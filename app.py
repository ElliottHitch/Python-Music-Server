import os
import atexit
import asyncio
import logging
import threading
import pygame
import websockets
import time
import signal
import sys
import gc
import psutil
from flask import Flask
import json

# Import from our modules
from src.logger import setup_logger
from src.config import load_config, load_state, save_state
from src.player import PygamePlayer
from src.audio_format import get_duration
from src.routes import setup_routes
from src.websocket_handler import websocket_handler, get_last_websocket_activity, broadcast_state_change
from src.song_cache import SongCache
from src.audio_normalizer import AudioNormalizer
from src.memory_monitor import MemoryMonitor
from src.watchdog import Watchdog
from src.downloader import ensure_files_in_playlist

# Optional systemd integration
try:
    import systemd.daemon  # type: ignore
    has_systemd = True
except ImportError:
    has_systemd = False

# Configure the logger
setup_logger()
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__, static_url_path='/static', static_folder='static')

# Global variables
player = None
config = load_config()
AUDIO_FOLDER = config["audio_folder"]
shutdown_event = threading.Event()
restart_in_progress = False
song_cache = SongCache()  # Initialize the song cache

# Register save_state to be called on exit
atexit.register(lambda: player.cleanup() if player else None)
atexit.register(lambda: save_state(player.current_state() if player else {}))

def signal_handler(sig, frame):
    """Handle termination signals gracefully."""
    logger.info(f"[SHUTDOWN] Received signal {sig}, shutting down...")
    shutdown_event.set()
    if player:
        player.cleanup()  # Clean up player resources properly
        save_state(player.current_state())
    sys.exit(0)

async def heartbeat_task(watchdog):
    """Task to periodically update the watchdog heartbeat."""
    while not shutdown_event.is_set():
        watchdog.heartbeat()
        await asyncio.sleep(15)  # Update heartbeat every 15 seconds

def pygame_event_handler():
    """Thread to handle pygame events like song end."""
    logger.info("[OK] Pygame event handler thread started")
    last_pos = 0
    idle_timeout = 180  # Release resources after 3 minutes of inactivity
    last_local_activity = time.time()
    
    while not shutdown_event.is_set():
        current_time = time.time()
        
        # Check if music has stopped playing
        if player and not player.paused and pygame.mixer.music.get_busy() == 0:
            # Only process if the position was non-zero before (meaning a song was playing)
            if last_pos > 0:
                current_song = player.track_list[player.current_index]['name']
                logger.info(f"[PLAYER] Song ended: {current_song}")
                player.next()
                # Reset last_pos after processing
                last_pos = 0
                # Update activity time
                last_local_activity = current_time
                # Save state and broadcast to all connected clients
                state = player.current_state()
                save_state(state)
                
                # Create a new event loop for this thread and run the async function
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    new_loop.run_until_complete(broadcast_state_change(state))
                except Exception as e:
                    logger.error(f"[ERROR] Failed to broadcast state change: {e}")
                finally:
                    new_loop.close()
            
        # Track the current position for next loop
        if player and not player.paused and pygame.mixer.music.get_busy() == 1:
            last_pos = pygame.mixer.music.get_pos()
            last_local_activity = current_time  # Playing is activity
            
        # Get latest activity time - either local or from websocket
        last_websocket_activity = get_last_websocket_activity()
        last_activity = max(last_local_activity, last_websocket_activity)
            
        # Check for idle timeout - release resources if player has been inactive
        if player and current_time - last_activity > idle_timeout:
            if not pygame.mixer.music.get_busy() or player.paused:
                # Access memory_monitor through the global app object
                app.memory_monitor.handle_idle_cleanup()
                # Don't release again for another timeout period
                last_local_activity = current_time
            
        time.sleep(0.1)  # Short sleep to prevent high CPU usage

async def start_servers():
    """Start WebSocket and Flask servers"""
    # Create and start the watchdog
    watchdog = Watchdog(check_interval=30, player=player, shutdown_event=shutdown_event)
    watchdog.start()
    
    # Create and start memory monitor
    memory_monitor = MemoryMonitor(check_interval=60, player=player, shutdown_event=shutdown_event)
    memory_monitor.start()
    
    # Make memory_monitor available to app for global access
    app.memory_monitor = memory_monitor
    
    # Create heartbeat task
    heartbeat_task_obj = asyncio.create_task(heartbeat_task(watchdog))
    
    # Start pygame event handler thread
    event_thread = threading.Thread(target=pygame_event_handler, daemon=True)
    event_thread.start()
    
    ws_server = await websockets.serve(
        lambda ws, path: websocket_handler(ws, player, save_state),
        "0.0.0.0", 
        8765,
        ping_interval=30,  # Increase ping interval to reduce network traffic
        ping_timeout=60    # Increase timeout for better reliability with poor connections
    )
    
    # Start Flask in a separate thread but don't await it
    # since app.run() blocks until the server stops
    loop = asyncio.get_running_loop()
    flask_thread = loop.run_in_executor(None, lambda: app.run(
        host="0.0.0.0", 
        port=5000, 
        debug=False, 
        use_reloader=False,
        threaded=True
    ))
    
    # Update heartbeat after servers are started
    watchdog.heartbeat()
    
    # Notify systemd that we're ready if available
    if has_systemd:
        try:
            systemd.daemon.notify("READY=1")
            logger.info("[OK] Notified systemd that service is ready")
        except Exception as e:
            logger.error(f"[ERROR] Failed to notify systemd ready status: {e}")
    
    try:
        # Wait for shutdown event
        while not shutdown_event.is_set():
            await asyncio.sleep(1)
    finally:
        # Clean shutdown
        heartbeat_task_obj.cancel()
        ws_server.close()
        await ws_server.wait_closed()
        logger.info("[OK] WebSocket server closed")
        watchdog.stop()
        memory_monitor.stop()
        logger.info("[OK] Watchdog and memory monitor stopped")
        # Cleanup player resources
        if player:
            player.cleanup()
        logger.info("[OK] Player resources cleaned up")
        logger.info("[OK] Event processing stopped")

def get_audio_files_with_normalization(audio_folder, normalizer):
    """Get all audio files, with preference for normalized versions."""
    # Get all original audio files using song_cache instead of deprecated function
    original_files = song_cache.get_cached_audio_files(audio_folder, None)
    
    # Replace paths with normalized versions where available
    normalized_files = []
    files_to_normalize = []
    
    for file_info in original_files:
        original_path = file_info['path']
        
        # Check if a normalized version exists
        if normalizer.is_normalized(original_path):
            # Use the normalized version
            normalized_path = normalizer.get_normalized_path(original_path)
            file_info['path'] = normalized_path
            file_info['normalized'] = True
            normalized_files.append(file_info)
        else:
            # Use the original version for now, but add to normalization queue
            file_info['normalized'] = False
            normalized_files.append(file_info)
            files_to_normalize.append(original_path)
    
    return normalized_files, files_to_normalize

if __name__ == "__main__":
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Enable garbage collection
    gc.enable()
    logger.info("[OK] Garbage collection enabled")
    
    # Initialize Pygame mixer
    try:
        # Use smaller buffer size for better memory efficiency
        pygame.mixer.init(
            frequency=44100,
            size=-16,
            channels=2,
            buffer=2048  # Smaller buffer = less memory, slightly higher CPU
        )
        logger.info("[OK] Pygame mixer initialized with optimized settings.")
    except pygame.error as e:
        logger.error(f"[ERROR] Failed to initialize Pygame mixer: {e}")
        exit(1)

    # Initialize audio normalizer
    audio_normalizer = AudioNormalizer(AUDIO_FOLDER)
    logger.info(f"[OK] Audio normalizer initialized, normalized files in {audio_normalizer.normalized_folder}")

    # Use the ensure_files_in_playlist function to make sure all normalized files are included
    audio_files, files_to_normalize = ensure_files_in_playlist(None, song_cache, audio_normalizer, AUDIO_FOLDER)
    
    # Initialize player
    try:
        player = PygamePlayer(audio_files)
        # Set audio_normalizer in player
        player.audio_normalizer = audio_normalizer
    except ValueError as e:
        logger.error(e)
        exit(1)

    # Set player reference in audio normalizer
    audio_normalizer.player = player

    # Start normalizing files after player is initialized
    if files_to_normalize:
        logger.info(f"[NORMALIZE] Starting normalization of {len(files_to_normalize)} files")
        audio_normalizer.normalize_files_background(files_to_normalize)

    # Setup routes
    setup_routes(app, AUDIO_FOLDER, player)

    # Make the song cache available to routes
    app.song_cache = song_cache
    app.config['AUDIO_FOLDER'] = AUDIO_FOLDER
    # Make the audio normalizer available to routes
    app.audio_normalizer = audio_normalizer
    
    # Load saved state if it exists
    saved_state = load_state()
    if saved_state:
        # Load settings from saved state
        player.current_index = saved_state.get("current_index", 0)
        player.shuffle_on = saved_state.get("shuffle", False)
        vol = saved_state.get("volume", 0.5)
        pygame.mixer.music.set_volume(vol)
        
        player.paused = False
        
        # Load track and start playing
        player.load_track(player.current_index)
        pygame.mixer.music.play()
    else:
        # No saved state, start playing automatically
        pygame.mixer.music.set_volume(0.5)
        player.paused = False
        player.load_track(player.current_index)
        pygame.mixer.music.play()

    # Start servers
    asyncio.run(start_servers()) 