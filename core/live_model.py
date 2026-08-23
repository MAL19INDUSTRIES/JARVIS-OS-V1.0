"""Shared Gemini Live model selection for startup audio and active JARVIS."""

from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULT_LIVE_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"
LIVE_ACTION = "bidiGenerateContent"


def configured_live_model(config_path: Path) -> str:
    env_model = os.environ.get("GEMINI_LIVE_MODEL", "").strip()
    if env_model:
        return env_model
    try:
        configured = str(
            json.loads(config_path.read_text(encoding="utf-8")).get("live_model", "") or ""
        ).strip()
    except Exception:
        configured = ""
    return configured or DEFAULT_LIVE_MODEL


def _model_name(model) -> str:
    return str(getattr(model, "name", "") or "").strip()


def _model_actions(model) -> set[str]:
    actions = getattr(model, "supported_actions", None)
    if actions is None:
        actions = getattr(model, "supportedActions", None)
    return {str(action).lower() for action in (actions or [])}


def pick_live_model(client, config_path: Path) -> str:
    configured = configured_live_model(config_path)
    try:
        models = list(client.models.list())
    except Exception as exc:
        print(
            f"[JARVIS] Could not list Gemini models; using configured "
            f"live_model={configured}: {exc}"
        )
        return configured

    live_models = [
        _model_name(model)
        for model in models
        if LIVE_ACTION.lower() in _model_actions(model) and _model_name(model)
    ]
    if not live_models:
        raise RuntimeError(
            "No Gemini Live-capable model is available for this API key. "
            "Check that Gemini Live API access is enabled."
        )
    if configured in live_models:
        return configured

    def score(name: str) -> tuple[int, str]:
        lowered = name.lower()
        if "native-audio" in lowered:
            return (0, name)
        if "live" in lowered:
            return (1, name)
        if "flash" in lowered:
            return (2, name)
        return (3, name)

    selected = sorted(live_models, key=score)[0]
    print(f"[JARVIS] Auto-selected Live model: {selected}")
    return selected
