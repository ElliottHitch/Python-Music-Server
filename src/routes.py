from flask import send_from_directory, jsonify, request, render_template
import logging
import gc
import psutil
import os
import time
import json
import threading
import subprocess
from src.downloader import download_youtube_audio, ensure_files_in_playlist
from flask_cors import cross_origin
from src.audio_format import get_duration, format_duration

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

        # Get the normalizer if available
        normalizer = getattr(app, 'audio_normalizer', None)
        
        # Make sure the player has access to the song cache
        if hasattr(app, 'song_cache') and not hasattr(player, 'song_cache'):
            player.song_cache = app.song_cache
            
        # Call download with normalizer and player
        success, message = download_youtube_audio(
            youtube_url, 
            audio_folder, 
            headers,
            normalizer=normalizer,
            player=player
        )
        
        if success:
            # Since normalization and playlist refresh are handled in the download function,
            # we just need to return the success message
            return jsonify({"message": message})
        else:
            return jsonify({"message": message}), 500

    @app.route('/system/memory', methods=["GET", "POST"], endpoint='memory_route')
    def manage_memory():
        """Get system memory information or optimize memory usage"""
        try:
            # Get current memory info
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
            
            # If it's a GET request, just return the memory info
            if request.method == "GET":
                return jsonify(memory_info)
            
            # If it's a POST request, optimize memory
            elif request.method == "POST":
                # Force Python garbage collection
                gc.collect(2)  # Full collection
                
                # Clear player cache if it exists
                cache_cleared = False
                if hasattr(player, 'clear_cache'):
                    player.clear_cache()
                    cache_cleared = True
                    
                # Get updated memory info after optimization
                vm = psutil.virtual_memory()
                process_memory = process.memory_info().rss / 1024 / 1024  # MB
                
                # Update memory info with post-optimization values
                memory_info.update({
                    "available": vm.available / 1024 / 1024,
                    "used_percent": vm.percent,
                    "process_mb": process_memory,
                    "cache_cleared": cache_cleared,
                    "success": True,
                    "message": "Memory optimization completed"
                })
                
                return jsonify(memory_info)
        
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
                    # Rebuild the playlist with normalized files
                    normalizer = getattr(app, 'audio_normalizer', None)
                    playlist, files_to_normalize = ensure_files_in_playlist(
                        player, 
                        app.song_cache,
                        normalizer,
                        app.config['AUDIO_FOLDER']
                    )
                    
                    # Start normalizing files in the background if needed
                    if normalizer and files_to_normalize:
                        normalizer.normalize_files_background(files_to_normalize)
                        
                    return jsonify({
                        "message": "Cache refreshed successfully",
                        "songs_count": len(player.track_list)
                    })
                    
                else:
                    return jsonify({"message": "Invalid action"}), 400
                
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/system/normalize', methods=["GET", "POST"], endpoint='normalize_route')
    def manage_normalization():
        """Get normalization status or trigger normalization"""
        try:
            # Get normalizer from app
            normalizer = getattr(app, 'audio_normalizer', None)
            if normalizer is None:
                return jsonify({"error": "Audio normalizer not available"}), 500
                
            if request.method == "GET":
                # Count how many files are normalized and how many need normalization
                normalized_count = 0
                pending_count = 0
                normalized_folder = normalizer.normalized_folder
                
                # Check if the normalized folder exists
                if os.path.exists(normalized_folder):
                    for track in player.track_list:
                        original_path = track['path']
                        normalized_path = normalizer.get_normalized_path(original_path)
                        if os.path.exists(normalized_path):
                            normalized_count += 1
                        else:
                            pending_count += 1
                
                return jsonify({
                    "normalized_count": normalized_count,
                    "pending_count": pending_count,
                    "total_count": len(player.track_list),
                    "normalized_folder": normalized_folder
                })
                
            elif request.method == "POST":
                action = request.json.get('action', '')
                
                if action == 'normalize_all':
                    # Normalize all files that aren't already normalized
                    files_to_normalize = []
                    for track in player.track_list:
                        original_path = track['path']
                        if not normalizer.is_normalized(original_path):
                            files_to_normalize.append(original_path)
                    
                    if files_to_normalize:
                        # Start normalization in background with built-in callback
                        normalizer.normalize_files_background(files_to_normalize)
                        return jsonify({
                            "message": f"Started normalization of {len(files_to_normalize)} files",
                            "normalizing_count": len(files_to_normalize)
                        })
                    else:
                        return jsonify({"message": "All files are already normalized"})
                        
                elif action == 'normalize_file':
                    # Normalize a specific file
                    file_path = request.json.get('file_path')
                    if not file_path:
                        return jsonify({"error": "No file path provided"}), 400
                        
                    # Check if the file exists
                    if not os.path.exists(file_path):
                        return jsonify({"error": f"File not found: {file_path}"}), 404
                        
                    # Start normalization in background
                    normalizer.normalize_files_background([file_path])
                    return jsonify({"message": f"Started normalization of file: {os.path.basename(file_path)}"})
                    
                else:
                    return jsonify({"error": "Invalid action"}), 400
                    
        except Exception as e:
            logging.error(f"Error in normalize route: {e}")
            return jsonify({"error": str(e)}), 500

    # Route for reloading songs
    @app.route('/api/reload', methods=['POST'])
    @cross_origin()
    def reload_songs():
        try:
            audio_folder = app.config['AUDIO_FOLDER']
            normalizer = getattr(app, 'audio_normalizer', None)
            
            # Rebuild the playlist with normalized files
            playlist, files_to_normalize = ensure_files_in_playlist(
                player, 
                app.song_cache,
                normalizer,
                audio_folder
            )
            
            # Start normalizing files in the background if needed
            if normalizer and files_to_normalize:
                normalizer.normalize_files_background(files_to_normalize)
            
            # Reload current track
            player.current_index = min(player.current_index, len(player.track_list) - 1)
            player.load_track(player.current_index)
            
            return jsonify({"message": "Songs reloaded", "count": len(player.track_list)})
        except Exception as e:
            logger.error(f"[ERROR] Error reloading songs: {e}")
            return jsonify({"error": str(e)}), 500
            
    # Route for downloading audio from YouTube
    @app.route('/api/download-youtube', methods=['POST'])
    @cross_origin()
    def download_youtube():
        data = request.json
        if not data or 'url' not in data:
            return jsonify({"error": "No URL provided"}), 400
            
        url = data['url']
        audio_folder = app.config['AUDIO_FOLDER']
        headers = {
            'User-Agent': request.headers.get("User-Agent",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"),
            'Referer': request.headers.get("Referer", url),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive'
        }
        
        # Get the normalizer if available
        normalizer = getattr(app, 'audio_normalizer', None)
        
        # Make sure the player has access to the song cache
        if hasattr(app, 'song_cache') and not hasattr(player, 'song_cache'):
            player.song_cache = app.song_cache
            
        # Call download with normalizer and player
        success, message = download_youtube_audio(
            url, 
            audio_folder, 
            headers,
            normalizer=normalizer,
            player=player
        )
        
        if success:
            # Since normalization and playlist refresh are handled in the download function,
            # we just need to return the success message
            return jsonify({"message": message})
        else:
            return jsonify({"message": message}), 500

    @app.route('/upload', methods=['POST'])
    @cross_origin()
    def upload_file():
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400

        filename = file.filename
        audio_folder = app.config['AUDIO_FOLDER']
        upload_path = os.path.join(audio_folder, filename)

        # Save the uploaded file
        file.save(upload_path)

        # Normalize immediately if requested
        if request.form.get('normalize', 'false').lower() == 'true':
            normalizer = getattr(app, 'audio_normalizer', None)
            if normalizer:
                normalizer.normalize_file(upload_path)
            
        # Update the player's track list
        if player:
            normalizer = getattr(app, 'audio_normalizer', None)
            playlist, files_to_normalize = ensure_files_in_playlist(
                player, 
                app.song_cache, 
                normalizer, 
                audio_folder
            )
            
            # Start normalizing files in the background if not already normalized
            if normalizer and files_to_normalize and not request.form.get('normalize', 'false').lower() == 'true':
                normalizer.normalize_files_background(files_to_normalize)
                
        return jsonify({"message": "File uploaded successfully", "filename": filename}) 