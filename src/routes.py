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
import schedule

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

        normalizer = getattr(app, 'audio_normalizer', None)
        
        if hasattr(app, 'song_cache') and not hasattr(player, 'song_cache'):
            player.song_cache = app.song_cache
            
        success, message = download_youtube_audio(
            youtube_url, 
            audio_folder, 
            headers,
            normalizer=normalizer,
            player=player
        )
        
        if success:
            return jsonify({"message": message})
        else:
            return jsonify({"message": message}), 500

    @app.route('/system/memory', methods=["GET", "POST"], endpoint='memory_route')
    def manage_memory():
        """Get system memory information or optimize memory usage"""
        try:
            vm = psutil.virtual_memory()
            process = psutil.Process(os.getpid())
            process_memory = process.memory_info().rss / 1024 / 1024  
            
            memory_info = {
                "total": vm.total / 1024 / 1024,  # MB
                "available": vm.available / 1024 / 1024,  # MB
                "used_percent": vm.percent,
                "process_mb": process_memory,
                "cache_size": len(player._cache) if hasattr(player, '_cache') else 0
            }
            
            if request.method == "GET":
                return jsonify(memory_info)
            
            elif request.method == "POST":
                gc.collect(2)  
                
                cache_cleared = False
                if hasattr(player, 'clear_cache'):
                    player.clear_cache()
                    cache_cleared = True
                    
                vm = psutil.virtual_memory()
                process_memory = process.memory_info().rss / 1024 / 1024  
                
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
                    song_cache = app.song_cache
                    song_cache.cache['files'] = {}
                    song_cache.modified = True
                    song_cache.save_cache()
                    return jsonify({"message": "Cache cleared successfully"})
                    
                elif action == 'refresh' and hasattr(app, 'song_cache'):
                    normalizer = getattr(app, 'audio_normalizer', None)
                    playlist, files_to_normalize = ensure_files_in_playlist(
                        player, 
                        app.song_cache,
                        normalizer,
                        app.config['AUDIO_FOLDER']
                    )
                    
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
            normalizer = getattr(app, 'audio_normalizer', None)
            if normalizer is None:
                return jsonify({"error": "Audio normalizer not available"}), 500
                
            if request.method == "GET":
                normalized_count = 0
                pending_count = 0
                normalized_folder = normalizer.normalized_folder
                
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
                    files_to_normalize = []
                    for track in player.track_list:
                        original_path = track['path']
                        if not normalizer.is_normalized(original_path):
                            files_to_normalize.append(original_path)
                    
                    if files_to_normalize:
                        normalizer.normalize_files_background(files_to_normalize)
                        return jsonify({
                            "message": f"Started normalization of {len(files_to_normalize)} files",
                            "normalizing_count": len(files_to_normalize)
                        })
                    else:
                        return jsonify({"message": "All files are already normalized"})
                        
                elif action == 'normalize_file':
                    file_path = request.json.get('file_path')
                    if not file_path:
                        return jsonify({"error": "No file path provided"}), 400
                        
                    if not os.path.exists(file_path):
                        return jsonify({"error": f"File not found: {file_path}"}), 404
                        
                    normalizer.normalize_files_background([file_path])
                    return jsonify({"message": f"Started normalization of file: {os.path.basename(file_path)}"})
                    
                else:
                    return jsonify({"error": "Invalid action"}), 400
                    
        except Exception as e:
            logging.error(f"Error in normalize route: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/reload', methods=['POST'])
    @cross_origin()
    def reload_songs():
        try:
            audio_folder = app.config['AUDIO_FOLDER']
            normalizer = getattr(app, 'audio_normalizer', None)
            
            playlist, files_to_normalize = ensure_files_in_playlist(
                player, 
                app.song_cache,
                normalizer,
                audio_folder
            )
            
            if normalizer and files_to_normalize:
                normalizer.normalize_files_background(files_to_normalize)
            
            player.current_index = min(player.current_index, len(player.track_list) - 1)
            player.load_track(player.current_index)
            
            return jsonify({"message": "Songs reloaded", "count": len(player.track_list)})
        except Exception as e:
            logger.error(f"[ERROR] Error reloading songs: {e}")
            return jsonify({"error": str(e)}), 500
            
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
        
        normalizer = getattr(app, 'audio_normalizer', None)
        
        if hasattr(app, 'song_cache') and not hasattr(player, 'song_cache'):
            player.song_cache = app.song_cache
            
        success, message = download_youtube_audio(
            url, 
            audio_folder, 
            headers,
            normalizer=normalizer,
            player=player
        )
        
        if success:
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

        file.save(upload_path)

        if request.form.get('normalize', 'false').lower() == 'true':
            normalizer = getattr(app, 'audio_normalizer', None)
            if normalizer:
                normalizer.normalize_file(upload_path)
            
        if player:
            normalizer = getattr(app, 'audio_normalizer', None)
            playlist, files_to_normalize = ensure_files_in_playlist(
                player, 
                app.song_cache, 
                normalizer, 
                audio_folder
            )
            
            if normalizer and files_to_normalize and not request.form.get('normalize', 'false').lower() == 'true':
                normalizer.normalize_files_background(files_to_normalize)
                
        return jsonify({"message": "File uploaded successfully", "filename": filename})

    @app.route('/api/status')
    def api_status():
        """Return player status as JSON"""
        if not player:
            return jsonify({"error": "Player not initialized"}), 500
            
        return jsonify(player.current_state())
        
    @app.route('/api/scheduler/status')
    def scheduler_status():
        """Return scheduler status for diagnostics"""
        try:
            jobs = []
            for job in schedule.get_jobs():
                # Extract job information
                jobs.append({
                    "tags": list(job.tags),
                    "next_run": str(job.next_run) if job.next_run else None,
                    "last_run": str(job.last_run) if hasattr(job, 'last_run') else None,
                    "schedule_info": str(job),
                })
            
            return jsonify({
                "jobs": jobs,
                "next_run": str(schedule.next_run()) if schedule.next_run() else None,
                "job_count": len(schedule.get_jobs())
            })
        except Exception as e:
            logger.error(f"[ERROR] Failed to get scheduler status: {e}")
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/scheduler/force/<action>')
    def force_scheduler_action(action):
        """Force a scheduler action (pause or resume)"""
        if not player:
            return jsonify({"error": "Player not initialized"}), 500
            
        try:
            # Find the job with the requested action
            if action == "pause":
                logger.info("[API] Forcing scheduled pause")
                # Find and run all pause jobs
                for job in schedule.get_jobs():
                    if "pause" in str(job):
                        job.run()
                return jsonify({"status": "Pause action triggered", "player_state": player.current_state()})
            
            elif action == "resume" or action == "play":
                logger.info("[API] Forcing scheduled resume")
                # Find and run all resume jobs
                for job in schedule.get_jobs():
                    if "resume" in str(job):
                        job.run()
                return jsonify({"status": "Resume action triggered", "player_state": player.current_state()})
            
            else:
                return jsonify({"error": f"Unknown action: {action}"}), 400
                
        except Exception as e:
            logger.error(f"[ERROR] Failed to force scheduler action: {e}")
            return jsonify({"error": str(e)}), 500 