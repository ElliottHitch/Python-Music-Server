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
        if not pygame.mixer.get_init():
            pygame.mixer.init()
            
        if not track_list:
            raise ValueError("ERROR: No audio files found in the specified folder.")
            
        self.track_list = track_list
        self.current_index = 0
        self.paused = False
        self.shuffle_on = False
        self._cache = {}  
        self._max_cache_size = 5
        self.last_played = []
        self.max_history = 10
        self.audio_normalizer = None
        
        self._lock = threading.RLock()
        
        self.load_track(self.current_index)

    def load_track(self, index):
        """Load track at the specified index"""
        try:
            with self._lock:
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                    
                if len(self._cache) > self._max_cache_size:
                    self._manage_cache()
                
                current_path = self.track_list[index]['path']
                self._cache[current_path] = True 
                
                pygame.mixer.music.load(current_path)
                logger.info(f"[OK] Loaded track: {self.track_list[index]['name']}")
                    
        except Exception as e:
            logger.error(f"[ERROR] Error loading track {self.track_list[index]['name']}: {e}")
            raise 

    def _manage_cache(self):
        """Manage cache size to prevent memory issues"""
        logger.info(f"INFO: Clearing audio cache (size: {len(self._cache)})")
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

    def _update_play_history(self):
        """Update the history of played tracks"""
        if self.current_index not in self.last_played:
            self.last_played.append(self.current_index)
            if len(self.last_played) > self.max_history:
                self.last_played.pop(0)

    def start_track(self):
        """Start playing the current track"""
        with self._lock:
            pygame.mixer.music.play()
            self.paused = False
            self._update_play_history()

    def play(self):
        """Play or resume playback"""
        with self._lock:
            if self.paused:
                pygame.mixer.music.unpause()
                if not pygame.mixer.music.get_busy():
                    self.load_track(self.current_index)
                    self.start_track()
                else:
                    self.paused = False
            else:
                self.load_track(self.current_index)
                self.start_track()

    def pause(self):
        """Toggle pause state"""
        with self._lock:
            if self.paused:
                pygame.mixer.music.unpause()
                self.paused = False
            else:
                pygame.mixer.music.pause()
                self.paused = True

    def _get_next_track_index(self):
        """Determine the next track to play based on shuffle setting"""
        if self.shuffle_on and len(self.track_list) > 1:
            recent = self.last_played[-min(len(self.last_played), 5):]
            available_indices = [i for i in range(len(self.track_list)) if i not in recent]

            if not available_indices:
                available_indices = [i for i in range(len(self.track_list)) if i != self.current_index]

            if available_indices:
                return random.choice(available_indices)
        
        return (self.current_index + 1) % len(self.track_list)

    def next(self):
        """Skip to next track"""
        with self._lock:
            self.current_index = self._get_next_track_index()
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
        """Delete a track from the playlist and file system"""
        with self._lock:
            if index < 0 or index >= len(self.track_list):
                raise IndexError("ERROR: Invalid track index")
            
            song = self.track_list[index]
            file_path = song['path']
            
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"ERROR: File not found: {file_path}")
            
            try:
             
                is_current_track = (index == self.current_index)
                
             
                if is_current_track and len(self.track_list) > 1:
                    
                    if index == len(self.track_list) - 1:
                        next_index = 0
                    else:
                        next_index = index  
                
                deleted_files = [file_path] 
                
                if self.audio_normalizer:
                    norm_folder = self.audio_normalizer.normalized_folder
                    original_folder = self.audio_normalizer.audio_folder
                    
                    if os.path.normpath(file_path).startswith(os.path.normpath(norm_folder)):
                        rel_path = os.path.relpath(file_path, norm_folder)
                        original_path = os.path.join(original_folder, rel_path)
                        if os.path.exists(original_path):
                            os.remove(original_path)
                            deleted_files.append(original_path)
                            logger.info(f"[DELETE] Removed original file: {original_path}")
                    else:
                        rel_path = os.path.relpath(file_path, original_folder)
                        normalized_path = os.path.join(norm_folder, rel_path)
                        if os.path.exists(normalized_path):
                            os.remove(normalized_path)
                            deleted_files.append(normalized_path)
                            logger.info(f"[DELETE] Removed normalized file: {normalized_path}")
                
                if file_path not in deleted_files and os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"[DELETE] Removed file: {file_path}")
                
                if is_current_track and pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                
                del self.track_list[index]
                
                if len(self.track_list) == 0:
                    self.current_index = 0
                    self.paused = False
                    return
                
                if is_current_track:
                    self.current_index = next_index
                    self.load_track(self.current_index)
                    self.start_track()
                elif index < self.current_index:
                    self.current_index -= 1
                
            except PermissionError:
                raise PermissionError(f"ERROR: Permission denied: {file_path}")
            except Exception as e:
                logger.error(f"[ERROR] Failed to delete file: {e}")
                raise

    def current_state(self):
        """Get the current player state as a dictionary"""
        with self._lock:
            return {
                "current_index": self.current_index,
                "playing": not self.paused and pygame.mixer.music.get_busy(),
                "paused": self.paused,
                "current_song": self.track_list[self.current_index]["name"] if self.track_list else "",
                "shuffle": self.shuffle_on,
                "volume": self.get_volume(),
            }

    def cleanup(self):
        """Clean up resources"""
        with self._lock:
            try:
                pygame.mixer.music.stop()
                self._cache.clear()
                logger.info("[OK] Player cleanup complete")
            except Exception as e:
                logger.error(f"[ERROR] Error during player cleanup: {e}") 