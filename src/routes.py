from flask import send_from_directory, jsonify, request
import logging
import gc
import psutil
import os
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
            # Use song cache instead of legacy function
            from src.player import get_duration
            if hasattr(app, 'song_cache'):
                # Use the song cache to get fresh files
                player.track_list = app.song_cache.get_cached_audio_files(audio_folder, get_duration)
                app.song_cache.flush()  # Save changes to cache
            else:
                # Fallback to legacy method if cache isn't available
                from src.player import get_audio_files
                player.track_list = get_audio_files(audio_folder)
            return jsonify({"message": message})
        else:
            return jsonify({"message": message}), 500

    @app.route('/system/memory', methods=["GET"], endpoint='memory_route')
    def get_memory_info():
        """Get system memory information"""
        try:
            vm = psutil.virtual_memory()
            process = psutil.Process(os.getpid())
            process_memory = process.memory_info().rss / 1024 / 1024  # MB
            
            memory_info = {
                "total": vm.total / 1024 / 1024,  # MB
                "available": vm.available / 1024 / 1024,  # MB
                "used_percent": vm.percent,
                "process_mb": process_memory,
                "cache_size": len(player._cache) if hasattr(player, '_cache') else 0
            }
            return jsonify(memory_info)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
            
    @app.route('/system/optimize', methods=["POST"], endpoint='optimize_route')
    def optimize_memory():
        """Manually trigger memory optimization"""
        try:
            # Force Python garbage collection
            gc.collect(2)  # Full collection
            
            # Clear player cache if it exists
            cache_cleared = False
            if hasattr(player, 'clear_cache'):
                cache_cleared = player.clear_cache()
                
            # Get memory after optimization
            vm = psutil.virtual_memory()
            process = psutil.Process(os.getpid())
            process_memory = process.memory_info().rss / 1024 / 1024  # MB
            
            return jsonify({
                "success": True,
                "message": "Memory optimization completed",
                "cache_cleared": cache_cleared,
                "memory_percent": vm.percent,
                "process_mb": process_memory
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/system/cache', methods=["GET", "POST"], endpoint='cache_route')
    def manage_cache():
        """Get cache information or clear cache"""
        try:
            if request.method == "GET":
                # Get cache stats if possible
                if hasattr(app, 'song_cache'):
                    song_cache = app.song_cache
                    cache_stats = {
                        "files_count": len(song_cache.cache.get('files', {})),
                        "last_updated": song_cache.cache.get('last_updated', 'unknown')
                    }
                    return jsonify(cache_stats)
                else:
                    return jsonify({"message": "Cache system not accessible"}), 404
                
            elif request.method == "POST":
                action = request.json.get('action', '')
                
                if action == 'clear' and hasattr(app, 'song_cache'):
                    # Clear the entire cache
                    song_cache = app.song_cache
                    song_cache.cache['files'] = {}
                    song_cache.modified = True
                    song_cache.save_cache()
                    return jsonify({"message": "Cache cleared successfully"})
                    
                elif action == 'refresh' and hasattr(app, 'song_cache'):
                    # Force a refresh of the song list
                    from src.player import get_duration
                    song_cache = app.song_cache
                    fresh_files = song_cache.get_cached_audio_files(
                        app.config['AUDIO_FOLDER'], 
                        get_duration
                    )
                    if player:
                        player.track_list = fresh_files
                        
                    return jsonify({
                        "message": "Cache refreshed successfully",
                        "songs_count": len(fresh_files)
                    })
                    
                else:
                    return jsonify({"message": "Invalid action"}), 400
                
        except Exception as e:
            return jsonify({"error": str(e)}), 500 