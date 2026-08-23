"""User-supplied and Gemini-generated visual asset handling."""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any, Callable

from .models import PresentationRequest, SourceBundle


IMAGE_QUOTA_COOLDOWN_SECONDS = 5 * 60
_image_quota_cooldown_until = 0.0


def _is_quota_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(token in message for token in ("429", "quota", "resource_exhausted", "rate limit"))


def _image_quota_cooldown_active() -> bool:
    return time.monotonic() < _image_quota_cooldown_until


def _mark_image_quota_cooldown() -> None:
    global _image_quota_cooldown_until
    _image_quota_cooldown_until = time.monotonic() + IMAGE_QUOTA_COOLDOWN_SECONDS


def _image_request_limit(request: PresentationRequest, slide_total: int) -> int:
    """Keep image generation useful without turning one deck into an API burst."""
    if request.quality == "fast" or slide_total < 1:
        return 0
    if request.quality == "premium":
        return min(5, slide_total)
    return min(2, slide_total)


def _resolve_unbuilt_visuals(
    plan: dict,
    prompts: list[tuple[int, str]],
    generated_refs: list[str],
) -> int:
    """Reuse a small visual set or remove empty image layouts after quota stops."""
    reused = 0
    for index, (slide_number, _prompt) in enumerate(prompts):
        slide = plan["slides"][slide_number - 1]
        if slide.get("asset_ref"):
            continue
        slide["image_prompt"] = ""
        if generated_refs:
            slide["asset_ref"] = generated_refs[index % len(generated_refs)]
            reused += 1
        elif slide.get("type") == "image":
            slide["type"] = "statement"
            slide["proof_type"] = "statement"
    return reused


def supplied_asset_lookup(bundle: SourceBundle) -> dict[str, Path]:
    lookup: dict[str, Path] = {}
    for record in bundle.records:
        if record.media_path and record.kind in {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tif", "tiff"}:
            path = record.media_path
            lookup[path.name.lower()] = path
            lookup[path.stem.lower()] = path
            lookup[record.label.lower()] = path
    return lookup


def _write_generated_image(result: Any, output: Path) -> bool:
    image = getattr(result, "output_image", None)
    data = getattr(image, "data", None) if image is not None else None
    if data:
        output.write_bytes(base64.b64decode(data) if isinstance(data, str) else data)
        return True
    for candidate in getattr(result, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                raw = inline.data
                output.write_bytes(base64.b64decode(raw) if isinstance(raw, str) else raw)
                return True
    return False


def generate_planned_assets(
    plan: dict,
    request: PresentationRequest,
    bundle: SourceBundle,
    workspace: Path,
    progress_callback: Callable | None = None,
    cancel_flag: Any = None,
    api_key: str = "",
) -> tuple[dict[str, Path], list[str]]:
    lookup = supplied_asset_lookup(bundle)
    warnings: list[str] = []
    if request.quality == "fast":
        return lookup, warnings

    prompts = []
    for index, slide in enumerate(plan.get("slides", []), start=1):
        prompt = str(slide.get("image_prompt") or "").strip()
        if prompt and not slide.get("asset_ref"):
            prompts.append((index, prompt))
    slide_total = len(plan.get("slides", []))
    limit = _image_request_limit(request, slide_total)
    if not prompts:
        return lookup, warnings

    if _image_quota_cooldown_active():
        _resolve_unbuilt_visuals(plan, prompts, [])
        warnings.append(
            "Gemini image generation is in a short quota cooldown. JARVIS skipped new image "
            "requests and used a clean shape-based layout instead."
        )
        return lookup, warnings

    selected_prompts = prompts[:limit]
    generated_refs: list[str] = []

    try:
        from google import genai

        client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY") or None)
        asset_dir = workspace / "assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
        for completed, (slide_number, prompt) in enumerate(selected_prompts, start=1):
            if cancel_flag is not None and cancel_flag.is_set():
                raise RuntimeError("Presentation creation was cancelled.")
            output = asset_dir / f"generated-slide-{slide_number:02d}.png"
            try:
                result = client.interactions.create(
                    model=model,
                    input=(
                        "Create a premium editorial presentation image. No text, logos, app icons, "
                        "watermarks, badges, or brand marks. Widescreen composition. " + prompt
                    ),
                    response_format={
                        "type": "image",
                        "mime_type": "image/png",
                        "aspect_ratio": "16:9",
                        "image_size": "1K",
                    },
                )
                if _write_generated_image(result, output):
                    key = f"generated:{slide_number}"
                    lookup[key] = output
                    plan["slides"][slide_number - 1]["asset_ref"] = key
                    generated_refs.append(key)
                else:
                    warnings.append(f"No generated image was returned for slide {slide_number}.")
            except Exception as exc:
                if _is_quota_error(exc):
                    _mark_image_quota_cooldown()
                    warnings.append(
                        "Gemini image quota was reached. JARVIS stopped additional image requests "
                        "and finished the deck with the visuals already available."
                    )
                    break
                warnings.append(f"Image generation failed for slide {slide_number}: {exc}")
            if progress_callback:
                progress_callback(
                    percent=45 + int(10 * completed / max(1, len(selected_prompts))),
                    phase=f"Creating visual assets ({completed}/{len(selected_prompts)})",
                )
    except Exception as exc:
        warnings.append(f"Generated imagery was unavailable: {exc}")
    reused = _resolve_unbuilt_visuals(plan, prompts, generated_refs)
    if reused:
        warnings.append(
            f"Reused {len(generated_refs)} generated visual(s) across {reused} additional slide(s) "
            "to stay within the presentation API budget."
        )
    return lookup, warnings
