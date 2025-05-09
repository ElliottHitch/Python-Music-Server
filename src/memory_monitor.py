import os
import gc
import logging
import threading
import time
import psutil

logger = logging.getLogger(__name__)

class MemoryMonitor:
    """Monitor and manage memory usage to prevent OOM on resource-constrained devices."""
    
    def __init__(self, check_interval=60, gc_threshold=85.0, critical_threshold=90.0, player=None, shutdown_event=None):
        """Initialize the memory monitor.
        
        Args:
            check_interval: How often to check memory in seconds
            gc_threshold: Memory percentage at which to trigger garbage collection
            critical_threshold: Memory percentage at which to take critical action
            player: Reference to the player object for cleanup operations
            shutdown_event: Event to check for application shutdown
        """
        self.check_interval = check_interval
        self.gc_threshold = gc_threshold
        self.critical_threshold = critical_threshold
        self.player = player
        self.shutdown_event = shutdown_event
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
        while self.running and (not self.shutdown_event or not self.shutdown_event.is_set()):
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
        if self.player:
            if hasattr(self.player, '_cleanup_resources'):
                logger.info("[CLEANUP] Cleaning up all player resources")
                self.player._cleanup_resources("all")
                
            # Clear any in-memory caches if they exist
            if hasattr(self.player, 'clear_cache'):
                logger.info("[CLEANUP] Clearing player cache")
                self.player.clear_cache()
        
        # Log memory after cleanup
        memory_percent = psutil.virtual_memory().percent
        process_memory = self.process.memory_info().rss / 1024 / 1024  # MB
        logger.info(f"[MEMORY] Memory after cleanup: System {memory_percent:.1f}%, Process {process_memory:.1f}MB")
    
    def handle_idle_cleanup(self):
        """Handle resource cleanup when player is idle."""
        logger.info("[IDLE] Player idle - releasing unused resources")
        
        # Clean up player resources if available
        if self.player and hasattr(self.player, '_cleanup_resources'):
            self.player._cleanup_resources("all")
            return True
        return False
    
    def stop(self):
        """Stop the memory monitor."""
        self.running = False 