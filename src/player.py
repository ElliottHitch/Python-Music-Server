import os
import random
import logging
import pygame
import mmap
import gc
import threading
from mutagen.mp3 import MP3
import time

logger = logging.getLogger(__name__)

def format_duration(seconds):
    if seconds is None or seconds < 0:
        return "--:--"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"

def get_duration(file_path):
    """
    Calculate the duration of an audio file.
    This is an expensive operation that should be cached.
    """
    try:
        if file_path.lower().endswith('.mp3'):
            audio = MP3(file_path)
            return audio.info.length
        else:
            sound = pygame.mixer.Sound(file_path)
            return sound.get_length()
    except Exception as e:
        logger.exception(f"[ERROR] Error getting duration of {file_path}")
        return 0

class PygamePlayer:
    def __init__(self, track_list):
        """
        Initialize the player with a list of tracks.
        
        Args:
            track_list: List of dictionaries containing track information
        """
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
        
        # Garbage collection tracking
        self._cleanup_count = 0
        self._last_gc_time = time.time()
        
        # Track resources for proper cleanup
        self._current_file = None
        self._current_mmap = None
        
        # Next track preloading
        self._next_file = None
        self._next_mmap = None
        self._next_index = None
        self._preload_lock = threading.RLock()  # Thread safety for preloading
        
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
        Properly clean up file resources
        
        Args:
            which: What to clean up - "all", "current", or "next"
        """
        with self._preload_lock:
            if which in ["all", "current"]:
                logger.debug("INFO: Cleaning up current track resources")
                
                # Clean up memory map if exists
                if hasattr(self, '_current_mmap') and self._current_mmap:
                    try:
                        self._current_mmap.close()
                        logger.debug("INFO: Closed current memory map")
                    except Exception as e:
                        logger.error(f"[ERROR] Error closing current memory map: {e}")
                    self._current_mmap = None
                    
                # Clean up file handle if exists
                if hasattr(self, '_current_file') and self._current_file:
                    try:
                        self._current_file.close()
                        logger.debug("INFO: Closed current file handle")
                    except Exception as e:
                        logger.error(f"[ERROR] Error closing current file handle: {e}")
                    self._current_file = None
            
            if which in ["all", "next"]:
                logger.debug("INFO: Cleaning up next track resources")
                
                # Clean up next track resources
                if hasattr(self, '_next_mmap') and self._next_mmap:
                    try:
                        self._next_mmap.close()
                        logger.debug("INFO: Closed next track memory map")
                    except Exception as e:
                        logger.error(f"[ERROR] Error closing next track memory map: {e}")
                    self._next_mmap = None
                
                if hasattr(self, '_next_file') and self._next_file:
                    try:
                        self._next_file.close()
                        logger.debug("INFO: Closed next track file handle")
                    except Exception as e:
                        logger.error(f"[ERROR] Error closing next track file handle: {e}")
                    self._next_file = None
                
                self._next_index = None
        
        # Suggest garbage collection after cleanup, but only occasionally
        if which == "all" and self._should_run_gc():
            logger.debug("INFO: Running garbage collection after resource cleanup")
            gc.collect()

    def _use_preloaded_track(self):
        """Check if there's a preloaded track ready to use for the current index"""
        with self._preload_lock:
            # If we have a preloaded track matching the current index
            if (self._next_index == self.current_index and 
                self._next_file is not None and 
                self._next_mmap is not None):
                    
                # Clean up any existing current track
                self._cleanup_resources("current")
                
                # Move preloaded track to current
                self._current_file = self._next_file
                self._current_mmap = self._next_mmap
                
                # Reset preload placeholders
                self._next_file = None
                self._next_mmap = None
                self._next_index = None
                
                logger.info(f"[OK] Using preloaded track: {self.track_list[self.current_index]['name']}")
                return True
        
        return False

    def load_track(self, index):
        """Load track at the specified index"""
        try:
            # Check if the requested track is already preloaded
            if not self._use_preloaded_track():
                # Clean up current track resources (but keep next track preloaded)
                self._cleanup_resources("current")
                
                # Clear pygame mixer if it's already initialized to free memory
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                    
                # Track loading - check if we've exceeded reasonable memory usage
                self._manage_cache()
                
                # Keep track of path for cache management
                current_path = self.track_list[index]['path']
                self._cache[current_path] = True  # Mark as recently used
                
                # Try loading with memory mapping for better memory efficiency
                try:
                    # Open the file
                    self._current_file = open(current_path, 'rb')
                    # Create memory map
                    self._current_mmap = mmap.mmap(
                        self._current_file.fileno(), 
                        0,  # Whole file
                        access=mmap.ACCESS_READ
                    )
                    # Load from memory map
                    pygame.mixer.music.load(self._current_mmap)
                    logger.info(f"[OK] Loaded track with mmap: {self.track_list[index]['name']}")
                except Exception as e:
                    # Fallback to standard loading if memory mapping fails
                    logger.warning(f"[WARNING] Mmap loading failed, using standard: {e}")
                    self._cleanup_resources("current")  # Clean up failed resources
                    pygame.mixer.music.load(current_path)
                    logger.info(f"[OK] Loaded track with standard method: {self.track_list[index]['name']}")
            
            # After loading current track, preload the next track in background
            self._preload_next_track()
                
        except Exception as e:
            logger.error(f"[ERROR] Error loading track {self.track_list[index]['name']}: {e}")

    def _preload_next_track(self):
        """Preload the next track in a background thread for smoother transitions"""
        # Don't block the main thread for preloading
        preload_thread = threading.Thread(
            target=self._do_preload_next_track,
            daemon=True
        )
        preload_thread.start()
    
    def _do_preload_next_track(self):
        """Actually do the preloading work in a separate thread"""
        try:
            with self._preload_lock:
                # If already preloaded or no tracks, skip
                if self._next_mmap is not None or len(self.track_list) <= 1:
                    return
                
                # Determine next track index based on shuffle mode
                if self.shuffle_on:
                    # Use our intelligent shuffle algorithm to determine next track
                    available_indices = [i for i in range(len(self.track_list)) 
                                      if i != self.current_index and 
                                         i not in self.last_played[-min(len(self.last_played), 3):]]
                    
                    if available_indices:
                        next_index = random.choice(available_indices)
                    else:
                        next_index = (self.current_index + 1) % len(self.track_list)
                else:
                    # Sequential playback
                    next_index = (self.current_index + 1) % len(self.track_list)
                
                # Don't preload if it's the same as current (single track playlist)
                if next_index == self.current_index:
                    return
                
                # Get the path of the next track
                next_path = self.track_list[next_index]['path']
                
                # Clean up any existing next track resources
                self._cleanup_resources("next")
                
                # Preload the next track with memory mapping
                try:
                    self._next_file = open(next_path, 'rb')
                    self._next_mmap = mmap.mmap(
                        self._next_file.fileno(),
                        0,
                        access=mmap.ACCESS_READ
                    )
                    self._next_index = next_index
                    logger.info(f"[OK] Preloaded next track: {self.track_list[next_index]['name']}")
                except Exception as e:
                    logger.warning(f"[WARNING] Failed to preload next track: {e}")
                    # Clean up any partially loaded resources
                    self._cleanup_resources("next")
        except Exception as e:
            logger.error(f"[ERROR] Error in preload thread: {e}")

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

    def start_track(self):
        """Start playing the current track"""
        pygame.mixer.music.play()
        self.paused = False
        
        # Add to history
        if self.current_index not in self.last_played:
            self.last_played.append(self.current_index)
            if len(self.last_played) > self.max_history:
                self.last_played.pop(0)

    def play(self):
        """Play or resume playback"""
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
        
        # Preload the next track after starting this one
        self._preload_next_track()

    def back(self):
        """Go to the previous track in the playlist"""
        self.current_index = (self.current_index - 1) % len(self.track_list)
        self.load_track(self.current_index)
        self.start_track()
        # Preload the next track after going back
        self._preload_next_track()

    def play_track(self, index):
        """Play a specific track by index"""
        self.current_index = index
        self.load_track(self.current_index)
        self.start_track()
        # Preload the next track after selecting specific track
        self._preload_next_track()

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
        # Preload next track with new shuffle setting
        self._preload_next_track()

    def delete_track(self, index):
        """
        Delete a track from the filesystem and playlist
        
        Args:
            index: Index of track to delete
        """
        if index < 0 or index >= len(self.track_list):
            raise IndexError("ERROR: Invalid track index")
        song = self.track_list[index]
        if not os.path.exists(song['path']):
            raise FileNotFoundError(f"ERROR: File not found: {song['path']}")
        try:
            # If the current track is being deleted, move to the next track if available.
            if index == self.current_index:
                if len(self.track_list) > 1:
                    self.current_index = (index + 1) % len(self.track_list)
                    self.load_track(self.current_index)
                    self.start_track()
                else:
                    pygame.mixer.music.stop()
                    self.paused = True
            os.remove(song['path'])
            del self.track_list[index]
            if self.current_index >= len(self.track_list):
                self.current_index = 0
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
        self._cleanup_resources("all")
        self.clear_cache()
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except:
            pass 