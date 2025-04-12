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
from flask import Flask

# Import from our modules
from src.logger import setup_logger
from src.config import load_config, load_state, save_state
from src.player import PygamePlayer, get_audio_files, get_duration
from src.routes import setup_routes
from src.websocket_handler import websocket_handler

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
        logger.info("Watchdog monitor started")
        
    def heartbeat(self):
        """Update the heartbeat timestamp."""
        self.last_heartbeat = time.time()
        # Send systemd watchdog notification if available
        if has_systemd:
            try:
                systemd.daemon.notify("WATCHDOG=1")
            except Exception as e:
                logger.error(f"Failed to notify systemd watchdog: {e}")
        
    def _monitor(self):
        """Monitor thread that checks for system health."""
        while self.running and not shutdown_event.is_set():
            time_since_heartbeat = time.time() - self.last_heartbeat
            
            # If no heartbeat for more than 2x the interval, restart
            if time_since_heartbeat > (self.check_interval * 2):
                logger.error(f"Watchdog detected no heartbeat for {time_since_heartbeat:.1f} seconds. Restarting application...")
                self._restart_application()
                return
                
            # Check other critical components
            try:
                if player and not pygame.mixer.get_init():
                    logger.error("Watchdog detected pygame mixer failure. Restarting application...")
                    self._restart_application()
                    return
            except Exception as e:
                logger.error(f"Watchdog error during health check: {e}")
                
            time.sleep(self.check_interval)
            
    def _restart_application(self):
        """Restart the entire application."""
        global restart_in_progress
        if restart_in_progress:
            return
            
        restart_in_progress = True
        logger.info("Initiating application restart...")
        
        # Save state before restarting
        if player:
            save_state(player.current_state())
            
        # Use os.execv to restart the current process
        try:
            os.execv(sys.executable, ['python'] + sys.argv)
        except Exception as e:
            logger.error(f"Failed to restart application: {e}")
            # If we can't restart, exit and let the external watchdog handle it
            os._exit(1)
    
    def stop(self):
        """Stop the watchdog monitor."""
        self.running = False

# Register save_state to be called on exit
atexit.register(lambda: save_state(player.current_state() if player else {}))

def signal_handler(sig, frame):
    """Handle termination signals gracefully."""
    logger.info(f"Received signal {sig}, shutting down...")
    shutdown_event.set()
    if player:
        save_state(player.current_state())
    sys.exit(0)

def calculate_durations_background(player_instance):
    """Calculate durations for all tracks in a background thread."""
    logger.info("Starting background duration calculation...")
    if not player_instance or not player_instance.track_list:
        logger.warning("Player or track list not available for duration calculation.")
        return

    for index, track in enumerate(player_instance.track_list):
        if track['duration'] is None:
            try:
                track['duration'] = get_duration(track['path'])
                # Optional: Log progress every N tracks
                if (index + 1) % 50 == 0:
                     logger.info(f"Calculated duration for {index + 1}/{len(player_instance.track_list)} tracks...")
            except Exception as e:
                logger.error(f"Error calculating duration for {track['name']}: {e}")
                track['duration'] = -1 # Mark as error 

    logger.info("Background duration calculation finished.")

async def heartbeat_task(watchdog):
    """Task to periodically update the watchdog heartbeat."""
    while not shutdown_event.is_set():
        watchdog.heartbeat()
        await asyncio.sleep(15)  # Update heartbeat every 15 seconds

async def start_servers():
    """Start WebSocket and Flask servers"""
    # Create and start the watchdog
    watchdog = Watchdog()
    watchdog.start()
    
    # Create heartbeat task
    heartbeat_task_obj = asyncio.create_task(heartbeat_task(watchdog))
    
    ws_server = await websockets.serve(
        lambda ws, path: websocket_handler(ws, player, save_state),
        "0.0.0.0", 
        8765
    )
    
    # Start Flask in a separate thread but don't await it
    # since app.run() blocks until the server stops
    loop = asyncio.get_running_loop()
    flask_thread = loop.run_in_executor(None, lambda: app.run(host="0.0.0.0", port=5000, use_reloader=False))
    
    # Update heartbeat after servers are started
    watchdog.heartbeat()
    
    # Notify systemd that we're ready if available
    if has_systemd:
        try:
            systemd.daemon.notify("READY=1")
            logger.info("Notified systemd that service is ready")
        except Exception as e:
            logger.error(f"Failed to notify systemd ready status: {e}")
    
    try:
        # Wait for shutdown event
        while not shutdown_event.is_set():
            await asyncio.sleep(1)
    finally:
        # Clean shutdown
        heartbeat_task_obj.cancel()
        ws_server.close()
        await ws_server.wait_closed()
        watchdog.stop()

if __name__ == "__main__":
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize Pygame mixer *only* 
    try:
        pygame.mixer.init()
        logger.info("Pygame mixer initialized.")
    except pygame.error as e:
        logger.error(f"Failed to initialize Pygame mixer: {e}")
        # Decide if you want to exit or continue without audio
        exit(1) # Exit if mixer fails

    # Load audio files (without durations initially)
    audio_files = get_audio_files(AUDIO_FOLDER)
    
    # Initialize player
    try:
        player = PygamePlayer(audio_files)
    except ValueError as e:
        logger.error(e)
        exit(1)
    
    # Start background duration calculation
    duration_thread = threading.Thread(
        target=calculate_durations_background, 
        args=(player,),
        daemon=True # Allow program to exit even if this thread is running
    )
    duration_thread.start()
    
    # Setup routes
    setup_routes(app, AUDIO_FOLDER, player)
    
    # Load saved state if it exists
    saved_state = load_state()
    if saved_state:
        player.current_index = saved_state.get("current_index", 0)
        player.paused = saved_state.get("paused", True)
        player.shuffle_on = saved_state.get("shuffle", False)
        vol = saved_state.get("volume", 0.5)
        pygame.mixer.music.set_volume(vol)
        player.load_track(player.current_index)
        if player.paused:
            pygame.mixer.music.pause()
        else:
            pygame.mixer.music.play()
    else:
        pygame.mixer.music.set_volume(0.5)

    # Start servers
    asyncio.run(start_servers()) 