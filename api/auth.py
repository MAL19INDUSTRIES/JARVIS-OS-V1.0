"""FastAPI authentication dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .security import decode_access_token


bearer = HTTPBearer(auto_error=False)


def _user_for_token(token: str, db: Session) -> User:
    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    user = db.get(User, str(payload["sub"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found")
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return _user_for_token(credentials.credentials, db)


def websocket_user(websocket: WebSocket, db: Session) -> User:
    token = websocket.query_params.get("token", "")
    if not token:
        authorization = websocket.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    return _user_for_token(token, db)
