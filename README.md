# RPI Music Player

A web-based music player application for Raspberry Pi and standard computers.

## Quick Start

### Setup

```bash
# Create and activate virtual environment
python -m venv venv

# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Run

```bash
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