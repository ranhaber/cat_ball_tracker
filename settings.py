"""
Settings persistence for Cat Dome
Saves and loads user settings to/from JSON file
"""

import json
import os

import config


SETTINGS_FILE = "settings.json"


def get_default_settings():
    """Get default settings from config"""
    return {
        "resolution": list(config.DEFAULT_RESOLUTION),
        "framerate": config.DEFAULT_FRAMERATE,
        "frame_skip": config.DEFAULT_FRAME_SKIP,
        "detection_mode": config.DEFAULT_DETECTION_MODE,
        "detection_threshold": config.DETECTION_THRESHOLD,
        "motion_first_enabled": getattr(config, 'MOTION_FIRST_ENABLED', True),
        "show_motion_regions": getattr(config, 'SHOW_MOTION_REGIONS', False)
    }


def load_settings():
    """Load settings from file, return defaults if not found"""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                saved = json.load(f)
                # Merge with defaults (in case new settings were added)
                defaults = get_default_settings()
                defaults.update(saved)
                return defaults
    except Exception as e:
        print(f"Error loading settings: {e}")
    
    return get_default_settings()


def save_settings(settings):
    """Save settings to file"""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving settings: {e}")
        return False


def update_setting(key, value):
    """Update a single setting and save"""
    settings = load_settings()
    settings[key] = value
    return save_settings(settings)
