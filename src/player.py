import os
import random
import logging
import pygame
from mutagen.mp3 import MP3

logger = logging.getLogger(__name__)

def format_duration(seconds):
    if seconds is None or seconds < 0:
        return "--:--"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"

def get_duration(file_path):
    try:
        if file_path.lower().endswith('.mp3'):
            audio = MP3(file_path)
            return audio.info.length
        else:
            sound = pygame.mixer.Sound(file_path)
            return sound.get_length()
    except Exception as e:
        logger.exception(f"Error getting duration of {file_path}")
        return 0

def get_audio_files(folder):
    valid_extensions = {'.mp3', '.wav', '.ogg'}
    files_list = []
    logger.info(f"Scanning audio files in: {folder}")
    try:
        count = 0
        for file in os.listdir(folder):
            ext = os.path.splitext(file)[1].lower()
            if ext in valid_extensions:
                file_path = os.path.join(folder, file)
                files_list.append({
                    "path": file_path,
                    "name": file,
                    "duration": None  # Initialize duration as None
                })
                count += 1
        logger.info(f"Found {count} audio files.")
    except FileNotFoundError:
        logger.error(f"Audio folder not found: {folder}")
    except Exception as e:
        logger.exception(f"Error listing directory {folder}")
    return files_list

class PygamePlayer:
    def __init__(self, track_list):
        if not track_list:
            raise ValueError("No audio files found in the specified folder.")
        self.track_list = track_list
        self.current_index = 0
        self.paused = True
        self.shuffle_on = False
        self.load_track(self.current_index)

    def load_track(self, index):
        try:
            pygame.mixer.music.load(self.track_list[index]['path'])
            pygame.mixer.music.set_endevent(pygame.USEREVENT)
        except Exception as e:
            logger.error(f"Error loading track {self.track_list[index]['name']}: {e}")

    def start_track(self):
        pygame.mixer.music.play()
        self.paused = False

    def play(self):
        if not pygame.mixer.music.get_busy():
            self.load_track(self.current_index)
            self.start_track()
        elif self.paused:
            pygame.mixer.music.unpause()
            self.paused = False

    def pause(self):
        if self.paused:
            pygame.mixer.music.unpause()
            self.paused = False
        else:
            pygame.mixer.music.pause()
            self.paused = True

    def next(self):
        if self.shuffle_on and len(self.track_list) > 1:
            new_index = self.current_index
            while new_index == self.current_index:
                new_index = random.randint(0, len(self.track_list) - 1)
            self.current_index = new_index
        else:
            self.current_index = (self.current_index + 1) % len(self.track_list)
        self.load_track(self.current_index)
        self.start_track()

    def back(self):
        self.current_index = (self.current_index - 1) % len(self.track_list)
        self.load_track(self.current_index)
        self.start_track()

    def play_track(self, index):
        self.current_index = index
        self.load_track(self.current_index)
        self.start_track()

    def set_volume(self, volume):
        pygame.mixer.music.set_volume(volume)

    def get_volume(self):
        return pygame.mixer.music.get_volume()

    def is_paused(self):
        return self.paused

    def toggle_shuffle(self):
        self.shuffle_on = not self.shuffle_on

    def delete_track(self, index):
        if index < 0 or index >= len(self.track_list):
            raise IndexError("Invalid track index")
        song = self.track_list[index]
        if not os.path.exists(song['path']):
            raise FileNotFoundError(f"File not found: {song['path']}")
        try:
            # If the current track is being deleted, move to the next track if available.
            if index == self.current_index:
                if len(self.track_list) > 1:
                    self.current_index = (index + 1) % len(self.track_list)
                    self.load_track(self.current_index)
                    self.start_track()
                else:
                    pygame.mixer.music.stop()
                    self.paused = True
            os.remove(song['path'])
            del self.track_list[index]
            if self.current_index >= len(self.track_list):
                self.current_index = 0
        except Exception as e:
            logger.error(f"Error deleting track {song['name']}: {e}")
            raise
    
    def current_state(self):
        return {
            'current_index': self.current_index,
            'volume': self.get_volume(),
            'paused': self.is_paused(),
            'shuffle': self.shuffle_on
        } 