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
from src.player import PygamePlayer, get_duration
from src.routes import setup_routes
from src.websocket_handler import websocket_handler, get_last_websocket_activity, broadcast_state_change
from src.song_cache import SongCache
from src.audio_normalizer import AudioNormalizer

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

class Watchdog:
    """Watchdog to monitor the application and restart it if it crashes."""
    
    def __init__(self, check_interval=30):
        """Initialize the watchdog.
        
        Args:
            check_interval: How often to check system health in seconds
        """
        self.check_interval = check_interval
        self.last_heartbeat = time.time()
        self.running = True
        self.thread = threading.Thread(target=self._monitor, daemon=True)
        
    def start(self):
        """Start the watchdog monitor thread."""
        self.thread.start()
        logger.info("[OK] Watchdog monitor started")
        
    def heartbeat(self):
        """Update the heartbeat timestamp."""
        self.last_heartbeat = time.time()
        # Send systemd watchdog notification if available
        if has_systemd:
            try:
                systemd.daemon.notify("WATCHDOG=1")
            except Exception as e:
                logger.error(f"[ERROR] Failed to notify systemd watchdog: {e}")
        
    def _monitor(self):
        """Monitor thread that checks for system health."""
        while self.running and not shutdown_event.is_set():
            time_since_heartbeat = time.time() - self.last_heartbeat
            
            # If no heartbeat for more than 2x the interval, restart
            if time_since_heartbeat > (self.check_interval * 2):
                logger.error(f"[ERROR] Watchdog detected no heartbeat for {time_since_heartbeat:.1f} seconds. Restarting application...")
                self._restart_application()
                return
                
            # Check other critical components
            try:
                if player and not pygame.mixer.get_init():
                    logger.error("[ERROR] Watchdog detected pygame mixer failure. Restarting application...")
                    self._restart_application()
                    return
            except Exception as e:
                logger.error(f"[ERROR] Watchdog error during health check: {e}")
                
            time.sleep(self.check_interval)
            
    def _restart_application(self):
        """Restart the entire application."""
        global restart_in_progress
        if restart_in_progress:
            return
            
        restart_in_progress = True
        logger.info("[RESTART] Initiating application restart...")
        
        # Save state before restarting
        if player:
            save_state(player.current_state())
            
        # Use os.execv to restart the current process
        try:
            os.execv(sys.executable, ['python'] + sys.argv)
        except Exception as e:
            logger.error(f"[ERROR] Failed to restart application: {e}")
            # If we can't restart, exit and let the external watchdog handle it
            os._exit(1)
    
    def stop(self):
        """Stop the watchdog monitor."""
        self.running = False

class MemoryMonitor:
    """Monitor and manage memory usage to prevent OOM on resource-constrained devices."""
    
    def __init__(self, check_interval=60, gc_threshold=85.0, critical_threshold=90.0):
        """Initialize the memory monitor.
        
        Args:
            check_interval: How often to check memory in seconds
            gc_threshold: Memory percentage at which to trigger garbage collection
            critical_threshold: Memory percentage at which to take critical action
        """
        self.check_interval = check_interval
        self.gc_threshold = gc_threshold
        self.critical_threshold = critical_threshold
        self.running = True
        self.thread = threading.Thread(target=self._monitor, daemon=True)
        self.process = psutil.Process(os.getpid())
        self.last_gc_time = time.time()
        self.gc_min_interval = 300  # Minimum seconds between forced GC
        
    def start(self):
        """Start the memory monitor thread."""
        self.thread.start()
        logger.info("[OK] Memory monitor started")
        
    def _monitor(self):
        """Monitor thread that checks memory usage and takes appropriate actions."""
        while self.running and not shutdown_event.is_set():
            try:
                current_time = time.time()
                # Get memory usage as percentage
                memory_percent = psutil.virtual_memory().percent
                process_memory = self.process.memory_info().rss / 1024 / 1024  # MB
                
                # Log memory usage every interval
                logger.info(f"[MEMORY] Memory usage: System {memory_percent:.1f}%, Process {process_memory:.1f}MB")
                
                # If memory usage is high AND we haven't run GC recently, trigger garbage collection
                if (memory_percent > self.gc_threshold and 
                    current_time - self.last_gc_time > self.gc_min_interval):
                    self.force_garbage_collection()
                    self.last_gc_time = current_time
                
                # If memory usage is critical, take more aggressive action regardless of timing
                if memory_percent > self.critical_threshold:
                    self.handle_critical_memory()
                    self.last_gc_time = current_time
                
            except Exception as e:
                logger.error(f"[ERROR] Memory monitor error: {e}")
                
            time.sleep(self.check_interval)
    
    def force_garbage_collection(self):
        """Force Python garbage collection to free memory."""
        logger.info("[CLEANUP] Memory threshold exceeded, forcing garbage collection")
        collected = gc.collect()
        unreachable = gc.garbage
        logger.info(f"[CLEANUP] Garbage collection: {collected} objects collected, {len(unreachable)} unreachable objects")
        
    def handle_critical_memory(self):
        """Handle critical memory situation by taking aggressive actions."""
        logger.warning("[CRITICAL] CRITICAL MEMORY THRESHOLD EXCEEDED!")
        
        # Force more aggressive garbage collection
        logger.info("[CLEANUP] Performing full garbage collection")
        gc.collect(2)  # Full collection
        
        # Clean up player resources if available
        if player:
            if hasattr(player, '_cleanup_resources'):
                logger.info("[CLEANUP] Cleaning up all player resources")
                player._cleanup_resources("all")
                
            # Clear any in-memory caches if they exist
            if hasattr(player, 'clear_cache'):
                logger.info("[CLEANUP] Clearing player cache")
                player.clear_cache()
        
        # Log memory after cleanup
        memory_percent = psutil.virtual_memory().percent
        process_memory = self.process.memory_info().rss / 1024 / 1024  # MB
        logger.info(f"[MEMORY] Memory after cleanup: System {memory_percent:.1f}%, Process {process_memory:.1f}MB")
    
    def stop(self):
        """Stop the memory monitor."""
        self.running = False

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

def calculate_durations_background(player_instance):
    """Calculate durations for all tracks in a background thread."""
    logger.info("[INFO] Starting background duration calculation...")
    if not player_instance or not player_instance.track_list:
        logger.warning("[WARNING] Player or track list not available for duration calculation.")
        return

    # Use batch updates for better performance
    batch_size = 20
    duration_updates = {}
    
    for index, track in enumerate(player_instance.track_list):
        if track['duration'] is None:
            try:
                duration = get_duration(track['path'])
                track['duration'] = duration
                # Add to batch update
                duration_updates[track['path']] = duration
                
                # Periodically update cache in batches
                if len(duration_updates) >= batch_size:
                    if song_cache.update_batch(duration_updates):
                        logger.info(f"[OK] Calculated duration for {index + 1}/{len(player_instance.track_list)} tracks...")
                    duration_updates = {}  # Reset batch
                    
            except Exception as e:
                logger.error(f"[ERROR] Error calculating duration for {track['name']}: {e}")
                track['duration'] = -1  # Mark as error
    
    # Final batch update for durations
    if duration_updates:
        song_cache.update_batch(duration_updates)
    
    logger.info("[OK] Background duration calculation finished.")

def update_player_with_normalized_tracks(normalized_paths):
    """Callback to update player track list with newly normalized tracks."""
    if not player:
        logger.warning("[WARNING] Player not available to update with normalized tracks")
        return
        
    # Update paths in the player's track list to use normalized versions
    updated_count = 0
    for i, track in enumerate(player.track_list):
        original_path = track.get('path')
        
        # Skip already normalized tracks
        if track.get('normalized', False):
            continue
            
        # Find if this track has been normalized
        for norm_path in normalized_paths:
            # Check if this is the normalized version of the current track
            rel_path = os.path.relpath(norm_path, audio_normalizer.normalized_folder)
            orig_path = os.path.join(audio_normalizer.audio_folder, rel_path)
            
            if orig_path == original_path:
                # Update to use the normalized version
                logger.info(f"[NORMALIZE] Switching to normalized version: {norm_path}")
                player.track_list[i]['path'] = norm_path
                player.track_list[i]['normalized'] = True
                updated_count += 1
                break
    
    if updated_count > 0:
        logger.info(f"[NORMALIZE] Updated {updated_count} tracks to use normalized versions")
        # If currently playing a song that was normalized, reload it
        current_track = player.track_list[player.current_index]
        if current_track.get('normalized') and pygame.mixer.music.get_busy():
            # Save position
            pos = pygame.mixer.music.get_pos() / 1000.0  # Convert ms to seconds
            # Reload the track
            player.load_track(player.current_index)
            # Resume from position if possible
            if pos > 0:
                pygame.mixer.music.play(start=pos)

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
                broadcast_state_change(state)
            
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
                logger.info("[IDLE] Player idle - releasing unused resources")
                # Only release the next track resources, keep current track loaded
                player._cleanup_resources("next")
                # Don't release again for another timeout period
                last_local_activity = current_time
            
        time.sleep(0.1)  # Short sleep to prevent high CPU usage

async def start_servers():
    """Start WebSocket and Flask servers"""
    # Create and start the watchdog
    watchdog = Watchdog()
    watchdog.start()
    
    # Create and start memory monitor
    memory_monitor = MemoryMonitor()
    memory_monitor.start()
    
    # Create heartbeat task
    heartbeat_task_obj = asyncio.create_task(heartbeat_task(watchdog))
    
    # Start pygame event handler thread
    event_thread = threading.Thread(target=pygame_event_handler, daemon=True)
    event_thread.start()
    
    ws_server = await websockets.serve(
        lambda ws, path: websocket_handler(ws, player, save_state),
        "0.0.0.0", 
        8765,
        ping_interval=20,
        ping_timeout=30
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
    original_files = song_cache.get_cached_audio_files(audio_folder, get_duration)
    
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

    # Load audio files with normalization support
    audio_files, files_to_normalize = get_audio_files_with_normalization(AUDIO_FOLDER, audio_normalizer)

    # Prune old cache entries
    song_cache.prune_cache(max_age_days=90)

    # Initialize player
    try:
        player = PygamePlayer(audio_files)
    except ValueError as e:
        logger.error(e)
        exit(1)

    # Start normalizing files after player is initialized
    if files_to_normalize:
        logger.info(f"[NORMALIZE] Starting normalization of {len(files_to_normalize)} files")
        audio_normalizer.normalize_files_background(files_to_normalize, callback=update_player_with_normalized_tracks)

    # Start background duration calculation
    duration_thread = threading.Thread(
        target=calculate_durations_background, 
        args=(player,),
        daemon=True
    )
    duration_thread.start()

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