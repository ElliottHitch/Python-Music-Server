import os
import logging
import subprocess
import threading
from pathlib import Path
from ffmpeg_normalize import FFmpegNormalize
from ffmpeg_normalize._errors import FFmpegNormalizeError

logger = logging.getLogger(__name__)

class AudioNormalizer:
    """Class to handle audio normalization using ffmpeg-normalize."""
    
    def __init__(self, audio_folder, normalized_folder=None, batch_size=5):
        """Initialize the normalizer.
        
        Args:
            audio_folder: Path to the folder containing original audio files
            normalized_folder: Path to store normalized files (defaults to audio_folder/normalized)
            batch_size: Number of files to process in a single batch (default: 5)
        """
        self.audio_folder = audio_folder
        self.batch_size = batch_size
        
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
            Path to the normalized file if successful, None otherwise
        """
        with self.lock:
            if file_path in self.currently_normalizing:
                logger.info(f"[NORMALIZE] File {file_path} is already being normalized")
                return None
            self.currently_normalizing.add(file_path)
        
        try:
            normalized_path = self.get_normalized_path(file_path)
            
            # Skip if already normalized
            if os.path.exists(normalized_path):
                logger.info(f"[NORMALIZE] File already normalized: {normalized_path}")
                with self.lock:
                    self.currently_normalizing.remove(file_path)
                return normalized_path
            
            logger.info(f"[NORMALIZE] Normalizing: {file_path}")
            
            try:
                # First try with mp3 output
                normalizer = FFmpegNormalize(
                    normalization_type="ebu", 
                    target_level=target_level,
                    output_format="mp3",  # Output format
                    audio_codec="libmp3lame",  # Specify audio codec for mp3
                    loudness_range_target=11.0  # Higher target for better music dynamics
                )
                
                # Add the file and run normalization
                normalizer.add_media_file(file_path, normalized_path)
                normalizer.run_normalization()
            except FFmpegNormalizeError as e:
                logger.warning(f"[WARNING] MP3 normalization failed, trying WAV format: {e}")
                
                # If mp3 fails, try with WAV which is more compatible
                # Change extension to wav
                normalized_path = os.path.splitext(normalized_path)[0] + ".wav"
                
                normalizer = FFmpegNormalize(
                    normalization_type="ebu", 
                    target_level=target_level,
                    output_format="wav",  # WAV format is more compatible
                    loudness_range_target=11.0  # Higher target for better music dynamics
                )
                
                # Add the file and run normalization
                normalizer.add_media_file(file_path, normalized_path)
                normalizer.run_normalization()
            
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
    
    def normalize_files_background(self, file_list, callback=None):
        """Normalize multiple files in a background thread.
        
        Args:
            file_list: List of file paths to normalize
            callback: Optional callback function to call when normalization is complete
        """
        if not file_list:
            logger.info("[NORMALIZE] No files to normalize")
            return
            
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
        
        # Mark files as being normalized to prevent duplicate processing
        with self.lock:
            for file_path in files_to_process:
                self.currently_normalizing.add(file_path)
            
        def background_normalize():
            normalized_paths = []
            # Process files in batches
            for i in range(0, len(files_to_process), self.batch_size):
                batch = files_to_process[i:i+self.batch_size]
                logger.info(f"[NORMALIZE] Processing batch {i//self.batch_size + 1}/{(len(files_to_process)-1)//self.batch_size + 1} ({len(batch)} files)")
                
                # Normalize this batch
                batch_paths = self.batch_normalize(batch)
                normalized_paths.extend(batch_paths)
            
            logger.info(f"[NORMALIZE] Completed normalization of {len(normalized_paths)}/{len(files_to_process)} files")
            
            # Call the callback if provided and if any files were normalized
            if callback and normalized_paths:
                try:
                    callback(normalized_paths)
                    logger.info(f"[NORMALIZE] Successfully applied callback for {len(normalized_paths)} normalized files")
                except Exception as e:
                    logger.error(f"[ERROR] Error in normalization callback: {e}")
                    
            # Release files from currently normalizing
            with self.lock:
                for file_path in files_to_process:
                    if file_path in self.currently_normalizing:
                        self.currently_normalizing.remove(file_path)
        
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
            
            # Create normalizer instances
            mp3_normalizer = FFmpegNormalize(
                normalization_type="ebu", 
                target_level=target_level,
                output_format="mp3",
                audio_codec="libmp3lame",
                loudness_range_target=11.0
            )
            
            wav_normalizer = FFmpegNormalize(
                normalization_type="ebu", 
                target_level=target_level,
                output_format="wav",
                loudness_range_target=11.0
            )
            
            # Add files to the mp3 normalizer
            mp3_files = []
            for file_path in file_list:
                normalized_path = self.get_normalized_path(file_path)
                
                # Skip if already normalized
                if os.path.exists(normalized_path):
                    logger.info(f"[NORMALIZE] File already normalized: {normalized_path}")
                    normalized_paths.append(normalized_path)
                    continue
                    
                mp3_normalizer.add_media_file(file_path, normalized_path)
                mp3_files.append((file_path, normalized_path))
            
            # Run mp3 normalization if files were added
            if mp3_files:
                try:
                    logger.info(f"[NORMALIZE] Batch processing {len(mp3_files)} files with MP3 output")
                    mp3_normalizer.run_normalization()
                    # Add successfully normalized paths
                    for _, norm_path in mp3_files:
                        if os.path.exists(norm_path):
                            normalized_paths.append(norm_path)
                except FFmpegNormalizeError as e:
                    logger.warning(f"[WARNING] MP3 batch normalization failed, falling back to WAV: {e}")
                    
                    # Fall back to WAV format for files that failed
                    for orig_path, mp3_path in mp3_files:
                        if not os.path.exists(mp3_path):
                            # Try WAV instead
                            wav_path = os.path.splitext(mp3_path)[0] + ".wav"
                            wav_normalizer.add_media_file(orig_path, wav_path)
                    
                    # Run WAV normalization
                    try:
                        wav_normalizer.run_normalization()
                        # Check which files were normalized and add to results
                        for orig_path, mp3_path in mp3_files:
                            wav_path = os.path.splitext(mp3_path)[0] + ".wav"
                            if os.path.exists(wav_path):
                                normalized_paths.append(wav_path)
                    except FFmpegNormalizeError as e2:
                        logger.error(f"[ERROR] WAV batch normalization also failed: {e2}")
            
            logger.info(f"[NORMALIZE] Batch completed, {len(normalized_paths)}/{len(file_list)} files normalized")
            return normalized_paths
            
        except Exception as e:
            logger.error(f"[ERROR] Error during batch normalization: {e}")
            return normalized_paths 