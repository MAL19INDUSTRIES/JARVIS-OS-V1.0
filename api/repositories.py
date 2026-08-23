"""Small synchronous repositories used by API routes and legacy engine facades."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select

from .database import SessionLocal
from .models import AnswerCacheEntry, ChatMessage, MemoryEntry, TaskRecord, UserConfig


MEMORY_CATEGORIES = (
    "identity", "preferences", "projects", "relationships", "wishes", "notes"
)


def load_user_memory(user_id: str) -> dict:
    result = {category: {} for category in MEMORY_CATEGORIES}
    with SessionLocal() as db:
        rows = db.scalars(
            select(MemoryEntry).where(MemoryEntry.user_id == user_id)
        ).all()
    for row in rows:
        result.setdefault(row.category, {})[row.key] = {
            "value": row.value,
            "updated": row.updated_at.date().isoformat(),
        }
    return result


def replace_user_memory(user_id: str, memory: dict) -> None:
    with SessionLocal.begin() as db:
        db.execute(delete(MemoryEntry).where(MemoryEntry.user_id == user_id))
        for category, items in memory.items():
            if not isinstance(items, dict):
                continue
            for key, entry in items.items():
                value = entry.get("value") if isinstance(entry, dict) else entry
                if value is None:
                    continue
                db.add(MemoryEntry(
                    user_id=user_id,
                    category=str(category),
                    key=str(key),
                    value=str(value),
                ))


def load_user_config(user_id: str, namespace: str = "general") -> dict:
    with SessionLocal() as db:
        rows = db.scalars(select(UserConfig).where(
            UserConfig.user_id == user_id,
            UserConfig.namespace == namespace,
        )).all()
    return {row.key: row.value for row in rows}


def save_user_config(user_id: str, values: dict, namespace: str = "general") -> None:
    with SessionLocal.begin() as db:
        for key, value in values.items():
            row = db.scalar(select(UserConfig).where(
                UserConfig.user_id == user_id,
                UserConfig.namespace == namespace,
                UserConfig.key == str(key),
            ))
            if row:
                row.value = value
            else:
                db.add(UserConfig(
                    user_id=user_id,
                    namespace=namespace,
                    key=str(key),
                    value=value,
                ))


def add_chat_message(user_id: str, role: str, content: str) -> ChatMessage:
    with SessionLocal.begin() as db:
        row = ChatMessage(user_id=user_id, role=role, content=content)
        db.add(row)
    return row


def recent_chat_messages(user_id: str, limit: int = 20) -> list[ChatMessage]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(ChatMessage)
            .where(ChatMessage.user_id == user_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        ).all()
        return list(reversed(rows))


def add_task_record(user_id: str, payload: dict) -> dict:
    with SessionLocal.begin() as db:
        row = TaskRecord(user_id=user_id, **payload)
        db.add(row)
    return task_record_dict(row)


def task_history(user_id: str, limit: int, status: str | None = None) -> list[dict]:
    with SessionLocal() as db:
        query = select(TaskRecord).where(TaskRecord.user_id == user_id)
        if status:
            query = query.where(TaskRecord.status == status)
        rows = db.scalars(query.order_by(TaskRecord.created_at.desc()).limit(limit)).all()
    return [task_record_dict(row) for row in reversed(rows)]


def task_record_dict(row: TaskRecord) -> dict:
    return {
        "task_id": row.task_id,
        "goal": row.goal,
        "status": row.status,
        "result": row.result,
        "error": row.error,
        "saved_file": row.saved_file,
        "timestamp": row.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_cached(user_id: str, normalized_question: str) -> str | None:
    with SessionLocal.begin() as db:
        row = db.scalar(select(AnswerCacheEntry).where(
            AnswerCacheEntry.user_id == user_id,
            AnswerCacheEntry.normalized_question == normalized_question,
        ))
        if not row:
            return None
        row.hits += 1
        row.updated_at = datetime.now(row.updated_at.tzinfo)
        return row.answer


def put_cached(user_id: str, normalized_question: str, question: str, answer: str) -> None:
    with SessionLocal.begin() as db:
        row = db.scalar(select(AnswerCacheEntry).where(
            AnswerCacheEntry.user_id == user_id,
            AnswerCacheEntry.normalized_question == normalized_question,
        ))
        if row:
            row.question = question
            row.answer = answer
        else:
            db.add(AnswerCacheEntry(
                user_id=user_id,
                normalized_question=normalized_question,
                question=question,
                answer=answer,
            ))
