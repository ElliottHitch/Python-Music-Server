import json
import logging
import time
from src.audio_format import format_duration
import asyncio

logger = logging.getLogger(__name__)

_last_websocket_activity = time.time()

_connected_clients = set()

def get_last_websocket_activity():
    """Get the last time a websocket message was received"""
    return _last_websocket_activity

async def broadcast_state_change(state):
    """Broadcast state changes to all connected WebSocket clients."""
    if not _connected_clients or not state:
        return

    message = json.dumps({"type": "state_update", "data": state})
    
    tasks = []
    to_remove = set()
    
    for client in _connected_clients:
        try:
            tasks.append(client.send(message))
        except Exception:
            to_remove.add(client)
    
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    
    _connected_clients.difference_update(to_remove)

def format_songs_payload(track_list):
    """Format track list for sending to clients"""
    return [
        {"name": song["name"], "duration": format_duration(song["duration"])}
        for song in track_list
    ]

async def send_response(websocket, data):
    """Send standardized response to client"""
    await websocket.send(json.dumps(data))

async def handle_command(command, websocket, player, save_state_callback):
    """Handle player control commands"""
    command_changed_state = False
    response_data = {}
    
    if command == "ping":
        # Simple ping-pong for connection testing
        await websocket.send("pong")
        return False
    elif command == "get_state":
        # Special command to refresh state without changing anything
        response_data.update({
            "state": player.current_state(),
            "songs": format_songs_payload(player.track_list)
        })
        await send_response(websocket, response_data)
        return False
    elif command in {"play", "pause", "next", "back", "toggle-shuffle"}:
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
            response_data["message"] = "Invalid play command format"
    elif command.startswith("volume:"):
        try:
            volume = float(command.split(":", 1)[1])
            player.set_volume(volume)
            command_changed_state = True
        except (ValueError, IndexError):
            response_data["message"] = "Invalid volume command format"
    elif command.startswith("delete:"):
        try:
            index = int(command.split(":", 1)[1])
            player.delete_track(index)
            command_changed_state = True
            
            response_data.update({
                "state": player.current_state(),
                "songs": format_songs_payload(player.track_list),
                "message": "Song deleted."
            })
            await send_response(websocket, response_data)
            return command_changed_state
        except Exception as e:
            response_data["message"] = f"Error deleting song: {str(e)}"
    else:
        response_data["message"] = "Unknown command"
    
    if response_data:
        await send_response(websocket, response_data)
    
    return command_changed_state

async def websocket_handler(websocket, player, save_state_callback):
    """Handle WebSocket connections and player control commands"""
    global _last_websocket_activity
    
    _connected_clients.add(websocket)
    client_id = id(websocket)
    logger.info(f"[WEBSOCKET] New client connected: {client_id}")
    
    try:
        # Send initial state to client
        await send_response(websocket, {
            'state': player.current_state(),
            'songs': format_songs_payload(player.track_list)
        })
        
        async for message in websocket:
            _last_websocket_activity = time.time()
            command = message.strip().lower()
            
            command_changed_state = await handle_command(
                command, websocket, player, save_state_callback
            )
                
            if command_changed_state:
                current_state = player.current_state()
                save_state_callback(current_state)
                await send_response(websocket, {"state": current_state})
                
    except Exception as e:
        logger.error(f"[ERROR] WebSocket connection error: {e}")
    finally:
        _connected_clients.discard(websocket)
        logger.info(f"[WEBSOCKET] Client disconnected: {client_id}") 