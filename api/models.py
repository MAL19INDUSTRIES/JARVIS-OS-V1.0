"""Hosted persistence models. Every user-owned record carries user_id."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    secrets = relationship("UserSecret", cascade="all, delete-orphan")


class UserSecret(Base):
    __tablename__ = "user_secrets"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_secret_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    encrypted_value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class MemoryEntry(Base):
    __tablename__ = "memory_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "category", "key", name="uq_memory_user_category_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(120))
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class UserConfig(Base):
    __tablename__ = "user_configs"
    __table_args__ = (
        UniqueConstraint("user_id", "namespace", "key", name="uq_user_config_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    namespace: Mapped[str] = mapped_column(String(64), default="general")
    key: Mapped[str] = mapped_column(String(120))
    value: Mapped[object] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TaskRecord(Base):
    __tablename__ = "task_records"
    __table_args__ = (Index("ix_task_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str] = mapped_column(String(80), index=True)
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40))
    result: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    saved_file: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AnswerCacheEntry(Base):
    __tablename__ = "answer_cache_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "normalized_question", name="uq_answer_user_question"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    normalized_question: Mapped[str] = mapped_column(String(260))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
