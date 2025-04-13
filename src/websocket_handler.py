import json
import logging
import time
from src.player import format_duration
import threading
import asyncio

logger = logging.getLogger(__name__)

# Track last activity time locally
_last_websocket_activity = time.time()

# Keep track of connected clients
_connected_clients = set()

# Track whether there's a state update since last check
_state_changed = False
_state_lock = threading.Lock()
_last_state = {}

def get_last_websocket_activity():
    """Get the last time a websocket message was received"""
    return _last_websocket_activity

def broadcast_state_change(state):
    """
    Mark that state has changed and broadcast to all connected clients
    """
    global _state_changed, _last_state
    
    with _state_lock:
        _state_changed = True
        _last_state = state.copy() if state else {}
    
    if _connected_clients:
        asyncio_loop = asyncio.get_event_loop()
        for client in list(_connected_clients):
            try:
                asyncio_loop.create_task(_send_state_update(client, state))
            except Exception as e:
                logger.error(f"[ERROR] Failed to broadcast state: {e}")

async def _send_state_update(websocket, state):
    """Helper to send state updates to a client"""
    try:
        if websocket.open:
            await websocket.send(json.dumps({"state": state}))
    except Exception as e:
        logger.error(f"[ERROR] Failed to send state update: {e}")
        _connected_clients.discard(websocket)

async def websocket_handler(websocket, player, save_state_callback):
    """Handle WebSocket connections and player control commands"""
    global _last_websocket_activity, _state_changed
    
    _connected_clients.add(websocket)
    client_id = id(websocket)
    logger.info(f"[WEBSOCKET] New client connected: {client_id}")
    
    try:
        songs_payload = [
            {"name": song["name"], "duration": format_duration(song["duration"])}
            for song in player.track_list
        ]
        
        init_payload = {
            'state': player.current_state(),
            'songs': songs_payload
        }
        await websocket.send(json.dumps(init_payload))
        
        async for message in websocket:
            try:
                _last_websocket_activity = time.time()
                
                command = message.strip().lower()
                command_changed_state = False
                
                state_changed_flag = False
                with _state_lock:
                    if _state_changed:
                        state_changed_flag = True
                        _state_changed = False
                
                if state_changed_flag:
                    await websocket.send(json.dumps({"state": player.current_state()}))
                
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
                    except (ValueError, IndexError) as e:
                        logger.error(f"[ERROR] Invalid play command format: {e}")
                        await websocket.send(json.dumps({"message": "Invalid play command format"}))
                elif command.startswith("volume:"):
                    try:
                        volume = float(command.split(":", 1)[1])
                        player.set_volume(volume)
                        command_changed_state = True
                    except (ValueError, IndexError) as e:
                        logger.error(f"[ERROR] Invalid volume command format: {e}")
                        await websocket.send(json.dumps({"message": "Invalid volume command format"}))
                elif command.startswith("delete:"):
                    try:
                        index = int(command.split(":", 1)[1])
                        player.delete_track(index)
                        command_changed_state = True
                        
                        await websocket.send(json.dumps({
                            "state": player.current_state(),
                            "songs": [
                                {"name": f["name"], "duration": format_duration(f["duration"])}
                                for f in player.track_list
                            ],
                            "message": "Song deleted."
                        }))
                        continue
                    except Exception as e:
                        logger.error(f"[ERROR] Error processing delete command: {e}")
                        await websocket.send(json.dumps({"message": f"Error deleting song: {str(e)}"}))
                        continue
                else:
                    logger.warning(f"[WARNING] Unknown command received: {command}")
                    await websocket.send(json.dumps({"message": "Unknown command"}))
                    continue
                    
                if command_changed_state:
                    current_state = player.current_state()
                    save_state_callback(current_state)
                    await websocket.send(json.dumps({"state": current_state}))
            except Exception as e:
                logger.error(f"[ERROR] Error in websocket handler: {e}")
    except Exception as e:
        logger.error(f"[ERROR] WebSocket connection error: {e}")
    finally:
        _connected_clients.discard(websocket)
        logger.info(f"[WEBSOCKET] Client disconnected: {client_id}") 