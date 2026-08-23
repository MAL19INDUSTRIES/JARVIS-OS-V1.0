"""Encrypted per-user secret persistence."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.secret_store import SecretCipher

from .config import settings
from .models import UserSecret


def _cipher() -> SecretCipher:
    master = settings.encryption_key or settings.jwt_secret
    return SecretCipher(master)


def set_user_secret(db: Session, user_id: str, name: str, value: str) -> None:
    encrypted = _cipher().encrypt(value)
    row = db.scalar(select(UserSecret).where(
        UserSecret.user_id == user_id,
        UserSecret.name == name,
    ))
    if row:
        row.encrypted_value = encrypted
    else:
        db.add(UserSecret(user_id=user_id, name=name, encrypted_value=encrypted))
    db.commit()


def get_user_secret(db: Session, user_id: str, name: str) -> str | None:
    row = db.scalar(select(UserSecret).where(
        UserSecret.user_id == user_id,
        UserSecret.name == name,
    ))
    return _cipher().decrypt(row.encrypted_value) if row else None


def delete_user_secret(db: Session, user_id: str, name: str) -> None:
    db.execute(delete(UserSecret).where(
        UserSecret.user_id == user_id,
        UserSecret.name == name,
    ))
    db.commit()


def has_user_secret(db: Session, user_id: str, name: str) -> bool:
    return db.scalar(select(UserSecret.id).where(
        UserSecret.user_id == user_id,
        UserSecret.name == name,
    )) is not None
