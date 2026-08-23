import json
import re
import sys
import time
from pathlib import Path


MAX_CACHE_ENTRIES = 200
MAX_ANSWER_CHARS = 1200


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


CACHE_PATH = get_base_dir() / "memory" / "answer_cache.json"


def normalize_question(question: str) -> str:
    text = str(question or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" \t\r\n?.!,;:")
    return text


def looks_time_sensitive(question: str) -> bool:
    q = normalize_question(question)
    current_markers = (
        "today", "now", "current", "currently", "latest", "recent", "this week",
        "this month", "this year", "news", "price", "prices", "stock", "crypto",
        "bitcoin", "weather", "forecast", "schedule", "availability", "available",
        "release date", "sale", "deal", "law", "legal", "regulation", "version",
        "update", "score", "standings", "near me",
    )
    return any(marker in q for marker in current_markers)


def is_cacheable_question(question: str) -> bool:
    q = normalize_question(question)
    if not q or looks_time_sensitive(q):
        return False
    if len(q) < 8 or len(q) > 240:
        return False
    command_markers = (
        "open ", "launch ", "start ", "send ", "text ", "message ", "remind ",
        "set a reminder", "delete ", "move ", "copy ", "save ", "write ",
        "create a file", "run ", "install ", "update ", "close ", "turn ",
        "volume", "brightness", "wifi", "screenshot",
    )
    if any(q.startswith(marker) or marker in q for marker in command_markers):
        return False
    question_markers = (
        "what", "who", "why", "when", "where", "how", "explain", "define",
        "tell me", "can you explain",
    )
    return q.startswith(question_markers) or "?" in str(question or "")


def _load_cache() -> dict:
    try:
        if CACHE_PATH.exists():
            data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"[AnswerCache] Load failed: {e}")
    return {}


def _save_cache(data: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _trim_cache(data: dict) -> dict:
    if len(data) <= MAX_CACHE_ENTRIES:
        return data
    items = sorted(
        data.items(),
        key=lambda item: (int(item[1].get("hits", 0)), float(item[1].get("updated_at", 0))),
    )
    keep = dict(items[-MAX_CACHE_ENTRIES:])
    return keep


def get_cached_answer(question: str) -> str | None:
    key = normalize_question(question)
    if not key:
        return None

    from core.tenant import get_current_user_id

    user_id = get_current_user_id()
    if user_id:
        from api.repositories import get_cached

        return get_cached(user_id, key)

    data = _load_cache()
    entry = data.get(key)
    if not isinstance(entry, dict):
        return None

    answer = str(entry.get("answer", "")).strip()
    if not answer:
        return None

    entry["hits"] = int(entry.get("hits", 0)) + 1
    entry["updated_at"] = time.time()
    data[key] = entry
    try:
        _save_cache(_trim_cache(data))
    except Exception as e:
        print(f"[AnswerCache] Hit update failed: {e}")
    return answer


def save_cached_answer(question: str, answer: str) -> None:
    if not is_cacheable_question(question):
        return

    clean_answer = str(answer or "").strip()
    if not clean_answer or len(clean_answer) > MAX_ANSWER_CHARS:
        return

    key = normalize_question(question)
    from core.tenant import get_current_user_id

    user_id = get_current_user_id()
    if user_id:
        from api.repositories import put_cached

        put_cached(user_id, key, str(question or "").strip(), clean_answer)
        return
    data = _load_cache()
    existing = data.get(key, {}) if isinstance(data.get(key), dict) else {}
    data[key] = {
        "question": str(question or "").strip(),
        "answer": clean_answer,
        "created_at": existing.get("created_at", time.time()),
        "updated_at": time.time(),
        "hits": int(existing.get("hits", 0)),
    }

    try:
        _save_cache(_trim_cache(data))
    except Exception as e:
        print(f"[AnswerCache] Save failed: {e}")
