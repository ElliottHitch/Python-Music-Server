import os
import json
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class SongCache:
    """
    Persistent cache system for audio files metadata.
    Caches song information to avoid recalculating durations and metadata
    on every application start.
    """
    def __init__(self, cache_path="src/song_cache.json"):
        self.cache_path = cache_path
        self.cache = self._load_cache()
        self.modified = False
        
    def _load_cache(self):
        """Load the song cache from disk"""
        try:
            if os.path.exists(self.cache_path):
                with open(self.cache_path, 'r') as f:
                    cache = json.load(f)
                logger.info(f"[OK] Loaded song cache with {len(cache['files'])} entries")
                return cache
            else:
                logger.info("[INFO] No song cache found, creating new one")
                return {
                    "version": 1,
                    "last_updated": datetime.now().isoformat(),
                    "files": {}
                }
        except Exception as e:
            logger.error(f"[ERROR] Error loading song cache: {e}")
            return {
                "version": 1,
                "last_updated": datetime.now().isoformat(),
                "files": {}
            }
            
    def save_cache(self):
        """Save the song cache to disk"""
        if not self.modified:
            return
            
        try:
            self.cache["last_updated"] = datetime.now().isoformat()
            with open(self.cache_path, 'w') as f:
                json.dump(self.cache, f, indent=2)
            logger.info(f"[OK] Saved song cache with {len(self.cache['files'])} entries")
            self.modified = False
        except Exception as e:
            logger.error(f"[ERROR] Error saving song cache: {e}")
            
    def get_cached_audio_files(self, folder, get_duration_func=None):
        """Get audio files, using cache where possible"""
        valid_extensions = {'.mp3', '.wav', '.ogg'}
        files_list = []
        cache_hits = 0
        cache_misses = 0
        new_files = []  # Track brand new files for normalization
        current_files = set()
        
        # Scan the actual folder
        logger.info(f"[SCAN] Scanning audio folder: {folder}")
        start_time = time.time()
        
        try:
            for file in os.listdir(folder):
                file_path = os.path.join(folder, file)
                current_files.add(file_path)
                
                # Skip non-audio files
                ext = os.path.splitext(file)[1].lower()
                if ext not in valid_extensions:
                    continue
                    
                # Get file stats
                try:
                    stat = os.stat(file_path)
                    mtime = stat.st_mtime
                    size = stat.st_size
                except Exception as e:
                    logger.error(f"[ERROR] Error getting file stats for {file_path}: {e}")
                    continue
                    
                # Check if file is in cache and unchanged
                if (file_path in self.cache['files'] and 
                        self.cache['files'][file_path].get('mtime') == mtime and 
                        self.cache['files'][file_path].get('size') == size):
                    # Cache hit - use cached data
                    entry = {
                        "path": file_path,
                        "name": file,
                        "duration": self.cache['files'][file_path].get('duration'),
                        "normalized": self.cache['files'][file_path].get('normalized', False)
                    }
                    files_list.append(entry)
                    cache_hits += 1
                else:
                    # Cache miss - create new entry with placeholder duration
                    duration = None
                    # If a duration function is provided, calculate it now
                    if get_duration_func:
                        try:
                            duration = get_duration_func(file_path)
                        except Exception as e:
                            logger.error(f"[ERROR] Error calculating duration for {file}: {e}")
                    
                    # Check if this is a new file or an updated file
                    is_new = file_path not in self.cache['files']
                    if is_new:
                        new_files.append(file_path)  # Add to list of new files
                        logger.info(f"[NEW] Found new audio file: {file}")
                    
                    entry = {
                        "path": file_path,
                        "name": file,
                        "duration": duration,
                        "normalized": False  # Default to not normalized
                    }
                    files_list.append(entry)
                    cache_misses += 1
                    
                    # Update cache
                    self.cache['files'][file_path] = {
                        'mtime': mtime,
                        'size': size,
                        'duration': duration,
                        'normalized': False,
                        'is_new': is_new,  # Mark if this was a new file
                        'last_accessed': datetime.now().isoformat()
                    }
                    self.modified = True
            
            # Also scan for normalized files if there's a normalized subdirectory
            normalized_folder = os.path.join(folder, "normalized")
            if os.path.exists(normalized_folder) and os.path.isdir(normalized_folder):
                logger.info(f"[SCAN] Scanning normalized audio folder: {normalized_folder}")
                for root, _, files in os.walk(normalized_folder):
                    for file in files:
                        normalized_file_path = os.path.join(root, file)
                        
                        # Skip non-audio files
                        ext = os.path.splitext(file)[1].lower()
                        if ext not in valid_extensions:
                            continue
                        
                        # Determine the original file path
                        rel_path = os.path.relpath(normalized_file_path, normalized_folder)
                        original_file_path = os.path.join(folder, rel_path)
                        
                        # Add to the current files set so we don't prune it
                        current_files.add(normalized_file_path)
                        
                        # Update cache for normalized file
                        try:
                            stat = os.stat(normalized_file_path)
                            mtime = stat.st_mtime
                            size = stat.st_size
                            
                            # Check if normalized file is in cache and unchanged
                            if (normalized_file_path in self.cache['files'] and 
                                    self.cache['files'][normalized_file_path].get('mtime') == mtime and 
                                    self.cache['files'][normalized_file_path].get('size') == size):
                                # Already in cache, nothing to do
                                continue
                            
                            # Update or add normalized file to cache
                            duration = None
                            if get_duration_func:
                                try:
                                    duration = get_duration_func(normalized_file_path)
                                except Exception as e:
                                    logger.error(f"[ERROR] Error calculating duration for normalized file {file}: {e}")
                            
                            # Update cache entry for normalized file
                            self.cache['files'][normalized_file_path] = {
                                'mtime': mtime,
                                'size': size,
                                'duration': duration,
                                'normalized': True,
                                'original_path': original_file_path,
                                'last_accessed': datetime.now().isoformat()
                            }
                            self.modified = True
                            
                            # We don't add normalized files to files_list here
                            # as they'll be added by get_audio_files_with_normalization
                            
                        except Exception as e:
                            logger.error(f"[ERROR] Error processing normalized file {normalized_file_path}: {e}")
            
            # Remove deleted files from cache
            cached_paths = list(self.cache['files'].keys())
            removed = 0
            for path in cached_paths:
                if path not in current_files:
                    del self.cache['files'][path]
                    removed += 1
                    self.modified = True
            
            if removed > 0:
                logger.info(f"[CLEANUP] Removed {removed} deleted files from cache")
                    
            # Save updated cache
            self.save_cache()
            
            end_time = time.time()
            logger.info(f"[OK] Found {len(files_list)} audio files ({cache_hits} from cache, {cache_misses} new) in {end_time-start_time:.2f}s")
            
            # Store the new files list for apps to access
            self.new_files = new_files
            
            return files_list
        except Exception as e:
            logger.error(f"[ERROR] Error scanning folder {folder}: {e}")
            return []
    
    def get_new_files(self):
        """Return the list of new files detected during the last scan"""
        return getattr(self, 'new_files', [])
    
    def update_song_duration(self, file_path, duration):
        """Update a song's duration in the cache"""
        if file_path in self.cache['files']:
            self.cache['files'][file_path]['duration'] = duration
            self.cache['files'][file_path]['last_accessed'] = datetime.now().isoformat()
            self.modified = True
            return True
        return False

    def update_batch(self, updates, save=True):
        """Update multiple songs in the cache at once
        
        Args:
            updates: Dictionary of {file_path: duration} pairs
            save: Whether to save the cache after updating
            
        Returns:
            int: Number of records updated
        """
        count = 0
        now = datetime.now().isoformat()
        
        for file_path, duration in updates.items():
            if file_path in self.cache['files']:
                self.cache['files'][file_path]['duration'] = duration
                self.cache['files'][file_path]['last_accessed'] = now
                count += 1
                self.modified = True
        
        if save and self.modified:
            self.save_cache()
        
        return count
        
    def flush(self):
        """Save pending cache changes to disk"""
        self.save_cache()
        
    def prune_cache(self, max_age_days=90):
        """Remove entries that haven't been accessed in a long time"""
        now = datetime.now()
        removed = 0
        try:
            for path, data in list(self.cache['files'].items()):
                if 'last_accessed' in data:
                    last_accessed = datetime.fromisoformat(data['last_accessed'])
                    age_days = (now - last_accessed).days
                    if age_days > max_age_days:
                        del self.cache['files'][path]
                        removed += 1
                        self.modified = True
            
            if removed > 0:
                logger.info(f"[CLEANUP] Pruned {removed} old entries from cache")
                self.save_cache()
                
            return removed
        except Exception as e:
            logger.error(f"[ERROR] Error pruning cache: {e}")
            return 0

    def update_normalized_status(self, file_path, normalized_path):
        """Update a file's normalized status in the cache"""
        if file_path in self.cache['files']:
            self.cache['files'][file_path]['has_normalized'] = True
            self.cache['files'][file_path]['normalized_path'] = normalized_path
            self.cache['files'][file_path]['last_accessed'] = datetime.now().isoformat()
            self.modified = True
            return True
        return False 