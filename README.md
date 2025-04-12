# Python Music Server

A web-based music player application made for Raspberry Pi.
The backend maintains the player state and audio output.
The front end allows playback control over network through browser.

### Setup Instructions

### 1. Create and activate a virtual environment

**Windows**:
```
python -m venv venv
venv\Scripts\activate
```

**macOS/Linux**:
```
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```
pip install -r requirements.txt
```

### 3. Run the application
```
python app.py
```

The web interface is available at:
- http://localhost:5000 (local)
- http://[device-ip]:5000 (remote)

## Features

- Web interface for music playback control
- Real-time updates via WebSockets
- Auto music duration calculation
- State persistence between restarts
- Built-in watchdog for reliability

## Linux/Raspberry Pi Service Setup (Optional)

If you want the player to run as a background service:

1. Edit `rpi_music_player.service`:
   - Set your username in `User=`
   - Set your app path in `WorkingDirectory=`
   - Set correct Python path in `ExecStart=`

2. Install the service:
   ```bash
   sudo cp rpi_music_player.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable rpi_music_player.service
   sudo systemctl start rpi_music_player.service
   ```

3. Check service status:
   ```bash
   sudo systemctl status rpi_music_player.service
   ``` 