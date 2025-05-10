import os
import atexit
import asyncio
import logging
import threading
import pygame
import websockets
import time
import schedule
import signal
import sys
import gc
import psutil
import subprocess
import platform
from flask import Flask

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

try:
    import systemd.daemon
    has_systemd = True
except ImportError:
    has_systemd = False

setup_logger()
logger = logging.getLogger(__name__)
def setup_scheduler(player_instance):
    # Get scheduled times from config or use defaults
    pause_time = config.get("scheduler", {}).get("pause_time", "19:00")
    resume_time = config.get("scheduler", {}).get("resume_time", "10:00")
    
    logger.info(f"[SCHEDULER] Configured to pause at {pause_time} and resume at {resume_time}")
    
    # Define functions for scheduled tasks with proper logging
    def scheduled_pause():
        try:
            logger.info("[SCHEDULER] Running scheduled pause task")
            if player_instance is None:
                logger.warning("[SCHEDULER] Player not available for scheduled pause")
                return
                
            if not player_instance.paused:
                player_instance.pause()
                logger.info("[SCHEDULER] Executed scheduled pause")
                # Save state after pause
                save_state(player_instance.current_state())
                # Broadcast state change to clients
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    new_loop.run_until_complete(broadcast_state_change(player_instance.current_state()))
                except Exception as e:
                    logger.error(f"[SCHEDULER] Failed to broadcast pause state change: {e}")
                finally:
                    new_loop.close()
            else:
                logger.info("[SCHEDULER] Player already paused, no action needed")
        except Exception as e:
            logger.error(f"[SCHEDULER] Error during scheduled pause: {e}")
    
    def scheduled_resume():
        try:
            logger.info("[SCHEDULER] Running scheduled resume task")
            if player_instance is None:
                logger.warning("[SCHEDULER] Player not available for scheduled resume")
                return
                
            if player_instance.paused:
                player_instance.play()
                logger.info("[SCHEDULER] Executed scheduled resume")
                # Save state after resume
                save_state(player_instance.current_state())
                # Broadcast state change to clients
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    new_loop.run_until_complete(broadcast_state_change(player_instance.current_state()))
                except Exception as e:
                    logger.error(f"[SCHEDULER] Failed to broadcast resume state change: {e}")
                finally:
                    new_loop.close()
            else:
                logger.info("[SCHEDULER] Player already playing, no action needed")
        except Exception as e:
            logger.error(f"[SCHEDULER] Error during scheduled resume: {e}")
    
    # Clear any existing scheduled jobs that might be left over
    schedule.clear()
    
    # Schedule the tasks
    schedule.every().day.at(pause_time).do(scheduled_pause)
    schedule.every().day.at(resume_time).do(scheduled_resume)
    
    # Run the scheduler in a separate thread
    def run_scheduler():
        logger.info("[SCHEDULER] Scheduler thread started")
        next_run = None
        
        while not shutdown_event.is_set():
            try:
                # Get next job run time for logging
                if schedule.get_jobs() and next_run != schedule.next_run():
                    next_run = schedule.next_run()
                    if next_run:
                        logger.info(f"[SCHEDULER] Next job will run at {next_run.strftime('%H:%M:%S')}")
                
                # Check pending tasks
                schedule.run_pending()
            except Exception as e:
                logger.error(f"[SCHEDULER] Error in scheduler: {e}")
            time.sleep(1)
        
        logger.info("[SCHEDULER] Scheduler thread stopped")
    
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.name = "SchedulerThread"
    scheduler_thread.start()
    logger.info(f"[SCHEDULER] Scheduler thread '{scheduler_thread.name}' started with id {scheduler_thread.ident}")
    return scheduler_thread


# Global variables
app = Flask(__name__, static_url_path='/static', static_folder='static')
player = None
config = load_config()
AUDIO_FOLDER = config["audio_folder"]
shutdown_event = threading.Event()
song_cache = SongCache()
scheduler_thread = None

def setup_cleanup_handlers():
    """Setup cleanup handlers for graceful shutdown"""
    atexit.register(lambda: player.cleanup() if player else None)
    atexit.register(lambda: save_state(player.current_state() if player else {}))
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def signal_handler(sig, frame):
    """Handle system signals for graceful shutdown"""
    logger.info(f"[SHUTDOWN] Received signal {sig}, shutting down...")
    shutdown_event.set()
    if player:
        player.cleanup()  
        save_state(player.current_state())
    logger.info("[SHUTDOWN] Waiting for threads to complete...")
    sys.exit(0)

async def heartbeat_task(watchdog):
    """Task to periodically update the watchdog heartbeat."""
    while not shutdown_event.is_set():
        watchdog.heartbeat()
        await asyncio.sleep(15) 

def pygame_event_handler():
    """Thread to handle pygame events like song end."""
    logger.info("[OK] Pygame event handler thread started")
    last_pos = 0
    idle_timeout = 180 
    last_local_activity = time.time()
    
    while not shutdown_event.is_set():
        current_time = time.time()
        
        # Check if song has ended
        if player and not player.paused and pygame.mixer.music.get_busy() == 0:
            if last_pos > 0:
                current_song = player.track_list[player.current_index]['name']
                logger.info(f"[PLAYER] Song ended: {current_song}")
                player.next()
                
                last_pos = 0
                last_local_activity = current_time
                state = player.current_state()
                save_state(state)
                
                # Broadcast state change to clients
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    new_loop.run_until_complete(broadcast_state_change(state))
                except Exception as e:
                    logger.error(f"[ERROR] Failed to broadcast state change: {e}")
                finally:
                    new_loop.close()
            
        if player and not player.paused and pygame.mixer.music.get_busy() == 1:
            last_pos = pygame.mixer.music.get_pos()
            last_local_activity = current_time 
            
        # Check idle timeout
        last_websocket_activity = get_last_websocket_activity()
        last_activity = max(last_local_activity, last_websocket_activity)
            
        if player and current_time - last_activity > idle_timeout:
            if not pygame.mixer.music.get_busy() or player.paused:
                app.memory_monitor.handle_idle_cleanup()
                last_local_activity = current_time
            
        time.sleep(0.1) 

async def start_servers():
    """Start WebSocket and Flask servers"""
    watchdog = Watchdog(check_interval=30, player=player, shutdown_event=shutdown_event)
    watchdog.start()
    
    memory_monitor = MemoryMonitor(check_interval=60, player=player, shutdown_event=shutdown_event)
    memory_monitor.start()
    
    app.memory_monitor = memory_monitor
    
    heartbeat_task_obj = asyncio.create_task(heartbeat_task(watchdog))
    
    event_thread = threading.Thread(target=pygame_event_handler, daemon=True)
    event_thread.start()
    
    ws_server = await websockets.serve(
        lambda ws, path: websocket_handler(ws, player, save_state),
        "0.0.0.0", 
        8765
    )
    
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, lambda: app.run(
        host="0.0.0.0", 
        port=5000, 
        debug=False, 
        use_reloader=False,
        threaded=True
    ))
    
    watchdog.heartbeat()
    
    # Notify systemd if available
    if has_systemd:
        try:
            systemd.daemon.notify("READY=1")
            logger.info("[OK] Notified systemd that service is ready")
        except Exception as e:
            logger.error(f"[ERROR] Failed to notify systemd ready status: {e}")
    
    try:
        while not shutdown_event.is_set():
            await asyncio.sleep(1)
    finally:
        heartbeat_task_obj.cancel()
        ws_server.close()
        await ws_server.wait_closed()
        logger.info("[OK] WebSocket server closed")
        watchdog.stop()
        memory_monitor.stop()
        logger.info("[OK] Watchdog and memory monitor stopped")
        if player:
            player.cleanup()
        logger.info("[OK] Player resources cleaned up")
        logger.info("[OK] Event processing stopped")

def setup_audio_system():
    """Initialize the audio system and player"""
    global player
    
    try:
        pygame.mixer.init(
            frequency=44100,
            size=-16,
            channels=2,
            buffer=2048  
        )
        logger.info("[OK] Pygame mixer initialized with optimized settings.")
    except pygame.error as e:
        logger.error(f"[ERROR] Failed to initialize Pygame mixer: {e}")
        exit(1)
        
    audio_normalizer = AudioNormalizer(AUDIO_FOLDER)
    logger.info(f"[OK] Audio normalizer initialized, normalized files in {audio_normalizer.normalized_folder}")

    audio_files, files_to_normalize = ensure_files_in_playlist(None, song_cache, audio_normalizer, AUDIO_FOLDER)
    
    try:
        player = PygamePlayer(audio_files)
        player.audio_normalizer = audio_normalizer
    except ValueError as e:
        logger.error(e)
        exit(1)

    audio_normalizer.player = player

    if files_to_normalize:
        logger.info(f"[NORMALIZE] Starting normalization of {len(files_to_normalize)} files")
        audio_normalizer.normalize_files_background(files_to_normalize)
        
    return audio_normalizer

def set_system_volume_to_max():
    """Set the operating system volume to maximum level"""
    system = platform.system()
    try:
        if system == 'Linux':
            # For Raspberry Pi and most Linux systems
            
            # Try ALSA (standard Linux audio system)
            try:
                # Set main mixer controls
                subprocess.run(['amixer', 'set', 'Master', '100%'], check=False)
                subprocess.run(['amixer', 'set', 'PCM', '100%'], check=False)
                
                # Try common Raspberry Pi specific mixers
                subprocess.run(['amixer', 'set', 'Headphone', '100%'], check=False)
                subprocess.run(['amixer', 'set', 'Speaker', '100%'], check=False)
                subprocess.run(['amixer', 'set', 'Digital', '100%'], check=False)
                
                # HDMI specific (for Raspberry Pi)
                subprocess.run(['amixer', '-c', '0', 'set', 'HDMI', '100%'], check=False)
                
                logger.info("[VOLUME] Set ALSA system volume to maximum")
            except Exception as e:
                logger.warning(f"[VOLUME] Failed to set ALSA volume: {e}")
                
            # Try PulseAudio as fallback
            try:
                subprocess.run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', '100%'], check=False)
                logger.info("[VOLUME] Set PulseAudio system volume to maximum")
            except Exception as e:
                logger.warning(f"[VOLUME] Failed to set PulseAudio volume: {e}")
                
        elif system == 'Windows':
            # On Windows we could use pycaw library, but for now just log that it's not implemented
            logger.info("[VOLUME] Setting Windows system volume not implemented")
            
        elif system == 'Darwin':  # macOS
            try:
                subprocess.run(['osascript', '-e', 'set volume output volume 100'], check=False)
                logger.info("[VOLUME] Set macOS system volume to maximum")
            except Exception as e:
                logger.warning(f"[VOLUME] Failed to set macOS volume: {e}")
    except Exception as e:
        logger.error(f"[VOLUME] Failed to set system volume: {e}")
        
    # Also set the pygame mixer volume to maximum
    pygame.mixer.music.set_volume(1.0)
    logger.info("[VOLUME] Set pygame mixer volume to maximum")

def init_app():
    """Initialize the Flask app"""
    audio_normalizer = setup_audio_system()
    
    setup_routes(app, AUDIO_FOLDER, player)
    setup_cleanup_handlers()
    
    # Set system volume to maximum
    set_system_volume_to_max()
    
    app.song_cache = song_cache
    app.config['AUDIO_FOLDER'] = AUDIO_FOLDER
    app.audio_normalizer = audio_normalizer
    
    # Restore previous state if it exists
    restore_player_state()
    
    return app

def restore_player_state():
    """Restore player state from saved state file"""
    saved_state = load_state()
    if saved_state:
        player.current_index = saved_state.get("current_index", 0)
        player.shuffle_on = saved_state.get("shuffle", False)
        vol = saved_state.get("volume", 0.5)
        pygame.mixer.music.set_volume(vol)
    else:
        pygame.mixer.music.set_volume(0.5)
        
    player.paused = False
    player.load_track(player.current_index)
    pygame.mixer.music.play()

if __name__ == "__main__":
    # Enable garbage collection and set up signal handlers
    gc.enable()
    logger.info("[OK] Garbage collection enabled")
    setup_cleanup_handlers()
    
    # Initialize the application
    init_app()
    
    # Set up the scheduler after player is initialized
    scheduler_thread = setup_scheduler(player)
    
    # Start the servers
    asyncio.run(start_servers()) 