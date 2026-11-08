"""User-editable settings, persisted as JSON next to the database.

KEY_TO_FINGER used to live as a hardcoded dict in config.py - editing it
meant opening source code and restarting the app. Moving it here means the
dashboard's key-settings form (and, for a packaged .exe, anyone editing the
JSON file directly) can change it without touching Python, and the running
collector can pick up the change live via reload_key_to_finger().
"""
import json
import os
import threading

from config import _DATA_DIR

SETTINGS_PATH = os.path.join(_DATA_DIR, "settings.json")

DEFAULT_KEY_TO_FINGER = {
    "a": "left_middle",
    "s": "left_index",
    ";": "right_index",
    "'": "right_middle",
}

_lock = threading.Lock()
_key_to_finger = None


def _load_from_disk():
    if os.path.isfile(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            mapping = data.get("key_to_finger")
            if isinstance(mapping, dict) and mapping:
                return mapping
        except (OSError, json.JSONDecodeError):
            pass
    return dict(DEFAULT_KEY_TO_FINGER)


def get_key_to_finger():
    global _key_to_finger
    with _lock:
        if _key_to_finger is None:
            _key_to_finger = _load_from_disk()
        return dict(_key_to_finger)


def set_key_to_finger(mapping):
    """Validates and persists a new key-to-finger mapping. Raises ValueError
    on anything malformed rather than silently accepting bad input."""
    import keyboard

    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("Mapping must be a non-empty object of key -> finger name")

    cleaned = {}
    for key, finger in mapping.items():
        key = str(key).strip()
        finger = str(finger).strip()
        if not key or not finger:
            raise ValueError("Keys and finger names can't be empty")
        if not keyboard.key_to_scan_codes(key):
            raise ValueError(f"'{key}' isn't a recognized keyboard key")
        cleaned[key] = finger

    global _key_to_finger
    with _lock:
        _key_to_finger = cleaned
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump({"key_to_finger": cleaned}, f, indent=2)

    return cleaned
