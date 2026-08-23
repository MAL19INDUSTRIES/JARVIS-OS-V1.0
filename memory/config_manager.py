import json
import os
import sys
from pathlib import Path

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def config_exists() -> bool:
    return CONFIG_FILE.exists()

def save_api_keys(gemini_api_key: str) -> None:
    from core.tenant import get_current_user_id

    user_id = get_current_user_id()
    if user_id:
        from api.database import SessionLocal
        from api.secret_service import set_user_secret

        with SessionLocal() as db:
            set_user_secret(db, user_id, "gemini_api_key", gemini_api_key.strip())
        return
    ensure_config_dir()

    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    data["gemini_api_key"] = gemini_api_key.strip()

    CONFIG_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )

def load_api_keys() -> dict:
    from core.tenant import get_current_user_id

    user_id = get_current_user_id()
    if user_id:
        from api.database import SessionLocal
        from api.secret_service import get_user_secret

        with SessionLocal() as db:
            key = get_user_secret(db, user_id, "gemini_api_key")
        return {"gemini_api_key": key} if key else {}
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Failed to load api_keys.json: {e}")
        return {}

def get_gemini_key() -> str | None:
    from core.tenant import get_current_user_id

    if get_current_user_id():
        return load_api_keys().get("gemini_api_key")
    key = os.environ.get("GEMINI_API_KEY")
    if isinstance(key, str) and key.strip():
        return key.strip()
    return load_api_keys().get("gemini_api_key")

def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)
