#!/bin/bash
# Script to setup or update the RPI Music Player service

# Colors for terminal output
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Please run as root (use sudo).${NC}"
  exit 1
fi

SERVICE_NAME="rpi_music_player.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
SOURCE_PATH="$(pwd)/${SERVICE_NAME}"

echo -e "${YELLOW}Setting up ${SERVICE_NAME}...${NC}"

# Check if service file exists
if [ ! -f "$SOURCE_PATH" ]; then
  echo -e "${RED}Error: ${SERVICE_NAME} not found in current directory.${NC}"
  exit 1
fi

# Copy service file to systemd directory
echo "Copying service file to systemd..."
cp "$SOURCE_PATH" "$SERVICE_PATH"

# Add user to audio group if needed
echo "Making sure user 'el' is in the audio group..."
usermod -a -G audio el

# Reload systemd daemon
echo "Reloading systemd daemon..."
systemctl daemon-reload

# Check if service is already running
if systemctl is-active --quiet "$SERVICE_NAME"; then
  echo "Restarting service..."
  systemctl restart "$SERVICE_NAME"
else
  echo "Starting service..."
  systemctl start "$SERVICE_NAME"
fi

# Enable service to start at boot
echo "Enabling service to start at boot..."
systemctl enable "$SERVICE_NAME"

# Show status
echo -e "${GREEN}Service setup complete!${NC}"
echo "Current service status:"
systemctl status "$SERVICE_NAME"

# Provide helpful commands
echo -e "\n${YELLOW}Useful commands:${NC}"
echo "- Check status: sudo systemctl status $SERVICE_NAME"
echo "- View logs: sudo journalctl -u $SERVICE_NAME -f"
echo "- Stop service: sudo systemctl stop $SERVICE_NAME"
echo "- Start service: sudo systemctl start $SERVICE_NAME"
echo "- Disable autostart: sudo systemctl disable $SERVICE_NAME" 