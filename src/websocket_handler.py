import json
import logging
import time
from src.audio_format import format_duration
import asyncio

logger = logging.getLogger(__name__)

# Track last activity time locally
_last_websocket_activity = time.time()

# Keep track of connected clients
_connected_clients = set()

def get_last_websocket_activity():
    """Get the last time a websocket message was received"""
    return _last_websocket_activity

async def broadcast_state_change(state):
    """Broadcast state changes to all connected WebSocket clients."""
    if not _connected_clients or not state:
        return

    message = json.dumps({"type": "state_update", "data": state})
    
    # Remove stale clients and send messages concurrently
    tasks = []
    to_remove = set()
    
    for client in _connected_clients:
        try:
            tasks.append(client.send(message))
        except Exception:
            to_remove.add(client)
    
    # Execute all sends concurrently
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    
    # Remove disconnected clients
    _connected_clients.difference_update(to_remove)

async def websocket_handler(websocket, player, save_state_callback):
    """Handle WebSocket connections and player control commands"""
    global _last_websocket_activity
    
    _connected_clients.add(websocket)
    client_id = id(websocket)
    logger.info(f"[WEBSOCKET] New client connected: {client_id}")
    
    try:
        # Send initial state and song list in a single message
        songs_payload = [
            {"name": song["name"], "duration": format_duration(song["duration"])}
            for song in player.track_list
        ]
        
        await websocket.send(json.dumps({
            'state': player.current_state(),
            'songs': songs_payload
        }))
        
        async for message in websocket:
            _last_websocket_activity = time.time()
            command = message.strip().lower()
            command_changed_state = False
            
            # Process commands
            if command in {"play", "pause", "next", "back", "toggle-shuffle"}:
                command_map = {
                    "play": player.play,
                    "pause": player.pause,
                    "next": player.next,
                    "back": player.back,
                    "toggle-shuffle": player.toggle_shuffle,
                }
                command_map[command]()
                command_changed_state = True
            elif command.startswith("play:"):
                try:
                    index = int(command.split(":", 1)[1])
                    player.play_track(index)
                    command_changed_state = True
                except (ValueError, IndexError):
                    await websocket.send(json.dumps({"message": "Invalid play command format"}))
            elif command.startswith("volume:"):
                try:
                    volume = float(command.split(":", 1)[1])
                    player.set_volume(volume)
                    command_changed_state = True
                except (ValueError, IndexError):
                    await websocket.send(json.dumps({"message": "Invalid volume command format"}))
            elif command.startswith("delete:"):
                try:
                    index = int(command.split(":", 1)[1])
                    player.delete_track(index)
                    command_changed_state = True
                    
                    await websocket.send(json.dumps({
                        "state": player.current_state(),
                        "songs": [{"name": f["name"], "duration": format_duration(f["duration"])} for f in player.track_list],
                        "message": "Song deleted."
                    }))
                    continue
                except Exception as e:
                    await websocket.send(json.dumps({"message": f"Error deleting song: {str(e)}"}))
                    continue
            else:
                await websocket.send(json.dumps({"message": "Unknown command"}))
                continue
                
            if command_changed_state:
                current_state = player.current_state()
                save_state_callback(current_state)
                await websocket.send(json.dumps({"state": current_state}))
                
    except Exception as e:
        logger.error(f"[ERROR] WebSocket connection error: {e}")
    finally:
        _connected_clients.discard(websocket)
        logger.info(f"[WEBSOCKET] Client disconnected: {client_id}") 