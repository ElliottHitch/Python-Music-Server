import os
import logging
import subprocess
import threading
from pathlib import Path
from ffmpeg_normalize import FFmpegNormalize
from ffmpeg_normalize._errors import FFmpegNormalizeError
from src.audio_format import get_optimal_format, get_fallback_format

logger = logging.getLogger(__name__)

class AudioNormalizer:
    """Class to handle audio normalization using ffmpeg-normalize."""
    
    def __init__(self, audio_folder, normalized_folder=None, batch_size=5, player=None):
        """Initialize the normalizer.
        
        Args:
            audio_folder: Path to the folder containing original audio files
            normalized_folder: Path to store normalized files (defaults to audio_folder/normalized)
            batch_size: Number of files to process in a single batch (default: 5)
            player: Reference to the player object for track updates
        """
        self.audio_folder = audio_folder
        self.batch_size = batch_size
        self._player = player  # Initialize the internal player reference
        
        if normalized_folder is None:
            # Create a "normalized" subfolder in the audio folder
            self.normalized_folder = os.path.join(audio_folder, "normalized")
        else:
            self.normalized_folder = normalized_folder
            
        # Create the normalized folder if it doesn't exist
        os.makedirs(self.normalized_folder, exist_ok=True)
        
        # Keep track of files being normalized
        self.currently_normalizing = set()
        self.lock = threading.Lock()
        
    # Property for player reference that can be set after initialization
    @property
    def player(self):
        return self._player
        
    @player.setter
    def player(self, player):
        self._player = player
        
    def get_normalized_path(self, original_path):
        """Convert an original file path to its normalized equivalent.
        
        Args:
            original_path: Path to the original audio file
            
        Returns:
            Path to the normalized version of the file
        """
        # Skip if file is already in the normalized folder
        if os.path.normpath(original_path).startswith(os.path.normpath(self.normalized_folder)):
            logger.debug(f"[NORMALIZE] File {original_path} is already in normalized folder")
            return original_path
            
        # Get the relative path from the audio folder
        rel_path = os.path.relpath(original_path, self.audio_folder)
        # Join with normalized folder to get the normalized path
        normalized_path = os.path.join(self.normalized_folder, rel_path)
        
        # Ensure the directory structure exists
        os.makedirs(os.path.dirname(normalized_path), exist_ok=True)
        
        # First check if a WAV version exists (fallback format)
        wav_path = os.path.splitext(normalized_path)[0] + ".wav"
        if os.path.exists(wav_path):
            return wav_path
            
        # Otherwise return the standard path (using original extension)
        return normalized_path
    
    def is_normalized(self, file_path):
        """Check if a file has already been normalized.
        
        Args:
            file_path: Path to the original audio file
            
        Returns:
            True if a normalized version exists, False otherwise
        """
        # If the file is already in the normalized folder, it's normalized
        if os.path.normpath(file_path).startswith(os.path.normpath(self.normalized_folder)):
            return True
            
        normalized_path = self.get_normalized_path(file_path)
        
        # Check for mp3 version
        if os.path.exists(normalized_path):
            return True
            
        # Also check for wav version
        wav_path = os.path.splitext(normalized_path)[0] + ".wav"
        if os.path.exists(wav_path):
            return True
            
        return False
    
    def normalize_file(self, file_path, target_level=-14):
        """Normalize a single audio file.
        
        Args:
            file_path: Path to the audio file to normalize
            target_level: Target loudness level in LUFS (default: -14)
            
        Returns:
            Path to the normalized audio file, or None if normalization failed
        """
        with self.lock:
            # Check if this file is already being normalized
            if file_path in self.currently_normalizing:
                logger.info(f"[NORMALIZE] File {file_path} is already being normalized")
                return None
                
            # Add to the set of files being normalized
            self.currently_normalizing.add(file_path)
            
        # Get normalized path
        normalized_path = self.get_normalized_path(file_path)
        
        # Check if already normalized
        if os.path.exists(normalized_path):
            logger.info(f"[NORMALIZE] File already normalized: {normalized_path}")
            with self.lock:
                self.currently_normalizing.remove(file_path)
            return normalized_path
            
        # Get optimal format based on original file extension
        original_ext = os.path.splitext(file_path)[1]
        output_format, audio_codec = get_optimal_format(original_ext)
            
        try:
            logger.info(f"[NORMALIZE] Normalizing file: {file_path}")
            
            try:
                # First try with optimal format
                normalizer_kwargs = {
                    "normalization_type": "ebu", 
                    "target_level": target_level,
                    "output_format": output_format,
                    "loudness_range_target": 11.0  # Higher target for better music dynamics
                }
                
                # Add audio codec if specified
                if audio_codec:
                    normalizer_kwargs["audio_codec"] = audio_codec
                
                normalizer = FFmpegNormalize(**normalizer_kwargs)
                
                # Add the file and run normalization
                normalizer.add_media_file(file_path, normalized_path)
                normalizer.run_normalization()
                normalizer = None  # Release reference for GC
            except FFmpegNormalizeError as e:
                logger.warning(f"[WARNING] {output_format.upper()} normalization failed, trying fallback format: {e}")
                
                # If optimal format fails, try with fallback format (WAV)
                fallback_format, fallback_codec = get_fallback_format()
                
                # Change extension to fallback format
                normalized_path = os.path.splitext(normalized_path)[0] + f".{fallback_format}"
                
                # Create fallback normalizer
                normalizer_kwargs = {
                    "normalization_type": "ebu", 
                    "target_level": target_level,
                    "output_format": fallback_format,
                    "loudness_range_target": 11.0
                }
                
                # Add audio codec if specified
                if fallback_codec:
                    normalizer_kwargs["audio_codec"] = fallback_codec
                    
                normalizer = FFmpegNormalize(**normalizer_kwargs)
                
                # Add the file and run normalization
                normalizer.add_media_file(file_path, normalized_path)
                normalizer.run_normalization()
                normalizer = None  # Release reference for GC
            
            logger.info(f"[NORMALIZE] Successfully normalized: {file_path} -> {normalized_path}")
            return normalized_path
            
        except FFmpegNormalizeError as e:
            logger.error(f"[ERROR] FFmpeg normalization error: {e}")
            return None
        except Exception as e:
            logger.error(f"[ERROR] Error normalizing file {file_path}: {e}")
            return None
        finally:
            with self.lock:
                if file_path in self.currently_normalizing:
                    self.currently_normalizing.remove(file_path)
    
    def update_player_with_normalized_tracks(self, normalized_paths):
        """Update player track list with newly normalized tracks."""
        if not self._player:
            logger.warning("[WARNING] Player not available to update with normalized tracks")
            return
            
        # Update paths in the player's track list to use normalized versions
        updated_count = 0
        
        import pygame  # Import here to avoid circular imports
        
        for i, track in enumerate(self._player.track_list):
            original_path = track.get('path')
            
            # Skip already normalized tracks
            if track.get('normalized', False):
                continue
                
            # Find if this track has been normalized
            for norm_path in normalized_paths:
                # Check if this is the normalized version of the current track
                rel_path = os.path.relpath(norm_path, self.normalized_folder)
                orig_path = os.path.join(self.audio_folder, rel_path)
                
                if orig_path == original_path:
                    # Update to use the normalized version
                    logger.info(f"[NORMALIZE] Switching to normalized version: {norm_path}")
                    self._player.track_list[i]['path'] = norm_path
                    self._player.track_list[i]['normalized'] = True
                    updated_count += 1
                    break
        
        if updated_count > 0:
            logger.info(f"[NORMALIZE] Updated {updated_count} tracks to use normalized versions")
            # If currently playing a song that was normalized, reload it
            current_track = self._player.track_list[self._player.current_index]
            
            if current_track.get('normalized') and pygame.mixer.music.get_busy():
                # Save position
                pos = pygame.mixer.music.get_pos() / 1000.0  # Convert ms to seconds
                # Reload the track
                self._player.load_track(self._player.current_index)
                # Resume from position if possible
                if pos > 0:
                    pygame.mixer.music.play(start=pos)
                    
    def normalize_files_background(self, file_list, callback=None):
        """Normalize multiple files in a background thread.
        
        Args:
            file_list: List of file paths to normalize
            callback: Optional callback function to call when normalization is complete
                      If None and player is available, update_player_with_normalized_tracks
                      will be used
        """
        if not file_list:
            logger.info("[NORMALIZE] No files to normalize")
            return
            
        # If no callback is provided but player is available, use the built-in callback
        if callback is None and self._player is not None:
            callback = self.update_player_with_normalized_tracks
            
        # Filter files once to eliminate duplicates and already normalized files
        files_to_process = []
        skipped_count = 0
        
        for file_path in file_list:
            # Skip files already in the normalized folder
            if os.path.normpath(file_path).startswith(os.path.normpath(self.normalized_folder)):
                logger.debug(f"[NORMALIZE] Skipping file already in normalized folder: {file_path}")
                skipped_count += 1
                continue
                
            # Skip files that already have a normalized version
            if self.is_normalized(file_path):
                logger.debug(f"[NORMALIZE] Skipping file that already has a normalized version: {file_path}")
                skipped_count += 1
                continue
                
            # Skip if already being normalized
            with self.lock:
                if file_path in self.currently_normalizing:
                    logger.debug(f"[NORMALIZE] File already being normalized: {file_path}")
                    skipped_count += 1
                    continue
                    
            # Add to processing list
            files_to_process.append(file_path)
        
        if skipped_count > 0:
            logger.info(f"[NORMALIZE] Skipped {skipped_count} files that don't need normalization")
            
        if not files_to_process:
            logger.info("[NORMALIZE] No files to normalize after filtering")
            return
        
        # Create a weak copy of files_to_process to prevent circular references
        files_copy = list(files_to_process)
        
        # Mark files as being normalized to prevent duplicate processing
        with self.lock:
            for file_path in files_copy:
                self.currently_normalizing.add(file_path)
            
        def background_normalize():
            normalized_paths = []
            # Process files in batches
            for i in range(0, len(files_copy), self.batch_size):
                batch = files_copy[i:i+self.batch_size]
                logger.info(f"[NORMALIZE] Processing batch {i//self.batch_size + 1}/{(len(files_copy)-1)//self.batch_size + 1} ({len(batch)} files)")
                
                # Normalize this batch
                batch_paths = self.batch_normalize(batch)
                normalized_paths.extend(batch_paths)
            
            logger.info(f"[NORMALIZE] Completed normalization of {len(normalized_paths)}/{len(files_copy)} files")
            
            # Call the callback if provided and if any files were normalized
            if callback and normalized_paths:
                try:
                    callback(normalized_paths)
                    logger.info(f"[NORMALIZE] Successfully applied callback for {len(normalized_paths)} normalized files")
                except Exception as e:
                    logger.error(f"[ERROR] Error in normalization callback: {e}")
                    
            # Release files from currently normalizing
            with self.lock:
                for file_path in files_copy:
                    if file_path in self.currently_normalizing:
                        self.currently_normalizing.remove(file_path)
            
            # Clear local references
            normalized_paths = None
            files_copy = None
        
        thread = threading.Thread(target=background_normalize)
        thread.daemon = True
        thread.start()
        logger.info(f"[NORMALIZE] Started background normalization of {len(files_to_process)} files")
        
    def batch_normalize(self, file_list, target_level=-14):
        """Normalize multiple files in a single ffmpeg process.
        
        Args:
            file_list: List of file paths to normalize
            target_level: Target loudness level in LUFS (default: -14)
            
        Returns:
            List of normalized file paths
        """
        if not file_list:
            return []
        
        normalized_paths = []
        try:
            logger.info(f"[NORMALIZE] Batch normalizing {len(file_list)} files")
            
            # Get format options for primary and fallback
            primary_format, primary_codec = get_optimal_format('.mp3')  # Default to mp3 for batch
            fallback_format, fallback_codec = get_fallback_format()
            
            # Create primary normalizer
            primary_kwargs = {
                "normalization_type": "ebu", 
                "target_level": target_level,
                "output_format": primary_format,
                "loudness_range_target": 11.0
            }
            
            if primary_codec:
                primary_kwargs["audio_codec"] = primary_codec
                
            primary_normalizer = FFmpegNormalize(**primary_kwargs)
            
            # Create fallback normalizer
            fallback_kwargs = {
                "normalization_type": "ebu", 
                "target_level": target_level,
                "output_format": fallback_format,
                "loudness_range_target": 11.0
            }
            
            if fallback_codec:
                fallback_kwargs["audio_codec"] = fallback_codec
                
            fallback_normalizer = FFmpegNormalize(**fallback_kwargs)
            
            # Add files to the primary normalizer
            primary_files = []
            for file_path in file_list:
                normalized_path = self.get_normalized_path(file_path)
                
                # Skip if already normalized
                if os.path.exists(normalized_path):
                    logger.info(f"[NORMALIZE] File already normalized: {normalized_path}")
                    normalized_paths.append(normalized_path)
                    continue
                    
                primary_normalizer.add_media_file(file_path, normalized_path)
                primary_files.append((file_path, normalized_path))
            
            # Run mp3 normalization if files were added
            if primary_files:
                try:
                    logger.info(f"[NORMALIZE] Batch processing {len(primary_files)} files with MP3 output")
                    primary_normalizer.run_normalization()
                    # Add successfully normalized paths
                    for _, norm_path in primary_files:
                        if os.path.exists(norm_path):
                            normalized_paths.append(norm_path)
                except FFmpegNormalizeError as e:
                    logger.warning(f"[WARNING] MP3 batch normalization failed, falling back to WAV: {e}")
                    
                    # Fall back to WAV format for files that failed
                    for orig_path, mp3_path in primary_files:
                        if not os.path.exists(mp3_path):
                            # Try WAV instead
                            wav_path = os.path.splitext(mp3_path)[0] + ".wav"
                            fallback_normalizer.add_media_file(orig_path, wav_path)
                    
                    # Run WAV normalization
                    try:
                        fallback_normalizer.run_normalization()
                        # Check which files were normalized and add to results
                        for orig_path, mp3_path in primary_files:
                            wav_path = os.path.splitext(mp3_path)[0] + ".wav"
                            if os.path.exists(wav_path):
                                normalized_paths.append(wav_path)
                    except FFmpegNormalizeError as e2:
                        logger.error(f"[ERROR] WAV batch normalization also failed: {e2}")
            
            # Clear references to normalizers
            primary_normalizer = None
            fallback_normalizer = None
            primary_files = None
            
            logger.info(f"[NORMALIZE] Batch completed, {len(normalized_paths)}/{len(file_list)} files normalized")
            return normalized_paths
            
        except Exception as e:
            logger.error(f"[ERROR] Error during batch normalization: {e}")
            return normalized_paths 