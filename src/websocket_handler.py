import json
import logging
import time
from src.player import format_duration
import threading

logger = logging.getLogger(__name__)

# Track last activity time locally
_last_websocket_activity = time.time()

# Keep track of connected clients
_connected_clients = set()

# Track whether there's a state update since last check
_state_changed = False
_state_lock = threading.Lock()

def get_last_websocket_activity():
    """Get the last time a websocket message was received"""
    return _last_websocket_activity

def broadcast_state_change(state):
    """
    Mark that state has changed since the last client interaction.
    The next time any client sends a message, they'll get the latest state.
    """
    global _state_changed
    with _state_lock:
        _state_changed = True
    logger.debug("Marked state as changed for next client interaction")

async def websocket_handler(websocket, player, save_state_callback):
    """
    Handle WebSocket connections and player control commands
    """
    global _last_websocket_activity, _state_changed
    
    # Add client to connected clients set
    _connected_clients.add(websocket)
    
    try:
        # Send initial state
        init_payload = {
            'state': player.current_state(),
            'songs': [
                {"name": song["name"], "duration": format_duration(song["duration"])}
                for song in player.track_list
            ]
        }
        await websocket.send(json.dumps(init_payload))
        
        # Start message handling loop
        async for message in websocket:
            try:
                # Update activity time when any WebSocket message is received
                _last_websocket_activity = time.time()
                
                # Check if state has changed since last client interaction
                state_changed_flag = False
                with _state_lock:
                    if _state_changed:
                        state_changed_flag = True
                        _state_changed = False
                
                # If state changed due to auto-advance, send update
                if state_changed_flag:
                    await websocket.send(json.dumps({"state": player.current_state()}))
                
                # Process incoming command
                command = message.strip().lower()
                command_changed_state = False
                
                if command in {"play", "pause", "next", "back", "toggle-shuffle"}:
                    {
                        "play": player.play,
                        "pause": player.pause,
                        "next": player.next,
                        "back": player.back,
                        "toggle-shuffle": player.toggle_shuffle,
                    }[command]()
                    command_changed_state = True
                elif command.startswith("play:"):
                    index = int(command.split(":", 1)[1])
                    player.play_track(index)
                    command_changed_state = True
                elif command.startswith("volume:"):
                    volume = float(command.split(":", 1)[1])
                    player.set_volume(volume)
                    command_changed_state = True
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
                    
                # Only save state if command changed it
                if command_changed_state:
                    current_state = player.current_state()
                    save_state_callback(current_state)
                    await websocket.send(json.dumps({"state": current_state}))
            except Exception as e:
                logger.error(f"[ERROR] Error in websocket handler: {e}")
    finally:
        # Remove client from connected clients set when connection closes
        _connected_clients.discard(websocket) 