import os
import random
import logging
import pygame
import gc
import threading
import time

logger = logging.getLogger(__name__)

def format_duration(seconds):
    if seconds is None or seconds < 0:
        return "--:--"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"

def get_duration(file_path):
    """Get audio file duration in seconds"""
    try:
        # Fast duration check for mp3
        sound = pygame.mixer.Sound(file_path)
        duration = sound.get_length()  # in seconds
        # Release sound object to prevent memory leaks
        del sound
        return duration
    except Exception as e:
        logger.warning(f"[WARNING] Failed to get duration for {file_path}: {e}")
        return None

class PygamePlayer:
    def __init__(self, track_list):
        """
        Initialize the player with a list of tracks.
        
        Args:
            track_list: List of dictionaries containing track information
        """
        # Initialize pygame mixer if not already initialized
        if not pygame.mixer.get_init():
            pygame.mixer.init()
            
        if not track_list:
            raise ValueError("ERROR: No audio files found in the specified folder.")
        self.track_list = track_list
        self.current_index = 0
        self.paused = False
        self.shuffle_on = False
        self._cache = {}  # Memory cache for player data
        self._max_cache_size = 5  # Maximum number of cached items
        self.last_played = []  # Keep track of recently played for shuffle
        self.max_history = 10  # Maximum history size
        
        # Add lock for thread safety
        self._lock = threading.RLock()
        
        # Garbage collection tracking
        self._cleanup_count = 0
        self._last_gc_time = time.time()
        
        # Add thread for monitoring track end
        self._playback_monitor = None
        self._monitor_active = False
        
        # Load first track
        self.load_track(self.current_index)

    def _should_run_gc(self):
        """
        Determine if garbage collection should run based on 
        frequency and time since last collection
        """
        current_time = time.time()
        
        # Run GC if it's been more than 5 minutes
        if current_time - self._last_gc_time > 300:  # 5 minutes
            self._last_gc_time = current_time
            return True
            
        # Otherwise, run occasionally (10% chance after every 5 cleanups)
        self._cleanup_count += 1
        if self._cleanup_count >= 5 and random.random() < 0.1:
            self._cleanup_count = 0
            self._last_gc_time = current_time
            return True
            
        return False

    def _cleanup_resources(self, which="all"):
        """
        Clean up file resources
        
        Args:
            which: What to clean up - "all", "current", or "next" (simplified version)
        """
        # We've simplified to direct file loading, so less cleanup needed
        # Just log the cleanup for tracking
        logger.debug(f"INFO: Cleanup requested ({which})")
        
        # Suggest garbage collection after cleanup, but only occasionally
        if which == "all" and self._should_run_gc():
            logger.debug("INFO: Running garbage collection after resource cleanup")
            gc.collect()

    def load_track(self, index):
        """Load track at the specified index"""
        try:
            with self._lock:
                # Clean up any existing resources before loading new track
                self._cleanup_resources("all")
                
                # Clear pygame mixer if it's already initialized to free memory
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                    
                # Track loading - check if we've exceeded reasonable memory usage
                self._manage_cache()
                
                # Keep track of path for cache management
                current_path = self.track_list[index]['path']
                self._cache[current_path] = True  # Mark as recently used
                
                # Use direct file loading for reliability
                pygame.mixer.music.load(current_path)
                logger.info(f"[OK] Loaded track: {self.track_list[index]['name']}")
                    
        except Exception as e:
            logger.error(f"[ERROR] Error loading track {self.track_list[index]['name']}: {e}")
            raise  # Re-raise the exception to prevent inconsistent state

    def _manage_cache(self):
        """Manage cache size to prevent memory issues"""
        # If cache exceeds max size, clear oldest items
        if len(self._cache) > self._max_cache_size:
            logger.info(f"INFO: Clearing audio cache (size: {len(self._cache)})")
            # Keep only the most recent half of items
            keep_count = max(2, self._max_cache_size // 2)
            keys_to_remove = list(self._cache.keys())[:-keep_count]
            for key in keys_to_remove:
                del self._cache[key]
            
            # Only run garbage collection occasionally
            if self._should_run_gc():
                logger.debug("INFO: Running garbage collection after cache cleanup")
                gc.collect()
            
    def clear_cache(self):
        """Clear the entire cache to free memory"""
        if self._cache:
            logger.info(f"INFO: Clearing entire audio cache (size: {len(self._cache)})")
            self._cache.clear()
            
            # Always run GC after a full cache clear
            self._last_gc_time = time.time()
            gc.collect()
            return True
        return False

    def _playback_monitor_thread(self):
        """Thread to monitor when playback ends and automatically advance"""
        while self._monitor_active:
            try:
                # Use a flag-based approach to signal track advancement
                next_track = False
                with self._lock:
                    if not self.paused and not pygame.mixer.music.get_busy():
                        next_track = True
                
                # Call next() directly if needed, but release the lock first
                if next_track:
                    # Call next() directly from this thread, but with proper lock handling
                    # next() already contains its own lock acquisition
                    self.next()
                
                time.sleep(0.5)  # Check every half second
            except Exception as e:
                logger.error(f"[ERROR] Exception in playback monitor: {e}")
                time.sleep(1.0)  # Sleep longer on error to avoid tight error loops

    def start_track(self):
        """Start playing the current track"""
        with self._lock:
            pygame.mixer.music.play()
            self.paused = False
            
            # Add to history
            if self.current_index not in self.last_played:
                self.last_played.append(self.current_index)
                if len(self.last_played) > self.max_history:
                    self.last_played.pop(0)
                
            # Start monitoring for end of track if not already
            if not self._monitor_active:
                self._monitor_active = True
                self._playback_monitor = threading.Thread(target=self._playback_monitor_thread)
                self._playback_monitor.daemon = True  # Thread will exit when main program exits
                self._playback_monitor.start()

    def play(self):
        """Play or resume playback"""
        with self._lock:
            if self.paused:
                # Track is paused, unpause it
                pygame.mixer.music.unpause()
                # Check if unpausing worked by seeing if music is now playing
                if not pygame.mixer.music.get_busy():
                    # Unpausing didn't work, reload and start the track
                    self.load_track(self.current_index)
                    self.start_track()
                else:
                    # Unpausing worked, update paused state
                    self.paused = False
            else:
                # Track wasn't paused, load and start it
                self.load_track(self.current_index)
                self.start_track()

    def pause(self):
        """Toggle pause state"""
        with self._lock:
            if self.paused:
                # If currently paused, unpause
                pygame.mixer.music.unpause()
                self.paused = False
            else:
                # If currently playing, pause
                pygame.mixer.music.pause()
                self.paused = True

    def next(self):
        """Skip to next track"""
        with self._lock:
            if self.shuffle_on and len(self.track_list) > 1:
                # More intelligent shuffle that avoids recent history
                available_indices = [i for i in range(len(self.track_list)) 
                                  if i not in self.last_played[-min(len(self.last_played), 5):]]
                
                # If we've played all songs recently, allow repeats but avoid current
                if not available_indices:
                    available_indices = [i for i in range(len(self.track_list)) if i != self.current_index]
                
                # Choose random from available
                if available_indices:
                    self.current_index = random.choice(available_indices)
                else:
                    self.current_index = (self.current_index + 1) % len(self.track_list)
            else:
                self.current_index = (self.current_index + 1) % len(self.track_list)
            
            # Load and start the next track    
            self.load_track(self.current_index)
            self.start_track()

    def back(self):
        """Go to the previous track in the playlist"""
        with self._lock:
            self.current_index = (self.current_index - 1) % len(self.track_list)
            self.load_track(self.current_index)
            self.start_track()

    def play_track(self, index):
        """Play a specific track by index"""
        with self._lock:
            self.current_index = index
            self.load_track(self.current_index)
            self.start_track()

    def set_volume(self, volume):
        """Set playback volume (0.0 to 1.0)"""
        pygame.mixer.music.set_volume(volume)

    def get_volume(self):
        """Get current playback volume"""
        return pygame.mixer.music.get_volume()

    def is_paused(self):
        """Check if playback is currently paused"""
        return self.paused

    def toggle_shuffle(self):
        """Toggle shuffle mode on/off"""
        self.shuffle_on = not self.shuffle_on

    def delete_track(self, index):
        """
        Delete a track from the filesystem and playlist
        
        Args:
            index: Index of track to delete
        """
        with self._lock:
            if index < 0 or index >= len(self.track_list):
                raise IndexError("ERROR: Invalid track index")
            
            song = self.track_list[index]
            file_path = song['path']
            
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"ERROR: File not found: {file_path}")
            
            try:
                # If the current track is being deleted, stop it first
                if index == self.current_index and pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                
                # Remove the file
                os.remove(file_path)
                
                # Update the playlist
                del self.track_list[index]
                
                # Update current_index if necessary
                if len(self.track_list) == 0:
                    self.current_index = 0
                    self.paused = True
                    return
                
                # Adjust current_index if the deleted track was before it
                if index < self.current_index:
                    self.current_index -= 1
                # If we deleted the current track, load the next one
                elif index == self.current_index:
                    if self.current_index >= len(self.track_list):
                        self.current_index = 0
                    self.load_track(self.current_index)
                    self.start_track()
            except PermissionError:
                logger.error(f"[ERROR] Permission denied when deleting {song['name']}")
                raise PermissionError(f"Cannot delete file: Permission denied for {file_path}")
            except Exception as e:
                logger.error(f"[ERROR] Error deleting track {song['name']}: {e}")
                raise
    
    def current_state(self):
        """
        Get the current player state for saving
        
        Returns:
            Dictionary with current state
        """
        return {
            'current_index': self.current_index,
            'volume': self.get_volume(),
            'paused': self.is_paused(),
            'shuffle': self.shuffle_on,
            'cache_size': len(self._cache)
        }
        
    def cleanup(self):
        """Clean up all resources when app is shutting down"""
        logger.info("INFO: Performing final player cleanup")
        # Stop monitoring thread
        self._monitor_active = False
        if self._playback_monitor and self._playback_monitor.is_alive():
            self._playback_monitor.join(timeout=1.0)
            
        self._cleanup_resources("all")
        self.clear_cache()
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except:
            pass 