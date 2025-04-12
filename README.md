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

### 4. Monitor audio with Cava

Install Cava (Terminal Audio Visualizer):
```bash
# On Raspberry Pi/Debian/Ubuntu
sudo apt install cava
```

Run in a separate terminal to visualize the music:
```bash
cava
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
# Allow more time for graceful shutdown
TimeoutStopSec=30

# Audio environment variables for better playback
Environment=SDL_AUDIODRIVER=alsa
Environment=PYGAME_HIDE_SUPPORT_PROMPT=1
Environment=SDL_AUDIO_BUFFER_SIZE=4096

# PulseAudio settings for CAVA visualization to work with service
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=PULSE_SERVER=unix:/run/user/1000/pulse/native

[Install]
WantedBy=multi-user.target
```

Replace:
- `username` with your system username
- `/path/to/your/music/player` with the absolute path to your project
- Adjust the Python path if needed (run `which python` to find your correct path)
- Verify that `1000` in the PulseAudio paths matches your user ID (check with `id -u`)

### 2. Install and enable the service

```bash
# Copy the service file to systemd
sudo cp rpi_music_player.service /etc/systemd/system/

# Make sure your user is in the audio group
sudo usermod -a -G audio username

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

### 4. Using CAVA with the service

When the music player runs as a service, CAVA needs special configuration to visualize the audio:

1. Ensure your service file includes the PulseAudio environment variables (see above)
2. Add your user to the audio group (as shown in the install steps)
3. Start CAVA in a terminal:
   ```bash
   cava
   ```
4. If CAVA still doesn't detect audio, try:
   ```bash
   export XDG_RUNTIME_DIR=/run/user/1000
   export PULSE_SERVER=unix:/run/user/1000/pulse/native
   cava
   ```

### Note
The service file is in the .gitignore list to prevent committing system-specific paths. 