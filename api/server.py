"""Authenticated multi-user HTTP and Gemini Live WebSocket API."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.api_key_validator import normalize_gemini_api_key, validate_gemini_api_key
from core.tenant import tenant_scope
from memory.memory_manager import format_memory_for_prompt, load_memory

from .auth import get_current_user, websocket_user
from .config import settings
from .database import SessionLocal, get_db, init_db
from .models import User
from .rate_limit import limiter
from .repositories import add_chat_message, recent_chat_messages
from .schemas import (
    ChatRequest,
    ChatResponse,
    GeminiKeyRequest,
    LoginRequest,
    SessionView,
    UserCreate,
    UserView,
)
from .secret_service import (
    delete_user_secret,
    get_user_secret,
    has_user_secret,
    set_user_secret,
)
from .security import create_access_token, hash_password, verify_password
from .websocket_client import WebSocketClient


class LiveSessionRegistry:
    def __init__(self):
        self._sessions: dict[str, tuple[Any, WebSocketClient, asyncio.Task]] = {}
        self._lock = asyncio.Lock()

    async def replace(self, user_id: str, engine, client: WebSocketClient, task: asyncio.Task) -> None:
        async with self._lock:
            previous = self._sessions.pop(user_id, None)
            self._sessions[user_id] = (engine, client, task)
        if previous:
            previous[0].request_shutdown()
            previous[2].cancel()

    async def remove(self, user_id: str, task: asyncio.Task) -> None:
        async with self._lock:
            current = self._sessions.get(user_id)
            if current and current[2] is task:
                self._sessions.pop(user_id, None)

    def status(self, user_id: str) -> dict:
        current = self._sessions.get(user_id)
        if not current:
            return {"state": "OFFLINE", "connected": False}
        engine, client, task = current
        return {
            "state": client.state,
            "connected": not task.done(),
            "voice": engine._get_current_voice(),
            "cloud_safe": True,
        }

    async def close_all(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for engine, client, task in sessions:
            engine.request_shutdown()
            task.cancel()
            await client.close()


live_sessions = LiveSessionRegistry()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_production()
    if settings.auto_create_tables:
        await asyncio.to_thread(init_db)
    await limiter.connect()
    try:
        yield
    finally:
        await live_sessions.close_all()
        await limiter.close()


app = FastAPI(
    title="JARVIS Cloud API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def _user_view(user: User, db: Session) -> UserView:
    return UserView(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        gemini_configured=has_user_secret(db, user.id, "gemini_api_key"),
    )


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "jarvis-api"}


@app.post("/auth/signup", response_model=SessionView, status_code=201)
async def signup(payload: UserCreate, db: Session = Depends(get_db)) -> SessionView:
    await limiter.consume(payload.email.lower(), "signup", 5, 3600)
    user = User(
        email=payload.email.lower().strip(),
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account already exists for this email") from exc
    db.refresh(user)
    return SessionView(access_token=create_access_token(user.id), user=_user_view(user, db))


@app.post("/auth/login", response_model=SessionView)
async def login(payload: LoginRequest, db: Session = Depends(get_db)) -> SessionView:
    await limiter.consume(payload.email.lower(), "login", 10, 300)
    user = db.scalar(select(User).where(User.email == payload.email.lower().strip()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    return SessionView(access_token=create_access_token(user.id), user=_user_view(user, db))


@app.get("/auth/me", response_model=UserView)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserView:
    return _user_view(user, db)


@app.post("/auth/logout", status_code=204)
def logout(_: User = Depends(get_current_user)) -> None:
    return None


@app.post("/me/gemini-key")
async def save_gemini_key(
    payload: GeminiKeyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    await limiter.consume(user.id, "secret", 8, 3600)
    key = normalize_gemini_api_key(payload.api_key)
    if payload.verify_key:
        validation = await asyncio.to_thread(validate_gemini_api_key, key)
        if not validation.valid:
            raise HTTPException(status_code=422, detail=validation.message)
    set_user_secret(db, user.id, "gemini_api_key", key)
    return {"configured": True}


@app.delete("/me/gemini-key", status_code=204)
def remove_gemini_key(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    delete_user_secret(db, user.id, "gemini_api_key")


@app.get("/status")
def get_status(user: User = Depends(get_current_user)) -> dict:
    return live_sessions.status(user.id)


@app.get("/actions")
def get_actions(_: User = Depends(get_current_user)) -> dict:
    from main import get_tool_declarations

    tools = get_tool_declarations(cloud_safe=True)
    return {
        "actions": [
            {"name": item["name"], "description": item.get("description", "")}
            for item in tools
        ]
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatResponse:
    await limiter.consume(user.id, "chat", 30, 60)
    api_key = get_user_secret(db, user.id, "gemini_api_key")
    if not api_key:
        raise HTTPException(status_code=409, detail="Add a Gemini API key before starting JARVIS")

    with tenant_scope(user.id):
        history = recent_chat_messages(user.id, limit=12)
        add_chat_message(user.id, "user", payload.message)
        memory = format_memory_for_prompt(load_memory())

        def generate() -> str:
            from google import genai
            from google.genai import types
            from main import _load_system_prompt

            client = genai.Client(api_key=api_key)
            context = "\n".join(
                f"{message.role.title()}: {message.content}" for message in history
            )
            prompt = (
                f"Recent conversation:\n{context}\n\n"
                f"Current user message: {payload.message}"
            )
            response = client.models.generate_content(
                model=settings.chat_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_load_system_prompt() + "\n\n" + memory,
                ),
            )
            return str(response.text or "").strip()

        response_text = await asyncio.to_thread(generate)
        if not response_text:
            raise HTTPException(status_code=502, detail="Gemini returned an empty response")
        add_chat_message(user.id, "assistant", response_text)
    return ChatResponse(response=response_text)


@app.websocket("/ws")
async def live_socket(websocket: WebSocket) -> None:
    from main import JarvisLive

    with SessionLocal() as db:
        try:
            user = websocket_user(websocket, db)
            await limiter.consume(user.id, "websocket", 12, 60)
            api_key = get_user_secret(db, user.id, "gemini_api_key")
        except HTTPException as exc:
            await websocket.close(code=4401, reason=str(exc.detail))
            return

    await websocket.accept()
    if not api_key:
        await websocket.send_json({
            "type": "error",
            "code": "gemini_key_required",
            "message": "Add a Gemini API key before starting JARVIS.",
        })
        await websocket.close(code=4403)
        return

    client = WebSocketClient(websocket, user.id)
    engine = JarvisLive(
        client,
        cloud_safe=True,
        api_key=api_key,
        external_audio=True,
    )
    sender_task = asyncio.create_task(client.send_events())
    with tenant_scope(user.id):
        engine_task = asyncio.create_task(engine.run())
    await live_sessions.replace(user.id, engine, client, engine_task)
    client._emit({
        "type": "ready",
        "state": "CONNECTING",
        "audio": {"input_rate": 16000, "output_rate": 24000, "encoding": "pcm_s16le"},
    })

    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes") is not None:
                await engine.send_audio_chunk(message["bytes"])
                continue
            raw = message.get("text")
            if raw is None:
                continue
            import json

            event = json.loads(raw)
            event_type = event.get("type")
            if event_type == "text":
                await limiter.consume(user.id, "live_text", 60, 60)
                with tenant_scope(user.id):
                    await engine.send_text(str(event.get("content", "")))
            elif event_type == "mode":
                requested_mode = str(event.get("mode") or "").strip().lower()
                if requested_mode not in {"jarvis", "ultron", "atlas"}:
                    client._emit({"type": "error", "message": "Unknown operational mode."})
                    continue
                engine.update_mode(requested_mode)
            elif event_type == "audio":
                data = base64.b64decode(event.get("data", ""), validate=True)
                await engine.send_audio_chunk(
                    data,
                    str(event.get("mime_type") or "audio/pcm;rate=16000"),
                )
            elif event_type == "mute":
                client.muted = bool(event.get("muted", True))
                client.set_state("MUTED" if client.muted else "LISTENING")
            elif event_type == "ping":
                client._emit({
                    "type": "pong",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            elif event_type == "close":
                break
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)[:240]})
        except Exception:
            pass
    finally:
        engine.request_shutdown()
        engine_task.cancel()
        await asyncio.gather(engine_task, return_exceptions=True)
        await live_sessions.remove(user.id, engine_task)
        await client.close()
        try:
            await sender_task
        except (Exception, asyncio.CancelledError):
            pass
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect):
            pass
