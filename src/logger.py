import logging
import os
import sys
from logging.handlers import RotatingFileHandler

def setup_logger():
    """Configure and return the root logger for the application"""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Create console handler with proper encoding for Windows
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Handle unicode errors for Windows console output
    if sys.platform == 'win32':
        # Set up a custom formatter that handles encoding errors
        class WindowsConsoleFormatter(logging.Formatter):
            def __init__(self, fmt=None, datefmt=None):
                super().__init__(fmt, datefmt)
            
            def format(self, record):
                msg = super().format(record)
                # Replace problematic characters for Windows console
                try:
                    return msg
                except UnicodeEncodeError:
                    # Replace characters that can't be encoded in cp1252
                    return msg.encode('cp1252', errors='replace').decode('cp1252')
        
        formatter = WindowsConsoleFormatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    
    console_handler.setFormatter(formatter)
    
    # Create file handler with rotation
    file_handler = RotatingFileHandler(
        os.path.join("src", "app.log"),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))
    
    # Add handlers to root logger
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    return root_logger 