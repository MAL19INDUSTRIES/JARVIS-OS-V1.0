"""Transport-neutral client contract for the JARVIS live engine."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable


class VoiceSelector(Protocol):
    """Small legacy surface used to read the desktop voice selector."""

    def currentIndex(self) -> int: ...

    def itemData(self, index: int) -> Any: ...

    def currentText(self) -> str: ...


@runtime_checkable
class JarvisClient(Protocol):
    """Events and state the live engine needs from any connected client.

    The PyQt desktop adapter and future WebSocket adapter can both implement
    this contract without the engine importing either UI framework.
    """

    on_text_command: Callable[[str], None] | None
    on_mode_change: Callable[[str], None] | None

    @property
    def muted(self) -> bool: ...

    @property
    def current_file(self) -> str | None: ...

    @property
    def current_mode(self) -> str: ...

    @property
    def _voice_combo(self) -> VoiceSelector | None: ...

    def write_log(self, text: str) -> None: ...

    def set_state(self, state: str) -> None: ...

    def show_subtitle(self, text: str) -> None: ...

    def clear_subtitle(self) -> None: ...

    def activate_mode(self, mode: str) -> None: ...

    def set_graphics_quality(self, quality: str) -> None: ...

    def sync_voice_display(self, voice_name: str) -> None: ...

    def handle_ui_command(self, action: str) -> None: ...
