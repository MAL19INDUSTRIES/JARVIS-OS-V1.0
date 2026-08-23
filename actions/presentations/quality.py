"""Mechanical verification, native PDF export, and rendered presentation QA."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable


def verify_pptx(path: Path, expected_slides: int | None = None) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("The generated PowerPoint is missing or empty.")
    if not zipfile.is_zipfile(path):
        raise RuntimeError("The generated file is not a valid PowerPoint package.")

    with zipfile.ZipFile(path) as package:
        names = package.namelist()
        slide_parts = [
            name for name in names
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        ]
        empty_media = [
            info.filename for info in package.infolist()
            if info.filename.startswith("ppt/media/") and info.file_size == 0
        ]
        chart_parts = [
            name for name in names
            if name.startswith("ppt/charts/chart") and name.endswith(".xml")
        ]
        model_parts = [name for name in names if name.lower().endswith(".glb")]
        model_shapes = 0
        model_slides = 0
        transition_slides = 0
        morph_slides = 0
        for name in slide_parts:
            raw = package.read(name)
            lowered = raw.lower()
            count = lowered.count(b"<am3d:model3d")
            if count:
                model_shapes += count
                model_slides += 1
            local_names: set[str] = set()
            try:
                local_names = {
                    node.tag.rsplit("}", 1)[-1]
                    for node in ET.fromstring(raw).iter()
                }
            except ET.ParseError:
                # Native Office objects can carry extension namespaces that
                # older XML parsers do not understand. The raw local-name
                # check keeps valid Morph/transition markup observable.
                local_names = set()
            has_transition = (
                "transition" in local_names
                or b":transition" in lowered
                or b"<transition" in lowered
            )
            has_morph = (
                "morph" in local_names
                or b":morph" in lowered
                or b"<morph" in lowered
            )
            transition_slides += int(has_transition)
            morph_slides += int(has_morph)
    if expected_slides is not None and len(slide_parts) != expected_slides:
        raise RuntimeError(
            f"PowerPoint verification found {len(slide_parts)} slides; expected {expected_slides}."
        )
    if empty_media:
        raise RuntimeError(f"PowerPoint contains empty media files: {', '.join(empty_media)}")
    return {
        "slide_count": len(slide_parts),
        "chart_count": len(chart_parts),
        "native_3d_model_count": len(model_parts),
        "native_3d_shape_count": model_shapes,
        "native_3d_slide_count": model_slides,
        "transition_slide_count": transition_slides,
        "morph_slide_count": morph_slides,
        "empty_media": empty_media,
        "bytes": path.stat().st_size,
    }


def _export_pdf_windows(pptx_path: Path, pdf_path: Path) -> None:
    import comtypes.client

    powerpoint = comtypes.client.CreateObject("PowerPoint.Application")
    powerpoint.Visible = 1
    presentation = None
    try:
        presentation = powerpoint.Presentations.Open(str(pptx_path.resolve()), WithWindow=False)
        presentation.ExportAsFixedFormat(str(pdf_path.resolve()), 2)
    finally:
        if presentation is not None:
            presentation.Close()
        powerpoint.Quit()


def _export_pdf_macos(pptx_path: Path, pdf_path: Path) -> None:
    script = """
on run argv
    set sourceFile to POSIX file (item 1 of argv)
    set outputFile to POSIX file (item 2 of argv)
    tell application "Microsoft PowerPoint"
        open sourceFile
        set thePresentation to active presentation
        save thePresentation in outputFile as save as PDF
        close thePresentation saving no
    end tell
end run
"""
    result = subprocess.run(
        ["osascript", "-e", script, str(pptx_path.resolve()), str(pdf_path.resolve())],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Microsoft PowerPoint PDF export failed.")


def export_pdf(pptx_path: Path, pdf_path: Path) -> tuple[Path | None, str | None]:
    system = platform.system()
    try:
        if system == "Windows":
            _export_pdf_windows(pptx_path, pdf_path)
        elif system == "Darwin" and Path("/Applications/Microsoft PowerPoint.app").exists():
            _export_pdf_macos(pptx_path, pdf_path)
        else:
            return None, "PDF export skipped because Microsoft PowerPoint is not available."
        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            return None, "Microsoft PowerPoint did not produce a PDF file."
        return pdf_path, None
    except Exception as exc:
        return None, f"PDF export was unavailable: {exc}"


def render_pdf(pdf_path: Path, preview_dir: Path) -> tuple[list[Path], str | None]:
    try:
        import fitz
    except ImportError:
        return [], "Rendered QA skipped because PyMuPDF is not installed."

    preview_dir.mkdir(parents=True, exist_ok=True)
    images: list[Path] = []
    try:
        document = fitz.open(pdf_path)
        for index, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
            output = preview_dir / f"slide-{index:02d}.png"
            pixmap.save(output)
            images.append(output)
        document.close()
        return images, None
    except Exception as exc:
        return [], f"Rendered QA failed: {exc}"


def create_contact_sheet(images: list[Path], output: Path) -> Path | None:
    if not images:
        return None
    try:
        from PIL import Image, ImageDraw

        opened = [Image.open(path).convert("RGB") for path in images]
        thumb_width = 320
        thumb_height = 180
        columns = min(4, max(1, len(opened)))
        rows = (len(opened) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * thumb_width, rows * (thumb_height + 24)), "white")
        draw = ImageDraw.Draw(sheet)
        for index, image in enumerate(opened):
            image.thumbnail((thumb_width, thumb_height))
            x = (index % columns) * thumb_width
            y = (index // columns) * (thumb_height + 24)
            sheet.paste(image, (x, y))
            draw.text((x + 8, y + thumb_height + 4), f"{index + 1:02d}", fill="black")
        output.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(output)
        for image in opened:
            image.close()
        return output
    except Exception:
        return None


def critique_renders(
    images: list[Path],
    contact_sheet: Path | None,
    topic: str,
    api_key: str,
) -> tuple[dict[str, Any], str | None]:
    if not images:
        return {}, None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        selected = [contact_sheet] if contact_sheet else []
        selected.extend(images[: min(12, len(images))])
        contents: list[Any] = [
            "Review these rendered slides as a presentation art director. "
            f"Topic: {topic}. Return JSON only with score (0-100), blocking_issues "
            "(array), weakest_slides (array of slide numbers), and summary. Treat "
            "clipping, collisions, unreadable labels, repeated layouts, broken chart "
            "geometry, and unverified brand-like marks as blocking issues."
        ]
        for path in selected:
            if path:
                contents.append(types.Part.from_bytes(data=Path(path).read_bytes(), mime_type="image/png"))
        response = client.models.generate_content(
            model=os.environ.get("PRESENTATION_QA_MODEL", "gemini-2.5-flash"),
            contents=contents,
            config={"response_mime_type": "application/json"},
        )
        result = json.loads(response.text)
        return result if isinstance(result, dict) else {}, None
    except Exception as exc:
        return {}, f"Visual critique was unavailable: {exc}"


def clean_preview_dir(path: Path) -> None:
    if path.exists() and path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
