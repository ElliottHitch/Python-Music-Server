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
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
        return True, "Download successful."
    except Exception as e:
        logger.exception("Error downloading video")
        return False, f"Error downloading video: {str(e)}" 