"""SQLAlchemy session and metadata configuration."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


DATABASE_URL = _normalize_database_url(settings.database_url)
if DATABASE_URL.startswith("sqlite:///./"):
    Path(DATABASE_URL.removeprefix("sqlite:///./")).parent.mkdir(
        parents=True,
        exist_ok=True,
    )


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def session_scope() -> Session:
    """Return a session for synchronous repositories and context-aware stores."""
    return SessionLocal()
