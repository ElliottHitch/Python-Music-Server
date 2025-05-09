import os
import logging
import subprocess
import re

logger = logging.getLogger(__name__)

def ensure_files_in_playlist(player, song_cache, normalizer, audio_folder):
    """
    Ensure all files (including normalized ones) are correctly in playlist.
    This function does a clean rebuild of the playlist from filesystem.
    
    Returns:
        tuple: (normalized_files, files_to_normalize) - the playlist with normalized paths
               and a list of files that still need normalization
    """
    logger.info(f"Performing playlist rebuild for folder: {audio_folder}")
    
    song_cache.cache['files'] = {}
    song_cache.modified = True
    
    original_files = song_cache.get_cached_audio_files(audio_folder, None)
    logger.info(f"Found {len(original_files)} files in audio folder")
    
    normalized_files = []
    normalized_count = 0
    files_to_normalize = []
    
    for file_info in original_files:
        original_path = file_info['path']
        
        if normalizer and normalizer.is_normalized(original_path):
            normalized_path = normalizer.get_normalized_path(original_path)
            file_info['path'] = normalized_path
            file_info['normalized'] = True
            normalized_count += 1
        else:
            file_info['normalized'] = False
            files_to_normalize.append(original_path)
            
        normalized_files.append(file_info)
    
    if player:
        player.track_list = normalized_files
        logger.info(f"Updated player with {len(normalized_files)} tracks ({normalized_count} normalized)")
    
    song_cache.flush()
    
    logger.info(f"Playlist rebuild complete: {len(normalized_files)} tracks, {normalized_count} normalized")
    return normalized_files, files_to_normalize

def download_youtube_audio(youtube_url, output_folder, headers, normalizer=None, player=None):
    """
    Download audio from YouTube URL using yt-dlp's 'ba' preset alias for best audio,
    normalize it, and refresh the playlist
    """
    os.makedirs(output_folder, exist_ok=True)
    
    try:
        logger.info(f"Downloading audio from: {youtube_url}")
        
        cmd = [
            "yt-dlp",
            "-f", "ba", 
            "--extract-audio", 
            "--audio-format", "mp3", 
            "--audio-quality", "0", 
            "--output", os.path.join(output_folder, "%(title)s.%(ext)s"),
            youtube_url
        ]
        
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True,
            check=False
        )
        
        if result.returncode == 0:
            filepath = None
            for line in result.stdout.split('\n'):
                if "[download]" in line and "Destination: " in line:
                    filepath = line.split("Destination: ")[1].strip()
                elif "[download]" in line and "has already been downloaded" in line:
                    match = re.search(r'\[download\] (.*) has already been downloaded', line)
                    if match:
                        filepath = match.group(1).strip()
                elif "[ExtractAudio] Destination: " in line:
                    filepath = line.split("[ExtractAudio] Destination: ")[1].strip()
            
            if filepath:
                if not filepath.lower().endswith('.mp3'):
                    base_file = os.path.splitext(filepath)[0]
                    mp3_path = f"{base_file}.mp3"
                    if os.path.exists(mp3_path):
                        filepath = mp3_path
                        logger.info(f"Located MP3 file at: {filepath}")
                
                if normalizer:
                    logger.info(f"Normalizing downloaded file: {filepath}")
                    try:
                        normalized_path = normalizer.normalize_file(filepath)
                        if normalized_path:
                            filepath = normalized_path
                            logger.info(f"Normalization complete: {filepath}")
                    except Exception as e:
                        logger.error(f"Normalization failed: {e}")
                
                if player and hasattr(player, 'song_cache'):
                    updated_playlist, _ = ensure_files_in_playlist(
                        player, 
                        player.song_cache, 
                        normalizer, 
                        output_folder
                    )
                    
                return True, f"Download complete: {os.path.basename(filepath)}"
            else:
                return True, "Download successful"
        else:
            error_msg = result.stderr.strip()
            logger.error(f"yt-dlp error: {error_msg}")
            return False, f"Download failed: {error_msg}"
            
    except Exception as e:
        logger.exception(f"Error running yt-dlp: {str(e)}")
        return False, f"Download error: {str(e)}" 