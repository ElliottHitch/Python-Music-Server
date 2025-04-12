import os
import logging
from yt_dlp import YoutubeDL

logger = logging.getLogger(__name__)

def download_youtube_audio(youtube_url, output_folder, headers):
    """
    Download audio from YouTube URL and save as MP3 in the output folder
    """
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(output_folder, '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'http_headers': headers,
        'quiet': True,
        'geo_bypass': True,  # Try to bypass geo-restrictions
        'noplaylist': True,  # Only download single video, not playlist
        'extract_flat': False,
        'ignoreerrors': False, # Don't ignore errors
        'no_warnings': False,  # Show warnings
        'writethumbnail': False, # Don't download thumbnails
        'retries': 5,  # Retry a few times
    }

    try:
        logger.info(f"Downloading audio from YouTube URL: {youtube_url}")
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            title = info.get('title', 'Unknown')
            logger.info(f"Found video: {title}")
            ydl.download([youtube_url])
        return True, f"Download successful: {title}"
    except Exception as e:
        logger.exception(f"Error downloading video: {str(e)}")
        error_msg = str(e)
        if "unavailable" in error_msg.lower():
            return False, "Video is unavailable or restricted. Try another video."
        elif "copyright" in error_msg.lower():
            return False, "Video has copyright restrictions. Try another video."
        elif "private" in error_msg.lower():
            return False, "Video is private. Try another video."
        elif "not exist" in error_msg.lower():
            return False, "Video does not exist. Check the URL and try again."
        else:
            return False, f"Error downloading video: {error_msg}" 