import json
import logging
from src.player import format_duration

logger = logging.getLogger(__name__)

async def websocket_handler(websocket, player, save_state_callback):
    """
    Handle WebSocket connections and player control commands
    """
    init_payload = {
        'state': player.current_state(),
        'songs': [
            {"name": song["name"], "duration": format_duration(song["duration"])}
            for song in player.track_list
        ]
    }
    await websocket.send(json.dumps(init_payload))
    
    async for message in websocket:
        try:
            command = message.strip().lower()
            state_changed = False
            
            if command in {"play", "pause", "next", "back", "toggle-shuffle"}:
                {
                    "play": player.play,
                    "pause": player.pause,
                    "next": player.next,
                    "back": player.back,
                    "toggle-shuffle": player.toggle_shuffle,
                }[command]()
                state_changed = True
            elif command.startswith("play:"):
                index = int(command.split(":", 1)[1])
                player.play_track(index)
                state_changed = True
            elif command.startswith("volume:"):
                volume = float(command.split(":", 1)[1])
                player.set_volume(volume)
                state_changed = True
            elif command.startswith("delete:"):
                try:
                    index = int(command.split(":", 1)[1])
                    player.delete_track(index)
                    state_changed = True
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
                    logger.error(f"❌ Error processing delete command: {e}")
                    await websocket.send(json.dumps({"message": f"Error deleting song: {str(e)}"}))
                    continue
            else:
                logger.warning(f"❌ Unknown command received: {command}")
                await websocket.send(json.dumps({"message": "Unknown command"}))
                continue
                
            # Only save state if it actually changed
            if state_changed:
                save_state_callback(player.current_state())
                
            await websocket.send(json.dumps({"state": player.current_state()}))
        except Exception as e:
            logger.error(f"❌ Error in websocket handler: {e}") 