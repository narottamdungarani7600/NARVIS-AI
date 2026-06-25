import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "Config" / "settings.json"


def load_settings():
    """Load settings from settings.json"""
    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        return json.load(file)