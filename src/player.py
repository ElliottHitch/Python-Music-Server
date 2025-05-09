import os
import random
import logging
import pygame
import threading
import time
from src.audio_format import format_duration, get_duration

logger = logging.getLogger(__name__)

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
        self.audio_normalizer = None  # Reference to audio normalizer
        
        # Add lock for thread safety
        self._lock = threading.RLock()
        
        # Add thread for monitoring track end
        self._playback_monitor = None
        self._monitor_active = False
        
        # Load first track
        self.load_track(self.current_index)

    def load_track(self, index):
        """Load track at the specified index"""
        try:
            with self._lock:
                # Clear pygame mixer if it's already initialized to free memory
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                    
                # Manage cache if needed
                if len(self._cache) > self._max_cache_size:
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
        logger.info(f"INFO: Clearing audio cache (size: {len(self._cache)})")
        # Keep only the most recent half of items
        keep_count = max(2, self._max_cache_size // 2)
        keys_to_remove = list(self._cache.keys())[:-keep_count]
        for key in keys_to_remove:
            del self._cache[key]

    def clear_cache(self):
        """Clear the entire cache to free memory"""
        if self._cache:
            logger.info(f"INFO: Clearing entire audio cache (size: {len(self._cache)})")
            self._cache.clear()
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
                # If the current track is being deleted, load the next one first
                is_current_track = (index == self.current_index)
                if is_current_track:
                    if pygame.mixer.music.get_busy():
                        pygame.mixer.music.stop()
                    
                    # If we're deleting the current track and there are more tracks,
                    # move to the next track before removing this one
                    if len(self.track_list) > 1:
                        # Calculate the new index to play (next song)
                        next_index = (index + 1) % len(self.track_list)
                        # Load and start this track
                        self.current_index = next_index
                        self.load_track(self.current_index)
                        self.start_track()
                
                # Delete normalized version if it exists
                if self.audio_normalizer:
                    # Check if this is a normalized file
                    norm_folder = self.audio_normalizer.normalized_folder
                    if os.path.normpath(file_path).startswith(os.path.normpath(norm_folder)):
                        # This is a normalized file, delete the original too
                        rel_path = os.path.relpath(file_path, norm_folder)
                        original_path = os.path.join(self.audio_normalizer.audio_folder, rel_path)
                        if os.path.exists(original_path):
                            os.remove(original_path)
                            logger.info(f"[DELETE] Removed original file: {original_path}")
                    else:
                        # This is an original file, delete the normalized version
                        normalized_path = self.audio_normalizer.get_normalized_path(file_path)
                        if os.path.exists(normalized_path):
                            os.remove(normalized_path)
                            logger.info(f"[DELETE] Removed normalized file: {normalized_path}")
                
                # Remove the file
                os.remove(file_path)
                logger.info(f"[DELETE] Removed file: {file_path}")
                
                # Update the playlist
                del self.track_list[index]
                
                # Update current_index if necessary
                if len(self.track_list) == 0:
                    self.current_index = 0
                    self.paused = True
                    return
                
                # If we deleted a track before the current one, adjust the index
                if not is_current_track and index < self.current_index:
                    self.current_index -= 1
                
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
            
        self.clear_cache()
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except:
            pass 