"""Password hashing and compact HS256 JWT sessions without framework coupling."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import secrets

from .config import settings


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Password must contain at least 10 characters")
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64
    )
    return "scrypt$16384$8$1$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.urlsafe_b64decode(salt),
            n=int(n), r=int(r), p=int(p), dklen=64,
        )
        return hmac.compare_digest(digest, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError):
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_minutes)).timestamp()),
        "jti": secrets.token_urlsafe(12),
        "type": "access",
    }
    header = {"alg": "HS256", "typ": "JWT"}
    unsigned = ".".join((
        _b64(json.dumps(header, separators=(",", ":")).encode()),
        _b64(json.dumps(payload, separators=(",", ":")).encode()),
    ))
    signature = hmac.new(
        settings.jwt_secret.encode("utf-8"), unsigned.encode("ascii"), hashlib.sha256
    ).digest()
    return unsigned + "." + _b64(signature)


def decode_access_token(token: str) -> dict:
    try:
        header_part, payload_part, signature_part = token.split(".")
        unsigned = f"{header_part}.{payload_part}"
        expected = hmac.new(
            settings.jwt_secret.encode("utf-8"), unsigned.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _unb64(signature_part)):
            raise ValueError("Invalid token signature")
        header = json.loads(_unb64(header_part))
        payload = json.loads(_unb64(payload_part))
        if header.get("alg") != "HS256" or payload.get("type") != "access":
            raise ValueError("Invalid token type")
        if int(payload.get("exp", 0)) <= int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("Session expired")
        if not payload.get("sub"):
            raise ValueError("Invalid token subject")
        return payload
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid or expired session") from exc
