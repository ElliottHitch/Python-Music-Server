from flask import send_from_directory, jsonify, request
import logging
from src.downloader import download_youtube_audio
from src.player import get_audio_files

logger = logging.getLogger(__name__)

def setup_routes(app, audio_folder, player):
    """
    Setup Flask routes for the application
    """
    
    @app.route('/', endpoint='index_route')
    def index():
        return send_from_directory('static', 'index.html')

    @app.route('/download', methods=["POST"], endpoint='download_route')
    def download_song():
        data = request.get_json()
        youtube_url = data.get("url")
        if not youtube_url:
            return jsonify({"message": "No URL provided."}), 400

        headers = {
            'User-Agent': request.headers.get("User-Agent",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"),
            'Referer': request.headers.get("Referer", youtube_url),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive'
        }

        success, message = download_youtube_audio(youtube_url, audio_folder, headers)
        
        if success:
            player.track_list = get_audio_files(audio_folder)
            return jsonify({"message": message})
        else:
            return jsonify({"message": message}), 500 