import os
import json
import logging
import tkinter as tk
from tkinter import filedialog

# Setup logger
logger = logging.getLogger(__name__)

# Configuration paths
CONFIG_FILE = os.path.join("static", "config.json")
STATE_FILE = os.path.join("src", "state.json")

# Check if running in a headless environment
def is_headless():
    return not os.environ.get('DISPLAY')

# Initialize config file with folder selection
def initialize_config():
    if not os.path.exists(CONFIG_FILE):
        # Create static directory if it doesn't exist
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        
        folder_path = ""
        
        # If not headless, show GUI dialog
        if not is_headless():
            try:
                # Show folder selection dialog
                root = tk.Tk()
                root.withdraw()  # Hide the main window
                root.attributes("-topmost", True)  # Bring dialog to front
                
                print("Please select your music folder...")
                folder_path = filedialog.askdirectory(title="Select Music Folder")
            except tk.TclError:
                print("Cannot open display window. Running in headless mode.")
                folder_path = ""
        
        # If headless or user cancels, use a default path in Music folder
        if not folder_path:
            folder_path = os.path.join(os.path.expanduser("~"), "Music")
            print(f"Using default music folder: {folder_path}")
        else:
            print(f"Selected folder: {folder_path}")
            # Convert to Windows path format with double backslashes for JSON
            folder_path = os.path.normpath(folder_path).replace('\\', '\\\\')
        
        # Create config file
        config = {"audio_folder": folder_path}
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
        
        return config
    return None

# Load configuration
def load_config():
    # Initialize config if it doesn't exist
    init_config = initialize_config()
    if init_config:
        return init_config
        
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.exception(f"❌ Error loading config from {CONFIG_FILE}")
        # Fallback to default path in user's Music folder
        default_path = os.path.join(os.path.expanduser("~"), "Music")
        return {"audio_folder": default_path}

# State management
def save_state(state_data):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state_data, f)
    except Exception as e:
        logger.exception("❌Error saving state")

def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.exception("❌ Error loading state")
    return None 