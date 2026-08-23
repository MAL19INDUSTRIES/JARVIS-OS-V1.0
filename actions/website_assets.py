"""Local image generation and optimization for generated websites."""

from __future__ import annotations

import base64
import io
import os
import re
from pathlib import Path
from typing import Any


MAX_WEBSITE_ASSETS = 4
MAX_ASSET_EDGE = 1920


def _slug(value: Any, fallback: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return clean[:64] or fallback


def _image_bytes(result: Any) -> bytes | None:
    image = getattr(result, "output_image", None)
    data = getattr(image, "data", None) if image is not None else None
    if data:
        return base64.b64decode(data) if isinstance(data, str) else bytes(data)
    for candidate in getattr(result, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            raw = getattr(inline, "data", None) if inline is not None else None
            if raw:
                return base64.b64decode(raw) if isinstance(raw, str) else bytes(raw)
    return None


def _optimize_webp(raw: bytes, output: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as source:
        image = source.convert("RGB")
        image.thumbnail((MAX_ASSET_EDGE, MAX_ASSET_EDGE), Image.Resampling.LANCZOS)
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, "WEBP", quality=84, method=6)
        return image.size


def generate_website_assets(
    plan: list[dict[str, Any]],
    project_dir: Path,
    *,
    api_key: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Generate a bounded set of local, provenance-friendly website assets."""

    requested = [item for item in plan[:MAX_WEBSITE_ASSETS] if isinstance(item, dict)]
    if not requested:
        return [], []

    warnings: list[str] = []
    manifest: list[dict[str, Any]] = []
    try:
        from google import genai
        from memory.config_manager import get_gemini_key

        key = api_key or get_gemini_key()
        if not key:
            return [], ["Generated imagery was skipped because no Gemini key is configured."]
        client = genai.Client(api_key=key)
        model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
    except Exception as exc:
        return [], [f"Generated imagery is unavailable: {exc}"]

    for index, item in enumerate(requested, start=1):
        prompt = str(item.get("prompt") or "").strip()
        alt = str(item.get("alt") or "").strip()
        if not prompt or not alt:
            warnings.append(f"Asset {index} was skipped because its prompt or alt text is missing.")
            continue
        asset_id = _slug(item.get("id"), f"visual-{index}")
        aspect_ratio = str(item.get("aspect_ratio") or "16:9")
        if aspect_ratio not in {"1:1", "3:2", "4:3", "16:9", "9:16"}:
            aspect_ratio = "16:9"
        output = project_dir / "public" / "assets" / f"{asset_id}.webp"
        try:
            result = client.interactions.create(
                model=model,
                input=(
                    "Create an original image for a production website. No text, logos, "
                    "watermarks, interface chrome, badges, or recognizable brand marks. "
                    f"The image must support this specific brief: {prompt}"
                ),
                response_format={
                    "type": "image",
                    "mime_type": "image/png",
                    "aspect_ratio": aspect_ratio,
                    "image_size": "1K",
                },
            )
            raw = _image_bytes(result)
            if not raw:
                raise RuntimeError("the image model returned no image")
            width, height = _optimize_webp(raw, output)
            manifest.append({
                "id": asset_id,
                "path": f"/assets/{output.name}",
                "alt": alt,
                "width": width,
                "height": height,
                "aspect_ratio": aspect_ratio,
            })
        except Exception as exc:
            warnings.append(f"Asset '{asset_id}' could not be generated: {exc}")
    return manifest, warnings


__all__ = ["MAX_WEBSITE_ASSETS", "generate_website_assets"]
