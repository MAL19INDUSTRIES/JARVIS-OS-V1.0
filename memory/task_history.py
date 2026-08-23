import json
import re
import time
from pathlib import Path
from typing import Any

HISTORY_PATH = Path(__file__).resolve().parent / "task_history.json"
MAX_HISTORY = 100


def _load() -> list[dict]:
    try:
        if HISTORY_PATH.exists():
            data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save(items: list[dict]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(
        json.dumps(items[-MAX_HISTORY:], indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def _extract_saved_file(result: Any) -> str:
    text = str(result or "")

    # Matches: File saved: /Users/.../file.txt (123 bytes)
    m = re.search(r"File saved:\s*(.+?)(?:\s*\(\d+ bytes\)|$)", text)
    if m:
        return m.group(1).strip()

    # Matches any obvious absolute Desktop path
    m = re.search(r"(/Users/[^\n\r]+?\.(?:txt|md|json|csv|pdf|docx|html))", text)
    if m:
        return m.group(1).strip()

    return ""


def record_task(
    task_id: str,
    goal: str,
    status: str,
    result: Any = None,
    error: str = "",
) -> dict:
    entry = {
        "task_id": task_id,
        "goal": goal,
        "status": status,
        "result": str(result or ""),
        "error": str(error or ""),
        "saved_file": _extract_saved_file(result),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    from core.tenant import get_current_user_id

    user_id = get_current_user_id()
    if user_id:
        from api.repositories import add_task_record

        db_entry = dict(entry)
        db_entry.pop("timestamp", None)
        return add_task_record(user_id, db_entry)

    items = _load()

    items.append(entry)
    _save(items)
    return entry


def get_history(limit: int = 10, status: str | None = None) -> list[dict]:
    from core.tenant import get_current_user_id

    user_id = get_current_user_id()
    if user_id:
        from api.repositories import task_history

        return task_history(user_id, limit=limit, status=status)
    items = _load()
    if status:
        items = [x for x in items if x.get("status") == status]
    return items[-limit:]


def get_last() -> dict | None:
    items = get_history(limit=1)
    return items[-1] if items else None


def format_history(limit: int = 8, status: str | None = None) -> str:
    items = get_history(limit=limit, status=status)

    if not items:
        return "No saved task history found."

    lines = []
    for item in items:
        saved = item.get("saved_file") or "No saved file"
        error = item.get("error") or "None"
        lines.append(
            f"{item.get('timestamp')} — {item.get('task_id')} — {item.get('status')}\n"
            f"Goal: {item.get('goal')}\n"
            f"Saved file: {saved}\n"
            f"Error: {error}"
        )

    return "\n\n".join(lines)
