"""JarvisClient adapter that emits engine events as WebSocket JSON frames."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket


class WebSocketClient:
    def __init__(self, websocket: WebSocket, user_id: str | None = None):
        self.websocket = websocket
        self.user_id = user_id
        self.on_text_command: Callable[[str], None] | None = None
        self.on_mode_change: Callable[[str], None] | None = None
        self.muted = False
        self.current_file: str | None = None
        self.current_mode = "jarvis"
        self._voice_combo = None
        self.state = "CONNECTING"
        self._loop = asyncio.get_running_loop()
        self._events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=256)

    def _emit(self, event: dict[str, Any]) -> None:
        event.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

        def enqueue() -> None:
            if self._events.full():
                try:
                    self._events.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            self._events.put_nowait(event)

        self._loop.call_soon_threadsafe(enqueue)

    def write_log(self, text: str) -> None:
        role = "system"
        content = str(text)
        if content.startswith("You: "):
            role, content = "user", content[5:]
        elif content.startswith("Jarvis: "):
            role, content = "assistant", content[8:]
        if self.user_id and role in {"user", "assistant"}:
            from .repositories import add_chat_message

            add_chat_message(self.user_id, role, content)
        self._emit({"type": "message", "role": role, "content": content})

    def set_state(self, state: str) -> None:
        self.state = str(state).upper()
        self._emit({"type": "status", "state": self.state})

    def show_subtitle(self, text: str) -> None:
        self._emit({"type": "transcript", "content": str(text), "final": False})

    def clear_subtitle(self) -> None:
        self._emit({"type": "transcript_clear"})

    def activate_mode(self, mode: str) -> None:
        self.current_mode = str(mode or "jarvis").lower()
        self._emit({"type": "preference", "name": "mode", "value": self.current_mode})

    def set_mode_switching(self, switching: bool, target_mode: str) -> None:
        self._emit({
            "type": "mode_switch",
            "switching": bool(switching),
            "target_mode": str(target_mode or self.current_mode).lower(),
        })

    def stop_audio_playback(self) -> None:
        """Tell browser clients to discard already-scheduled outgoing speech."""
        self._emit({"type": "audio_reset"})

    def set_graphics_quality(self, quality: str) -> None:
        self._emit({"type": "preference", "name": "graphics_quality", "value": quality})

    def sync_voice_display(self, voice_name: str) -> None:
        self._emit({"type": "preference", "name": "voice", "value": voice_name})

    def handle_ui_command(self, action: str) -> None:
        self._emit({"type": "ui_command", "action": action})

    def show_research_progress(self, question: str) -> None:
        self._emit({"type": "progress", "kind": "research", "label": question, "percent": 0, "phase": "Queued"})

    def update_research_progress(self, question: str, percent: int, phase: str, artifacts=None, warnings=None) -> None:
        self._emit({"type": "progress", "kind": "research", "label": question, "percent": percent, "phase": phase, "artifacts": artifacts or [], "warnings": warnings or []})

    def finish_research_progress(self, state: str, detail: str) -> None:
        self._emit({"type": "progress_end", "kind": "research", "state": state, "detail": detail})

    def hide_research_progress(self) -> None:
        self._emit({"type": "progress_hide", "kind": "research"})

    def show_presentation_progress(self, title: str, visible: bool = False) -> None:
        self._emit({"type": "progress", "kind": "presentation", "label": title, "percent": 0, "phase": "Queued", "visible": visible})

    def update_presentation_progress(self, title: str, percent: int, phase: str, visible: bool = False, artifacts=None, warnings=None) -> None:
        self._emit({"type": "progress", "kind": "presentation", "label": title, "percent": percent, "phase": phase, "visible": visible, "artifacts": artifacts or [], "warnings": warnings or []})

    def finish_presentation_progress(self, state: str, detail: str) -> None:
        self._emit({"type": "progress_end", "kind": "presentation", "state": state, "detail": detail})

    def hide_presentation_progress(self) -> None:
        self._emit({"type": "progress_hide", "kind": "presentation"})

    def send_audio(self, data: bytes, mime_type: str = "audio/pcm;rate=24000") -> None:
        self._emit({
            "type": "audio",
            "mime_type": mime_type,
            "data": base64.b64encode(data).decode("ascii"),
        })

    async def send_events(self) -> None:
        while True:
            event = await self._events.get()
            if event is None:
                return
            await self.websocket.send_json(event)

    async def close(self) -> None:
        await self._events.put(None)
