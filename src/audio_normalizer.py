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
        self._player = player 
        
        if normalized_folder is None:
            self.normalized_folder = os.path.join(audio_folder, "normalized")
        else:
            self.normalized_folder = normalized_folder
            
        os.makedirs(self.normalized_folder, exist_ok=True)
        
        self.currently_normalizing = set()
        self.lock = threading.Lock()
        
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
        if os.path.normpath(original_path).startswith(os.path.normpath(self.normalized_folder)):
            logger.debug(f"[NORMALIZE] File {original_path} is already in normalized folder")
            return original_path
            
        rel_path = os.path.relpath(original_path, self.audio_folder)
        normalized_path = os.path.join(self.normalized_folder, rel_path)
        
        os.makedirs(os.path.dirname(normalized_path), exist_ok=True)
        
        wav_path = os.path.splitext(normalized_path)[0] + ".wav"
        if os.path.exists(wav_path):
            return wav_path
            
        return normalized_path
    
    def is_normalized(self, file_path):
        """Check if a file has already been normalized.
        
        Args:
            file_path: Path to the original audio file
            
        Returns:
            True if a normalized version exists, False otherwise
        """
        if os.path.normpath(file_path).startswith(os.path.normpath(self.normalized_folder)):
            return True
            
        normalized_path = self.get_normalized_path(file_path)
        
        if os.path.exists(normalized_path):
            return True
            
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
            if file_path in self.currently_normalizing:
                logger.info(f"[NORMALIZE] File {file_path} is already being normalized")
                return None
                
            self.currently_normalizing.add(file_path)
            
        normalized_path = self.get_normalized_path(file_path)
        
        if os.path.exists(normalized_path):
            logger.info(f"[NORMALIZE] File already normalized: {normalized_path}")
            with self.lock:
                self.currently_normalizing.remove(file_path)
            return normalized_path
            
        original_ext = os.path.splitext(file_path)[1]
        output_format, audio_codec = get_optimal_format(original_ext)
            
        try:
            logger.info(f"[NORMALIZE] Normalizing file: {file_path}")
            
            try:
                normalizer_kwargs = {
                    "normalization_type": "ebu", 
                    "target_level": target_level,
                    "output_format": output_format,
                    "loudness_range_target": 11.0  # Higher target for better music dynamics
                }
                
                if audio_codec:
                    normalizer_kwargs["audio_codec"] = audio_codec
                
                normalizer = FFmpegNormalize(**normalizer_kwargs)
                
                normalizer.add_media_file(file_path, normalized_path)
                normalizer.run_normalization()
                normalizer = None  # Release reference for GC
            except FFmpegNormalizeError as e:
                logger.warning(f"[WARNING] {output_format.upper()} normalization failed, trying fallback format: {e}")
                
                fallback_format, fallback_codec = get_fallback_format()
                
                normalized_path = os.path.splitext(normalized_path)[0] + f".{fallback_format}"
                
                normalizer_kwargs = {
                    "normalization_type": "ebu", 
                    "target_level": target_level,
                    "output_format": fallback_format,
                    "loudness_range_target": 11.0
                }
                
                if fallback_codec:
                    normalizer_kwargs["audio_codec"] = fallback_codec
                    
                normalizer = FFmpegNormalize(**normalizer_kwargs)
                
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
            
        updated_count = 0
        
        import pygame  # Import here to avoid circular imports
        
        for i, track in enumerate(self._player.track_list):
            original_path = track.get('path')
            
            if track.get('normalized', False):
                continue
                
            for norm_path in normalized_paths:
                rel_path = os.path.relpath(norm_path, self.normalized_folder)
                orig_path = os.path.join(self.audio_folder, rel_path)
                
                if orig_path == original_path:
                    logger.info(f"[NORMALIZE] Switching to normalized version: {norm_path}")
                    self._player.track_list[i]['path'] = norm_path
                    self._player.track_list[i]['normalized'] = True
                    updated_count += 1
                    break
        
        if updated_count > 0:
            logger.info(f"[NORMALIZE] Updated {updated_count} tracks to use normalized versions")
            current_track = self._player.track_list[self._player.current_index]
            
            if current_track.get('normalized') and pygame.mixer.music.get_busy():
                pos = pygame.mixer.music.get_pos() / 1000.0
                self._player.load_track(self._player.current_index)
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
            
        if callback is None and self._player is not None:
            callback = self.update_player_with_normalized_tracks
            
        files_to_process = []
        skipped_count = 0
        
        for file_path in file_list:
            if os.path.normpath(file_path).startswith(os.path.normpath(self.normalized_folder)):
                logger.debug(f"[NORMALIZE] Skipping file already in normalized folder: {file_path}")
                skipped_count += 1
                continue
                
            if self.is_normalized(file_path):
                logger.debug(f"[NORMALIZE] Skipping file that already has a normalized version: {file_path}")
                skipped_count += 1
                continue
                
            with self.lock:
                if file_path in self.currently_normalizing:
                    logger.debug(f"[NORMALIZE] File already being normalized: {file_path}")
                    skipped_count += 1
                    continue
                    
            files_to_process.append(file_path)
        
        if skipped_count > 0:
            logger.info(f"[NORMALIZE] Skipped {skipped_count} files that don't need normalization")
            
        if not files_to_process:
            logger.info("[NORMALIZE] No files to normalize after filtering")
            return
        
        files_copy = list(files_to_process)
        
        with self.lock:
            for file_path in files_copy:
                self.currently_normalizing.add(file_path)
            
        def background_normalize():
            normalized_paths = []
            for i in range(0, len(files_copy), self.batch_size):
                batch = files_copy[i:i+self.batch_size]
                logger.info(f"[NORMALIZE] Processing batch {i//self.batch_size + 1}/{(len(files_copy)-1)//self.batch_size + 1} ({len(batch)} files)")
                
                batch_paths = self.batch_normalize(batch)
                normalized_paths.extend(batch_paths)
            
            logger.info(f"[NORMALIZE] Completed normalization of {len(normalized_paths)}/{len(files_copy)} files")
            
            if callback and normalized_paths:
                try:
                    callback(normalized_paths)
                    logger.info(f"[NORMALIZE] Successfully applied callback for {len(normalized_paths)} normalized files")
                except Exception as e:
                    logger.error(f"[ERROR] Error in normalization callback: {e}")
                    
            with self.lock:
                for file_path in files_copy:
                    if file_path in self.currently_normalizing:
                        self.currently_normalizing.remove(file_path)
            
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
            
            primary_format, primary_codec = get_optimal_format('.mp3')  # Default to mp3 for batch
            fallback_format, fallback_codec = get_fallback_format()
            
            primary_kwargs = {
                "normalization_type": "ebu", 
                "target_level": target_level,
                "output_format": primary_format,
                "loudness_range_target": 11.0
            }
            
            if primary_codec:
                primary_kwargs["audio_codec"] = primary_codec
                
            primary_normalizer = FFmpegNormalize(**primary_kwargs)
            
            fallback_kwargs = {
                "normalization_type": "ebu", 
                "target_level": target_level,
                "output_format": fallback_format,
                "loudness_range_target": 11.0
            }
            
            if fallback_codec:
                fallback_kwargs["audio_codec"] = fallback_codec
                
            fallback_normalizer = FFmpegNormalize(**fallback_kwargs)
            
            primary_files = []
            for file_path in file_list:
                normalized_path = self.get_normalized_path(file_path)
                
                if os.path.exists(normalized_path):
                    logger.info(f"[NORMALIZE] File already normalized: {normalized_path}")
                    normalized_paths.append(normalized_path)
                    continue
                    
                primary_normalizer.add_media_file(file_path, normalized_path)
                primary_files.append((file_path, normalized_path))
            
            if primary_files:
                try:
                    logger.info(f"[NORMALIZE] Batch processing {len(primary_files)} files with MP3 output")
                    primary_normalizer.run_normalization()
                    for _, norm_path in primary_files:
                        if os.path.exists(norm_path):
                            normalized_paths.append(norm_path)
                except FFmpegNormalizeError as e:
                    logger.warning(f"[WARNING] MP3 batch normalization failed, falling back to WAV: {e}")
                    
                 
                    for orig_path, mp3_path in primary_files:
                        if not os.path.exists(mp3_path):
                         
                            wav_path = os.path.splitext(mp3_path)[0] + ".wav"
                            fallback_normalizer.add_media_file(orig_path, wav_path)
                    
               
                    try:
                        fallback_normalizer.run_normalization()
                       
                        for orig_path, mp3_path in primary_files:
                            wav_path = os.path.splitext(mp3_path)[0] + ".wav"
                            if os.path.exists(wav_path):
                                normalized_paths.append(wav_path)
                    except FFmpegNormalizeError as e2:
                        logger.error(f"[ERROR] WAV batch normalization also failed: {e2}")
            
            primary_normalizer = None
            fallback_normalizer = None
            primary_files = None
            
            logger.info(f"[NORMALIZE] Batch completed, {len(normalized_paths)}/{len(file_list)} files normalized")
            return normalized_paths
            
        except Exception as e:
            logger.error(f"[ERROR] Error during batch normalization: {e}")
            return normalized_paths 