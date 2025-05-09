import os
import sys
import time
import threading
import logging
import pygame

# Optional systemd integration
try:
    import systemd.daemon  # type: ignore
    has_systemd = True
except ImportError:
    has_systemd = False

logger = logging.getLogger(__name__)

class Watchdog:
    """Watchdog to monitor the application and restart it if it crashes."""
    
    def __init__(self, check_interval=30, player=None, shutdown_event=None):
        """Initialize the watchdog.
        
        Args:
            check_interval: How often to check system health in seconds
            player: Reference to player object for saving state and health checks
            shutdown_event: Event to check for application shutdown
        """
        self.check_interval = check_interval
        self.last_heartbeat = time.time()
        self.running = True
        self.thread = threading.Thread(target=self._monitor, daemon=True)
        self.player = player
        self.shutdown_event = shutdown_event
        self.restart_in_progress = False
        
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
        while self.running and (not self.shutdown_event or not self.shutdown_event.is_set()):
            time_since_heartbeat = time.time() - self.last_heartbeat
            
            # If no heartbeat for more than 2x the interval, restart
            if time_since_heartbeat > (self.check_interval * 2):
                logger.error(f"[ERROR] Watchdog detected no heartbeat for {time_since_heartbeat:.1f} seconds. Restarting application...")
                self._restart_application()
                return
                
            # Check other critical components
            try:
                if self.player and not pygame.mixer.get_init():
                    logger.error("[ERROR] Watchdog detected pygame mixer failure. Restarting application...")
                    self._restart_application()
                    return
            except Exception as e:
                logger.error(f"[ERROR] Watchdog error during health check: {e}")
                
            time.sleep(self.check_interval)
            
    def _restart_application(self):
        """Restart the entire application."""
        if self.restart_in_progress:
            return
            
        self.restart_in_progress = True
        logger.info("[RESTART] Initiating application restart...")
        
        # Save state before restarting
        if self.player:
            from src.config import save_state
            save_state(self.player.current_state())
            
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