from __future__ import annotations

"""Small abstraction for storing/retrieving secrets locally.

Currently uses `keyring` (OS keychain). Falls back to an in-memory stub if
keyring backend isn't available.
"""

from dataclasses import dataclass
import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

SERVICE = "jarvis"


@dataclass
class SecretStore:
    """Key/value secret store."""

    def set(self, key: str, value: str) -> None:
        raise NotImplementedError

    def get(self, key: str) -> Optional[str]:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError


class KeyringSecretStore(SecretStore):
    def __init__(self, service: str = SERVICE):
        self.service = service
        import keyring

        self._keyring = keyring

    def set(self, key: str, value: str) -> None:
        # keyring handles encryption on supported platforms.
        self._keyring.set_password(self.service, key, value)

    def get(self, key: str) -> Optional[str]:
        try:
            return self._keyring.get_password(self.service, key)
        except Exception:
            # A locked/unavailable macOS Keychain must not abort JARVIS boot.
            # Setup remains available so the user can validate a session key.
            return None

    def delete(self, key: str) -> None:
        try:
            self._keyring.delete_password(self.service, key)
        except Exception:
            # Missing entries and unavailable backends should not crash setup.
            pass


class NoopSecretStore(SecretStore):
    """Does not persist secrets; used if keyring cannot be used."""

    def __init__(self):
        self._mem: dict[str, str] = {}

    def set(self, key: str, value: str) -> None:
        self._mem[key] = value

    def get(self, key: str) -> Optional[str]:
        return self._mem.get(key)

    def delete(self, key: str) -> None:
        self._mem.pop(key, None)


class SecretCipher:
    """Authenticated encryption for secrets stored outside an OS keychain."""

    def __init__(self, master_secret: str):
        if not isinstance(master_secret, str) or len(master_secret) < 20:
            raise ValueError("The secret encryption key must contain at least 20 characters")
        digest = hashlib.sha256(master_secret.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, value: str) -> str:
        if not value:
            raise ValueError("Cannot encrypt an empty secret")
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as exc:
            raise ValueError("Stored secret could not be decrypted") from exc


class TenantDatabaseSecretStore(SecretStore):
    """Encrypted SecretStore view scoped to one hosted user."""

    def __init__(self, user_id: str):
        self.user_id = user_id

    def set(self, key: str, value: str) -> None:
        from api.database import SessionLocal
        from api.secret_service import set_user_secret

        with SessionLocal() as db:
            set_user_secret(db, self.user_id, key, value)

    def get(self, key: str) -> Optional[str]:
        from api.database import SessionLocal
        from api.secret_service import get_user_secret

        with SessionLocal() as db:
            return get_user_secret(db, self.user_id, key)

    def delete(self, key: str) -> None:
        from api.database import SessionLocal
        from api.secret_service import delete_user_secret

        with SessionLocal() as db:
            delete_user_secret(db, self.user_id, key)


_store: SecretStore | None = None


def get_secret_store() -> SecretStore:
    from core.tenant import get_current_user_id

    user_id = get_current_user_id()
    if user_id:
        return TenantDatabaseSecretStore(user_id)
    global _store
    if _store is not None:
        return _store

    try:
        _store = KeyringSecretStore()
    except Exception:
        _store = NoopSecretStore()
    return _store
