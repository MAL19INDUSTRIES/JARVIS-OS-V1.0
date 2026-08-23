# config/__init__.py
import json, os, platform
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "api_keys.json"

def get_config() -> dict:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def get_os() -> str:
    """Returns: 'windows' | 'mac' | 'linux'"""
    configured = get_config().get("os_system")
    if configured:
        return str(configured).lower()
    return {"Darwin": "mac", "Windows": "windows"}.get(platform.system(), "linux")

def is_windows() -> bool: return get_os() == "windows"
def is_mac()     -> bool: return get_os() == "mac"
def is_linux()   -> bool: return get_os() == "linux"
