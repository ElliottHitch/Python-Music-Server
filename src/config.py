import os
import json
import logging
import tkinter as tk
from tkinter import filedialog

logger = logging.getLogger(__name__)

CONFIG_FILE = os.path.join("static", "config.json")
STATE_FILE = os.path.join("src", "state.json")

def is_headless():
    return not os.environ.get('DISPLAY')

def initialize_config():
    if not os.path.exists(CONFIG_FILE):
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        
        folder_path = ""
        
        if not is_headless():
            try:
                root = tk.Tk()
                root.withdraw()  
                root.attributes("-topmost", True)  
                
                print("Please select your music folder...")
                folder_path = filedialog.askdirectory(title="Select Music Folder")
            except tk.TclError:
                print("Cannot open display window. Running in headless mode.")
                folder_path = ""
        
        if not folder_path:
            folder_path = os.path.join(os.path.expanduser("~"), "Music")
            print(f"Using default music folder: {folder_path}")
        else:
            print(f"Selected folder: {folder_path}")
            folder_path = os.path.normpath(folder_path).replace('\\', '\\\\')
        
        config = {"audio_folder": folder_path}
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
        
        return config
    return None


def load_config():
    init_config = initialize_config()
    if init_config:
        return init_config
        
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.exception(f"[ERROR] Error loading config from {CONFIG_FILE}")
        default_path = os.path.join(os.path.expanduser("~"), "Music")
        return {"audio_folder": default_path}

def save_state(state_data):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state_data, f)
    except Exception as e:
        logger.exception("[ERROR] Error saving state")

def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.exception("[ERROR] Error loading state")
    return None 