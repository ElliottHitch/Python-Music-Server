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

To run the player as a background service that starts automatically at boot:

### 1. Create the service file

Create a file named `rpi_music_player.service` with the following content:

```ini
[Unit]
Description=RPI Music Player Service
After=network.target

[Service]
Type=simple
# User that will run the service
User=username
# Full path to your application directory
WorkingDirectory=/path/to/your/music/player
# Path to the Python executable
ExecStart=/usr/bin/python app.py
Restart=always
RestartSec=5
# Watchdog settings - will restart service if no ping received for 60 seconds
WatchdogSec=60
# Enable watchdog notification from the application
NotifyAccess=main

# Environment variables if needed
# Environment=VARIABLE=value

[Install]
WantedBy=multi-user.target
```

Replace:
- `username` with your system username
- `/path/to/your/music/player` with the absolute path to your project
- Adjust the Python path if needed (run `which python` to find your correct path)

### 2. Install and enable the service

```bash
# Copy the service file to systemd
sudo cp rpi_music_player.service /etc/systemd/system/

# Reload systemd configuration
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable rpi_music_player.service

# Start the service
sudo systemctl start rpi_music_player.service
```

### 3. Service management commands

```bash
# Check service status
sudo systemctl status rpi_music_player.service

# View service logs
sudo journalctl -u rpi_music_player.service

# Stop the service
sudo systemctl stop rpi_music_player.service

# Restart the service
sudo systemctl restart rpi_music_player.service
```

### Note
The service file is in the .gitignore list to prevent committing system-specific paths. 