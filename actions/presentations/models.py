"""Validated request and result models for the presentation action."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


VALID_MODES = {"auto", "create", "edit", "redesign", "extend"}
VALID_QUALITY = {"fast", "quality", "premium"}
VALID_APPEARANCES = {"auto", "light", "dark"}
VALID_TRANSITIONS = {"morph", "fade", "none"}
MIN_SLIDES = 3
MAX_SLIDES = 50


def _text(value: Any, default: str = "") -> str:
    return " ".join(str(value or default).split()).strip()


def _paths(value: Any) -> list[Path]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[Path] = []
    seen: set[str] = set()
    for raw in values:
        cleaned = str(raw or "").strip().strip('"').strip("'")
        if not cleaned:
            continue
        path = Path(cleaned).expanduser()
        key = str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _urls(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    for raw in values:
        url = str(raw or "").strip()
        if url and url not in result:
            result.append(url)
    return result


@dataclass
class PresentationRequest:
    topic: str
    title: str
    audience: str = "General professional audience"
    tone: str = "confident, concise, executive"
    theme: str = "jarvis_minimal"
    theme_explicit: bool = False
    appearance: str = "auto"
    transition: str = "morph"
    mode: str = "auto"
    quality: str = "quality"
    slide_count: int = 8
    slide_count_explicit: bool = False
    language: str = ""
    source_files: list[Path] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    template_file: Path | None = None
    model_source_file: Path | None = None
    use_native_3d: bool = False
    allow_web_research: bool = False
    export_pdf: bool = True
    include_speaker_notes: bool = False
    output_path: str = ""
    open_after_create: bool = False

    @classmethod
    def from_parameters(cls, parameters: dict[str, Any] | None) -> "PresentationRequest":
        p = dict(parameters or {})
        topic = _text(p.get("topic") or p.get("instructions") or p.get("description"))
        if not topic:
            raise ValueError("Tell me the presentation topic before I create the PowerPoint.")

        try:
            count = int(p.get("slide_count", 8) or 8)
        except (TypeError, ValueError):
            count = 8
        count = max(MIN_SLIDES, min(MAX_SLIDES, count))

        mode = _text(p.get("mode"), "auto").lower()
        quality = _text(p.get("quality"), "quality").lower()
        appearance = _text(p.get("appearance"), "auto").lower()
        transition = _text(p.get("transition"), "morph").lower()
        if mode not in VALID_MODES:
            mode = "auto"
        if quality not in VALID_QUALITY:
            quality = "quality"
        if appearance not in VALID_APPEARANCES:
            appearance = "auto"
        if transition not in VALID_TRANSITIONS:
            transition = "morph"

        files = _paths(p.get("source_files"))
        legacy_source = _paths(p.get("source_file"))
        for path in legacy_source:
            if path not in files:
                files.append(path)
        template_paths = _paths(p.get("template_file"))
        model_source_paths = _paths(p.get("model_source_file"))

        return cls(
            topic=topic[:1000],
            title=_text(p.get("title") or topic)[:140],
            audience=_text(p.get("audience"), "General professional audience")[:140],
            tone=_text(p.get("tone"), "confident, concise, executive")[:140],
            theme=_text(p.get("theme"), "jarvis_minimal").lower(),
            theme_explicit="theme" in p and bool(str(p.get("theme") or "").strip()),
            appearance=appearance,
            transition=transition,
            mode=mode,
            quality=quality,
            slide_count=count,
            slide_count_explicit="slide_count" in p and p.get("slide_count") not in (None, ""),
            language=_text(p.get("language"))[:80],
            source_files=files,
            source_urls=_urls(p.get("source_urls")),
            template_file=template_paths[0] if template_paths else None,
            model_source_file=model_source_paths[0] if model_source_paths else None,
            use_native_3d=(
                bool(p.get("use_native_3d", False))
                or ("3d" in topic.lower() and "model" in topic.lower())
                or ("three-dimensional" in topic.lower() and "model" in topic.lower())
            ),
            allow_web_research=bool(p.get("allow_web_research", False)),
            export_pdf=bool(p.get("export_pdf", True)),
            include_speaker_notes=bool(p.get("include_speaker_notes", False)),
            output_path=str(p.get("output_path") or "").strip(),
            open_after_create=bool(p.get("open_after_create", False)),
        )

    def resolved_mode(self) -> str:
        if self.mode != "auto":
            return self.mode
        instruction = self.topic.lower()
        has_pptx = bool(self.template_file) or any(path.suffix.lower() == ".pptx" for path in self.source_files)
        if has_pptx and any(word in instruction for word in ("edit", "change", "replace", "fix", "update")):
            return "edit"
        if has_pptx and any(word in instruction for word in ("extend", "append", "add slide")):
            return "extend"
        if has_pptx and any(word in instruction for word in ("redesign", "rebuild", "make better", "refresh")):
            return "redesign"
        return "redesign" if has_pptx else "create"

    def source_deck(self) -> Path | None:
        if self.template_file:
            return self.template_file
        return next((path for path in self.source_files if path.suffix.lower() == ".pptx"), None)

    def resolved_appearance(self) -> str:
        if self.appearance in {"light", "dark"}:
            return self.appearance
        request_text = f"{self.topic} {self.tone}".lower()
        dark_terms = ("dark", "black background", "midnight", "low-light", "cinematic")
        light_terms = ("light", "white background", "bright", "airy", "daylight")
        if any(term in request_text for term in dark_terms):
            return "dark"
        if any(term in request_text for term in light_terms):
            return "light"
        if self.use_native_3d or self.theme == "jarvis_minimal":
            return "dark"
        if self.theme_explicit and self.theme == "arc_reactor":
            return "dark"
        return "light"


@dataclass
class SourceRecord:
    label: str
    kind: str
    location: str
    text: str = ""
    media_path: Path | None = None
    provenance: str = "user-provided"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceBundle:
    records: list[SourceRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        blocks = []
        for index, record in enumerate(self.records, start=1):
            if record.text.strip():
                blocks.append(
                    f"[SOURCE {index}: {record.label} | {record.provenance}]\n{record.text.strip()}"
                )
        return "\n\n".join(blocks)

    @property
    def media_paths(self) -> list[Path]:
        return [record.media_path for record in self.records if record.media_path]

    @property
    def citations(self) -> list[str]:
        return [record.location for record in self.records]


@dataclass
class PresentationResult:
    pptx_path: Path
    slide_count: int
    mode: str
    quality: str
    pdf_path: Path | None = None
    warnings: list[str] = field(default_factory=list)
    qa: dict[str, Any] = field(default_factory=dict)

    @property
    def artifacts(self) -> list[str]:
        paths = [str(self.pptx_path)]
        if self.pdf_path:
            paths.append(str(self.pdf_path))
        return paths

    def __str__(self) -> str:
        pdf = f" PDF: {self.pdf_path}." if self.pdf_path else ""
        warning = f" Warnings: {'; '.join(self.warnings)}" if self.warnings else ""
        return (
            f"Created an editable {self.slide_count}-slide PowerPoint presentation: "
            f"{self.pptx_path}.{pdf}{warning}"
        )
