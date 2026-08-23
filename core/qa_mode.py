"""Safety boundary used by the reusable JARVIS QA harness.

QA mode is intentionally opt-in. Normal runtime behavior is unchanged unless
``JARVIS_QA_MODE=1`` is present in the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


QA_MODE_ENV = "JARVIS_QA_MODE"
QA_WORKSPACE_ENV = "JARVIS_QA_WORKSPACE"


@dataclass(frozen=True)
class QAGuardDecision:
    allowed: bool
    reason: str = ""


def qa_enabled() -> bool:
    return os.environ.get(QA_MODE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def qa_workspace() -> Path | None:
    raw = os.environ.get(QA_WORKSPACE_ENV, "").strip()
    return Path(raw).expanduser().resolve() if raw else None


def _opt_in(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _action(args: dict[str, Any]) -> str:
    return str(args.get("action", "") or args.get("operation", "")).lower().strip().replace(" ", "_")


def _paths_in(value: Any, key: str = ""):
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _paths_in(child, str(child_key))
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _paths_in(child, key)
    elif isinstance(value, str) and any(marker in key.lower() for marker in ("path", "file", "folder", "directory", "destination", "output")):
        yield value


def _path_is_in_workspace(raw: str, workspace: Path | None) -> bool:
    if not raw or workspace is None:
        return False
    try:
        target = Path(raw).expanduser().resolve()
        return target == workspace or target.is_relative_to(workspace)
    except (OSError, RuntimeError, ValueError):
        return False


def guard_tool_call(name: str, args: dict[str, Any] | None = None) -> QAGuardDecision:
    """Return whether a tool call is safe under the current QA policy."""
    if not qa_enabled():
        return QAGuardDecision(True)

    tool = str(name or "").lower().strip()
    payload = dict(args or {})
    action = _action(payload)
    workspace = qa_workspace()

    if tool == "send_message":
        return QAGuardDecision(False, "QA mode never sends real messages.")

    if tool == "prepare_message_reply" and not _opt_in("JARVIS_QA_ALLOW_DRAFTS"):
        return QAGuardDecision(False, "QA draft typing requires JARVIS_QA_ALLOW_DRAFTS=1.")

    if tool == "email_control":
        if action == "approve":
            return QAGuardDecision(False, "QA mode never sends real email.")
        if not _opt_in("JARVIS_QA_ALLOW_EMAIL"):
            return QAGuardDecision(False, "QA email access requires JARVIS_QA_ALLOW_EMAIL=1.")

    if tool in {"open_app", "browser_control"} and not _opt_in(
        "JARVIS_QA_ALLOW_BROWSER" if tool == "browser_control" else "JARVIS_QA_ALLOW_DESKTOP"
    ):
        return QAGuardDecision(False, f"QA {tool} control requires explicit supervised opt-in.")

    if tool == "media_control" and not _opt_in("JARVIS_QA_ALLOW_DESKTOP"):
        return QAGuardDecision(False, "QA media playback requires JARVIS_QA_ALLOW_DESKTOP=1.")

    if tool in {"computer_control", "computer_settings"}:
        safe_read_actions = {"screenshot", "get_clipboard", "screen_size"}
        if action not in safe_read_actions and not _opt_in("JARVIS_QA_ALLOW_DESKTOP"):
            return QAGuardDecision(False, "QA desktop mutation requires JARVIS_QA_ALLOW_DESKTOP=1.")
        if action in {
            "shutdown", "restart", "reboot", "lock", "lock_screen", "sleep", "sleep_display",
            "toggle_wifi", "quit_app", "close_app",
        }:
            return QAGuardDecision(False, f"QA mode blocks dangerous desktop action: {action}.")

    if tool == "desktop_control":
        safe_reads = {"list", "list_desktop", "stats", "get_stats", "get_wallpaper", "current_wallpaper"}
        if action not in safe_reads and not _opt_in("JARVIS_QA_ALLOW_DESKTOP"):
            return QAGuardDecision(False, "QA desktop changes require JARVIS_QA_ALLOW_DESKTOP=1.")

    if tool == "game_updater":
        safe_reads = {"status", "download_status", "schedule_status", "list", "list_games"}
        if action not in safe_reads:
            return QAGuardDecision(False, f"QA mode blocks game mutation: {action or 'unspecified'}.")

    if tool == "reminder" and not _opt_in("JARVIS_QA_ALLOW_REMINDERS"):
        return QAGuardDecision(False, "QA reminders require JARVIS_QA_ALLOW_REMINDERS=1.")

    if tool == "save_memory" and not _opt_in("JARVIS_QA_ALLOW_MEMORY"):
        return QAGuardDecision(False, "QA memory writes require JARVIS_QA_ALLOW_MEMORY=1.")

    write_capable = {
        "file_controller", "file_processor", "code_helper", "website_builder", "dev_agent",
        "create_presentation",
    }
    if tool in write_capable:
        raw_paths = list(_paths_in(payload))
        if not raw_paths or any(not _path_is_in_workspace(path, workspace) for path in raw_paths):
            return QAGuardDecision(
                False,
                "QA file-writing tools must use explicit paths inside JARVIS_QA_WORKSPACE.",
            )

    return QAGuardDecision(True)


def qa_block_message(decision: QAGuardDecision) -> str:
    return f"QA SAFETY BLOCK: {decision.reason}"
