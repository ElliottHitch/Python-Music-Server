import os
import logging
import pygame

logger = logging.getLogger(__name__)

# Define supported audio formats
SUPPORTED_FORMATS = {'.mp3', '.wav', '.ogg'}

def is_supported_format(file_path):
    """Check if a file is in a supported audio format.
    
    Args:
        file_path: Path to the audio file
        
    Returns:
        True if the file has a supported extension, False otherwise
    """
    ext = os.path.splitext(file_path)[1].lower()
    return ext in SUPPORTED_FORMATS

def get_duration(file_path):
    """Get audio file duration in seconds.
    
    Args:
        file_path: Path to the audio file
        
    Returns:
        Duration in seconds or None if duration could not be determined
    """
    try:
        sound = pygame.mixer.Sound(file_path)
        duration = sound.get_length()  # in seconds
        # Release sound object to prevent memory leaks
        del sound
        return duration
    except Exception as e:
        logger.warning(f"[WARNING] Failed to get duration for {file_path}: {e}")
        return None

def format_duration(seconds):
    """Format duration in seconds to MM:SS format.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted duration string in MM:SS format
    """
    if seconds is None or seconds < 0:
        return "--:--"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"

def get_optimal_format(original_format):
    """Determine the optimal output format based on the original format.
    
    Args:
        original_format: Original file extension (with dot)
        
    Returns:
        Tuple of (output_format, audio_codec) for normalization
    """
    # Default to MP3 output for most cases
    if original_format.lower() in ['.mp3', '.ogg']:
        return 'mp3', 'libmp3lame'
    # For WAV files, prefer to keep WAV format
    elif original_format.lower() == '.wav':
        return 'wav', None
    # Fallback to MP3
    else:
        return 'mp3', 'libmp3lame'
        
def get_fallback_format():
    """Get the fallback format to use if primary format fails.
    
    Returns:
        Tuple of (output_format, audio_codec) for fallback
    """
    return 'wav', None 