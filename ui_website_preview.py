"""Integrated website preview surface for the desktop operator UI."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from PyQt6.QtCore import (
    QCoreApplication, QEasingCurve, QParallelAnimationGroup,
    QPropertyAnimation, Qt, QUrl, pyqtSignal,
)
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QScrollArea,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

try:  # Optional at import time so the main UI retains a useful safe fallback.
    from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # pragma: no cover - depends on the local Qt installation
    QWebEnginePage = None
    QWebEngineSettings = None
    QWebEngineView = None


PERSONA_NAMES = {
    "jarvis": "JARVIS",
    "ultron": "ULTRON",
    "atlas": "ATLAS",
}

VIEWPORT_WIDTHS = {
    "desktop": None,
    "tablet": 820,
    "mobile": 390,
}


@dataclass(frozen=True)
class PreviewTarget:
    """A resolved local HTML document or web URL."""

    url: QUrl
    label: str
    local_path: Path | None = None


def _normalise_persona(mode: str | None) -> str:
    candidate = str(mode or "jarvis").strip().lower()
    return candidate if candidate in PERSONA_NAMES else "jarvis"


def _directory_entry(directory: Path) -> Path | None:
    preferred = (
        "index.html",
        "index.htm",
        "dist/index.html",
        "build/index.html",
        "public/index.html",
        "src/index.html",
    )
    for relative in preferred:
        candidate = directory / relative
        if candidate.is_file():
            return candidate

    html_files = sorted(
        path for path in directory.glob("*.htm*")
        if path.is_file() and path.suffix.lower() in {".html", ".htm"}
    )
    return html_files[0] if html_files else None


def resolve_preview_target(source: str | Path) -> PreviewTarget:
    """Resolve a URL, HTML document, or website directory for safe previewing."""

    raw = str(source or "").strip()
    if not raw:
        raise ValueError("No website was provided for preview.")

    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"}:
        return PreviewTarget(QUrl(raw), raw)

    if parsed.scheme == "file":
        raw = unquote(parsed.path)

    path = Path(raw).expanduser()
    if path.is_dir():
        entry = _directory_entry(path)
        if entry is None:
            raise ValueError(f"No HTML entry file was found in {path}.")
        path = entry

    if not path.is_file():
        raise ValueError(f"Website preview target does not exist: {path}")
    if path.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("Website previews require an HTML file, website folder, or web URL.")

    resolved = path.resolve()
    return PreviewTarget(QUrl.fromLocalFile(str(resolved)), resolved.name, resolved)


class WebsitePreviewWidget(QWidget):
    """Persona-aware embedded browser with responsive viewport controls."""

    close_requested = pyqtSignal()
    command_submitted = pyqtSignal(str)
    dock_changed = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("websitePreview")
        self.setAccessibleName("Integrated website preview")
        self._active_mode = "jarvis"
        self._creator_mode = "jarvis"
        self._target: PreviewTarget | None = None
        self._viewport = "desktop"
        self._graphics_quality = "medium"
        self._focus_mode = False
        self._docked = False
        self._dock_animation = None
        self._palette: dict[str, str] = {}
        self._decision_pages: list[QWidget] = []
        # Chromium aborts the process if QApplication was constructed without
        # argv[0], which some test and embedding hosts legitimately do.
        self._full_engine = bool(
            QWebEngineView is not None
            and QCoreApplication.arguments()
            and os.environ.get("QT_QPA_PLATFORM", "").lower() != "offscreen"
        )

        root = QVBoxLayout(self)
        self._root_layout = root
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        self._chrome_header = QWidget()
        self._chrome_header.setObjectName("websitePreviewChrome")
        header = QHBoxLayout(self._chrome_header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self._close_btn = QPushButton("RETURN TO CORE")
        self._close_btn.setAccessibleName("Close website preview and return to AI core")
        self._close_btn.clicked.connect(self.close_requested.emit)
        header.addWidget(self._close_btn)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        self._title = QLabel("WEBSITE PREVIEW")
        self._title.setFont(QFont("Arial", 10, QFont.Weight.DemiBold))
        self._source_label = QLabel("Waiting for a generated website")
        self._source_label.setFont(QFont("Courier New", 7))
        self._source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        title_col.addWidget(self._title)
        title_col.addWidget(self._source_label)
        header.addLayout(title_col, stretch=1)

        self._creator_label = QLabel("CREATED BY JARVIS")
        self._creator_label.setFont(QFont("Courier New", 7, QFont.Weight.DemiBold))
        self._creator_label.setAccessibleName("Website creator persona")
        header.addWidget(self._creator_label)

        self._reload_btn = QPushButton("RELOAD")
        self._reload_btn.setAccessibleName("Reload website preview")
        self._reload_btn.clicked.connect(self.reload)
        header.addWidget(self._reload_btn)

        self._external_btn = QPushButton("OPEN IN BROWSER")
        self._external_btn.setAccessibleName("Open website in the default browser")
        self._external_btn.clicked.connect(self.open_external)
        header.addWidget(self._external_btn)
        root.addWidget(self._chrome_header)

        self._viewport_bar = QWidget()
        self._viewport_bar.setObjectName("websiteViewportBar")
        viewport_row = QHBoxLayout(self._viewport_bar)
        viewport_row.setContentsMargins(0, 0, 0, 0)
        viewport_row.setSpacing(6)
        viewport_label = QLabel("VIEWPORT")
        viewport_label.setFont(QFont("Courier New", 7, QFont.Weight.DemiBold))
        viewport_row.addWidget(viewport_label)

        self._viewport_group = QButtonGroup(self)
        self._viewport_group.setExclusive(True)
        self._viewport_buttons: dict[str, QPushButton] = {}
        for key, label in (("desktop", "DESKTOP"), ("tablet", "TABLET"), ("mobile", "MOBILE")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setAccessibleName(f"Preview at {label.title()} width")
            button.clicked.connect(lambda _checked=False, name=key: self.set_viewport(name))
            self._viewport_group.addButton(button)
            self._viewport_buttons[key] = button
            viewport_row.addWidget(button)
        self._viewport_buttons["desktop"].setChecked(True)
        viewport_row.addStretch()

        self._engine_label = QLabel(
            "CHROMIUM ENGINE" if self._full_engine else "BASIC ENGINE · JAVASCRIPT UNAVAILABLE"
        )
        self._engine_label.setFont(QFont("Courier New", 7))
        viewport_row.addWidget(self._engine_label)
        root.addWidget(self._viewport_bar)

        self._workspace_body = QWidget()
        self._workspace_body.setObjectName("websiteWorkspaceBody")
        workspace_layout = QHBoxLayout(self._workspace_body)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(10)

        self._dock_panel = QFrame()
        self._dock_panel.setObjectName("websiteDockPanel")
        self._dock_panel.setMinimumWidth(0)
        self._dock_panel.setMaximumWidth(0)
        self._dock_panel.hide()
        dock_layout = QVBoxLayout(self._dock_panel)
        dock_layout.setContentsMargins(14, 16, 14, 14)
        dock_layout.setSpacing(8)
        dock_title = QLabel("PREVIEW")
        dock_title.setObjectName("dockTitle")
        dock_title.setFont(QFont("Arial", 10, QFont.Weight.DemiBold))
        dock_layout.addWidget(dock_title)
        dock_hint = QLabel("Choose a viewport")
        dock_hint.setObjectName("dockHint")
        dock_hint.setFont(QFont("Arial", 8))
        dock_layout.addWidget(dock_hint)

        self._dock_viewport_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("desktop", "COMPUTER"),
            ("tablet", "TABLET"),
            ("mobile", "PHONE"),
        ):
            button = QPushButton(label)
            button.setObjectName("dockControl")
            button.setCheckable(True)
            button.setAccessibleName(f"Preview in {label.title()} mode")
            button.clicked.connect(
                lambda _checked=False, name=key: self.set_viewport(name)
            )
            self._dock_viewport_buttons[key] = button
            dock_layout.addWidget(button)
        self._dock_viewport_buttons["desktop"].setChecked(True)

        dock_layout.addSpacing(6)
        self._dock_reload_btn = QPushButton("RELOAD")
        self._dock_reload_btn.setObjectName("dockControl")
        self._dock_reload_btn.clicked.connect(self.reload)
        dock_layout.addWidget(self._dock_reload_btn)
        self._dock_external_btn = QPushButton("OPEN IN BROWSER")
        self._dock_external_btn.setObjectName("dockControl")
        self._dock_external_btn.clicked.connect(self.open_external)
        dock_layout.addWidget(self._dock_external_btn)
        dock_layout.addStretch()
        dock_exit_hint = QLabel("Double-click the orb\nto save and close")
        dock_exit_hint.setObjectName("dockExitHint")
        dock_exit_hint.setWordWrap(True)
        dock_exit_hint.setFont(QFont("Arial", 8))
        dock_layout.addWidget(dock_exit_hint)
        self._dock_center_btn = QPushButton("CENTER PREVIEW")
        self._dock_center_btn.setObjectName("dockControl")
        self._dock_center_btn.clicked.connect(lambda: self.set_docked(False))
        dock_layout.addWidget(self._dock_center_btn)

        self._dock_opacity = QGraphicsOpacityEffect(self._dock_panel)
        self._dock_opacity.setOpacity(0.0)
        self._dock_panel.setGraphicsEffect(self._dock_opacity)
        workspace_layout.addWidget(self._dock_panel)

        self._browser_frame = QFrame()
        self._browser_frame.setObjectName("previewViewport")
        self._browser_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        frame_layout = QHBoxLayout(self._browser_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._content = QStackedWidget()
        self._content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        frame_layout.addWidget(self._content)

        self._empty = QLabel(
            "Generated websites appear here automatically.\n"
            "You can also preview an existing HTML file or local website folder."
        )
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setAccessibleName("Website preview empty state")
        self._content.addWidget(self._empty)

        # The Chromium process is deliberately lazy. Starting it with the main
        # UI would consume memory and GPU resources even if no site is opened.
        self._browser = None
        workspace_layout.addWidget(self._browser_frame, stretch=1)
        root.addWidget(self._workspace_body, stretch=1)

        self.refresh_theme("jarvis", {})
        self.set_graphics_quality("medium")

    def set_focus_mode(self, active: bool) -> None:
        """Remove preview chrome so the website becomes the complete workspace."""
        self._focus_mode = bool(active)
        self._chrome_header.setVisible(not self._focus_mode)
        self._viewport_bar.setVisible(not self._focus_mode)
        self._root_layout.setContentsMargins(
            0 if self._focus_mode else 12,
            0 if self._focus_mode else 10,
            0 if self._focus_mode else 12,
            0 if self._focus_mode else 12,
        )
        self._root_layout.setSpacing(0 if self._focus_mode else 8)
        if not self._focus_mode:
            self.set_docked(False, animated=False)
        self.refresh_theme(self._active_mode, self._palette)

    @property
    def docked(self) -> bool:
        return self._docked

    def set_docked(self, active: bool, *, animated: bool = True) -> None:
        """Reveal or hide the minimal side controls while preserving the preview."""
        active = bool(active)
        if active == self._docked and self._dock_panel.isVisible() == active:
            return
        self._docked = active
        if self._dock_animation is not None:
            self._dock_animation.stop()
        if active:
            self._dock_panel.show()
        start_width = self._dock_panel.maximumWidth()
        end_width = 196 if active else 0
        start_opacity = self._dock_opacity.opacity()
        end_opacity = 1.0 if active else 0.0
        if not animated:
            self._dock_panel.setMaximumWidth(end_width)
            self._dock_opacity.setOpacity(end_opacity)
            self._dock_panel.setVisible(active)
            self.dock_changed.emit(active)
            return

        group = QParallelAnimationGroup(self)
        width_animation = QPropertyAnimation(self._dock_panel, b"maximumWidth")
        width_animation.setDuration(210)
        width_animation.setStartValue(start_width)
        width_animation.setEndValue(end_width)
        width_animation.setEasingCurve(QEasingCurve.Type.OutQuart)
        opacity_animation = QPropertyAnimation(self._dock_opacity, b"opacity")
        opacity_animation.setDuration(170)
        opacity_animation.setStartValue(start_opacity)
        opacity_animation.setEndValue(end_opacity)
        opacity_animation.setEasingCurve(QEasingCurve.Type.OutQuart)
        group.addAnimation(width_animation)
        group.addAnimation(opacity_animation)
        if not active:
            group.finished.connect(self._dock_panel.hide)
        self._dock_animation = group
        group.start()
        self.dock_changed.emit(active)

    def show_building_state(self, build_id: str, creator_mode: str = "jarvis") -> None:
        page, layout = self._decision_shell(
            "Building the design directions",
            "The brief is being structured and checked. Open the assistant orb in the lower-left "
            "to continue the conversation while the workspace prepares.",
        )
        status = QLabel("BRIEF  ·  COMPONENTS  ·  THREE DIRECTIONS")
        status.setObjectName("optionMeta")
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        layout.addWidget(status)
        layout.addStretch()
        self._show_workspace_page(page, f"BUILD {build_id} · PREPARING", creator_mode)

    def _show_workspace_page(self, page: QWidget, source_label: str, creator_mode: str) -> None:
        self._clear_decision_pages()
        self._creator_mode = _normalise_persona(creator_mode)
        self._creator_label.setText(f"CREATED BY {PERSONA_NAMES[self._creator_mode]}")
        self._source_label.setText(source_label)
        self._source_label.setToolTip(source_label)
        self._external_btn.setEnabled(False)
        self._reload_btn.setEnabled(False)
        self._dock_external_btn.setEnabled(False)
        self._dock_reload_btn.setEnabled(False)
        self._content.addWidget(page)
        self._decision_pages.append(page)
        self._content.setCurrentWidget(page)
        self._style_decision_page(page)

    def _clear_decision_pages(self) -> None:
        for old_page in self._decision_pages:
            self._content.removeWidget(old_page)
            old_page.deleteLater()
        self._decision_pages.clear()

    def _decision_shell(self, heading: str, introduction: str) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setObjectName("websiteDecisionScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("websiteDecisionBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 30, 28, 34)
        layout.setSpacing(16)
        title = QLabel(heading)
        title.setObjectName("decisionHeading")
        title.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        title.setWordWrap(True)
        copy = QLabel(introduction)
        copy.setObjectName("decisionCopy")
        copy.setFont(QFont("Arial", 10))
        copy.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(copy)
        layout.addSpacing(8)
        scroll.setWidget(body)
        return scroll, layout

    def show_design_options(
        self,
        build_id: str,
        options: list[dict],
        creator_mode: str = "jarvis",
    ) -> None:
        """Show visual, responsive design directions before the user commits."""

        page, layout = self._decision_shell(
            "Choose a design direction",
            "Compare the actual composition, brand system, and responsive behavior. The selected direction "
            "will determine the site; JARVIS colors apply only to this workspace.",
        )
        directions = list(options or [])[:3]
        if not directions:
            layout.addWidget(QLabel("No usable design directions were generated."))
            self._show_workspace_page(page, f"BUILD {build_id} · DESIGN ERROR", creator_mode)
            return

        selection = {"index": 0}
        selector = QHBoxLayout()
        selector.setSpacing(8)
        selector_group = QButtonGroup(page)
        selector_group.setExclusive(True)
        selector_buttons: list[QPushButton] = []
        for index, option in enumerate(directions):
            option_id = str(option.get("id") or chr(65 + index)).upper()
            button = QPushButton(f"DIRECTION {option_id}")
            button.setObjectName("directionTab")
            button.setCheckable(True)
            button.setAccessibleName(f"Preview website design direction {option_id}")
            selector_group.addButton(button)
            selector.addWidget(button)
            selector_buttons.append(button)
        selector.addStretch()
        layout.addLayout(selector)

        comparison = QFrame()
        comparison.setObjectName("designOption")
        comparison_row = QHBoxLayout(comparison)
        comparison_row.setContentsMargins(12, 12, 16, 16)
        comparison_row.setSpacing(18)

        preview_col = QVBoxLayout()
        preview_col.setSpacing(8)
        preview_tools = QHBoxLayout()
        preview_label = QLabel("RESPONSIVE PREVIEW")
        preview_label.setObjectName("optionMeta")
        preview_tools.addWidget(preview_label)
        preview_tools.addStretch()
        preview_desktop = QPushButton("DESKTOP")
        preview_mobile = QPushButton("MOBILE")
        for control in (preview_desktop, preview_mobile):
            control.setObjectName("decisionSecondary")
            control.setCheckable(True)
            preview_tools.addWidget(control)
        preview_desktop.setChecked(True)
        preview_col.addLayout(preview_tools)
        direction_preview = QTextBrowser()
        direction_preview.setObjectName("directionPreview")
        direction_preview.setAccessibleName("Rendered website design direction")
        direction_preview.setOpenExternalLinks(False)
        direction_preview.setOpenLinks(False)
        direction_preview.setMinimumHeight(390)
        preview_col.addWidget(direction_preview, stretch=1)
        comparison_row.addLayout(preview_col, stretch=3)

        evidence = QVBoxLayout()
        evidence.setSpacing(9)
        direction_marker = QLabel("A")
        direction_marker.setObjectName("optionMarker")
        direction_marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        direction_marker.setFixedSize(38, 38)
        direction_name = QLabel()
        direction_name.setObjectName("optionName")
        direction_name.setFont(QFont("Arial", 13, QFont.Weight.DemiBold))
        direction_summary = QLabel()
        direction_summary.setObjectName("optionSummary")
        direction_summary.setWordWrap(True)
        composition = QLabel()
        composition.setObjectName("optionDetail")
        composition.setWordWrap(True)
        palette = QLabel()
        palette.setObjectName("optionMeta")
        palette.setWordWrap(True)
        typography = QLabel()
        typography.setObjectName("optionMeta")
        typography.setWordWrap(True)
        performance = QLabel()
        performance.setObjectName("optionMeta")
        choose = QPushButton("USE A")
        choose.setObjectName("decisionAction")
        evidence.addWidget(direction_marker)
        evidence.addWidget(direction_name)
        evidence.addWidget(direction_summary)
        evidence.addSpacing(6)
        evidence.addWidget(composition)
        evidence.addWidget(palette)
        evidence.addWidget(typography)
        evidence.addWidget(performance)
        evidence.addStretch()
        evidence.addWidget(choose)
        comparison_row.addLayout(evidence, stretch=1)
        layout.addWidget(comparison, stretch=1)

        def apply_direction(index: int) -> None:
            selection["index"] = index
            option = directions[index]
            option_id = str(option.get("id") or chr(65 + index)).upper()
            selector_buttons[index].setChecked(True)
            direction_marker.setText(option_id)
            direction_name.setText(str(option.get("name") or f"Direction {option_id}"))
            direction_summary.setText(str(option.get("summary") or ""))
            composition.setText(f"COMPOSITION\n{str(option.get('composition') or 'Purposeful page hierarchy')}")
            palette_values = option.get("palette", {})
            if isinstance(palette_values, dict):
                palette_text = "  ·  ".join(f"{key}: {value}" for key, value in list(palette_values.items())[:5])
            else:
                palette_text = "  ·  ".join(str(item) for item in list(palette_values or [])[:5])
            palette.setText("PALETTE\n" + palette_text)
            typography.setText("TYPE\n" + "  +  ".join(str(item) for item in option.get("typography", [])[:3]))
            performance.setText(f"PERFORMANCE · {str(option.get('performance') or 'balanced').upper()}")
            choose.setText(f"USE {option_id}")
            choose.setAccessibleName(f"Use website design option {option_id}")
            preview_path = Path(str(option.get("preview_path") or ""))
            if preview_path.is_file():
                direction_preview.setSource(QUrl.fromLocalFile(str(preview_path.resolve())))
            else:
                direction_preview.setHtml(
                    f"<h1>{direction_name.text()}</h1><p>{direction_summary.text()}</p>"
                )

        for index, button in enumerate(selector_buttons):
            button.clicked.connect(lambda _checked=False, selected=index: apply_direction(selected))
        preview_desktop.clicked.connect(lambda: (direction_preview.setMaximumWidth(16_777_215), preview_mobile.setChecked(False), preview_desktop.setChecked(True)))
        preview_mobile.clicked.connect(lambda: (direction_preview.setMaximumWidth(390), preview_desktop.setChecked(False), preview_mobile.setChecked(True)))
        choose.clicked.connect(
            lambda _checked=False, build=str(build_id): self.command_submitted.emit(
                f"Use website design option {str(directions[selection['index']].get('id') or chr(65 + selection['index'])).upper()} for build {build}"
            )
        )
        apply_direction(0)
        self._show_workspace_page(page, f"BUILD {build_id} · AWAITING DESIGN SELECTION", creator_mode)

    def show_dependency_approval(
        self,
        build_id: str,
        packages: list[str],
        creator_mode: str = "jarvis",
    ) -> None:
        """Show the one-time npm consent boundary inside the workspace."""

        page, layout = self._decision_shell(
            "Approve website packages",
            "These exact packages will be installed only inside this website. Package lifecycle "
            "scripts remain disabled. Cancel leaves the selected design saved without installing anything.",
        )
        package_frame = QFrame()
        package_frame.setObjectName("packageManifest")
        package_layout = QVBoxLayout(package_frame)
        package_layout.setContentsMargins(18, 14, 18, 14)
        package_layout.setSpacing(8)
        for package in packages:
            label = QLabel(str(package))
            label.setObjectName("packageName")
            label.setFont(QFont("Courier New", 9))
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            package_layout.addWidget(label)
        layout.addWidget(package_frame)
        notice = QLabel("INSTALL COMMAND · npm install --ignore-scripts --no-audit --no-fund")
        notice.setObjectName("optionMeta")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        controls = QHBoxLayout()
        controls.addStretch()
        cancel = QPushButton("CANCEL")
        cancel.setObjectName("decisionSecondary")
        cancel.setAccessibleName("Cancel website package installation")
        cancel.clicked.connect(
            lambda _checked=False, build=str(build_id):
            self.command_submitted.emit(f"Cancel website packages for build {build}")
        )
        approve = QPushButton("APPROVE & BUILD")
        approve.setObjectName("decisionAction")
        approve.setAccessibleName("Approve website packages and build")
        approve.clicked.connect(
            lambda _checked=False, build=str(build_id):
            self.command_submitted.emit(f"Approve website packages for build {build}")
        )
        controls.addWidget(cancel)
        controls.addWidget(approve)
        layout.addLayout(controls)
        layout.addStretch()
        self._show_workspace_page(page, f"BUILD {build_id} · PACKAGE APPROVAL", creator_mode)

    def _style_decision_page(self, page: QWidget) -> None:
        p = self._palette or {
            "DARK": "#00080F", "PANEL": "#000C18", "BORDER": "#0A2535",
            "BORDER_B": "#1A5C7A", "PRI": "#00C8FF", "PRI_GHO": "#00141A",
            "WHITE": "#E8F8FF", "TEXT_MED": "#3A9AB0", "TEXT_DIM": "#1E5A6A",
        }
        page.setStyleSheet(f"""
            QScrollArea#websiteDecisionScroll, QWidget#websiteDecisionBody {{ background: {p['DARK']}; border: none; }}
            QLabel#decisionHeading {{ color: {p['WHITE']}; background: transparent; }}
            QLabel#decisionCopy, QLabel#optionSummary {{ color: {p['TEXT_MED']}; background: transparent; }}
            QLabel#optionDetail, QLabel#optionMeta {{ color: {p['TEXT_DIM']}; background: transparent; }}
            QLabel#optionName, QLabel#packageName {{ color: {p['WHITE']}; background: transparent; }}
            QLabel#optionMarker {{ color: {p['PRI']}; background: {p['PRI_GHO']}; border: 1px solid {p['PRI']}; border-radius: 19px; }}
            QFrame#designOption, QFrame#packageManifest {{ background: {p['PANEL']}; border: 1px solid {p['BORDER']}; border-radius: 5px; }}
            QFrame#designOption:hover {{ border-color: {p['BORDER_B']}; }}
            QTextBrowser#directionPreview {{ background: {p['DARK']}; border: 1px solid {p['BORDER']}; border-radius: 3px; }}
            QPushButton#decisionAction, QPushButton#decisionSecondary, QPushButton#directionTab {{ min-height: 42px; padding: 0 14px; border-radius: 3px; }}
            QPushButton#decisionAction {{ color: {p['DARK']}; background: {p['PRI']}; border: 1px solid {p['PRI']}; }}
            QPushButton#decisionAction:hover, QPushButton#decisionAction:focus {{ color: {p['WHITE']}; background: {p['PRI_GHO']}; }}
            QPushButton#decisionSecondary, QPushButton#directionTab {{ color: {p['TEXT_MED']}; background: transparent; border: 1px solid {p['BORDER_B']}; }}
            QPushButton#decisionSecondary:hover, QPushButton#decisionSecondary:focus, QPushButton#directionTab:hover, QPushButton#directionTab:focus {{ color: {p['WHITE']}; border-color: {p['PRI']}; }}
            QPushButton#directionTab:checked {{ color: {p['WHITE']}; background: {p['PRI_GHO']}; border-color: {p['PRI']}; }}
        """)

    @property
    def target(self) -> PreviewTarget | None:
        return self._target

    @property
    def has_full_engine(self) -> bool:
        return self._full_engine

    def load_preview(self, source: str | Path, creator_mode: str = "jarvis") -> PreviewTarget:
        target = resolve_preview_target(source)
        self._clear_decision_pages()
        self._ensure_browser()
        self._target = target
        self._creator_mode = _normalise_persona(creator_mode)
        creator = PERSONA_NAMES[self._creator_mode]
        self._creator_label.setText(f"CREATED BY {creator}")
        self._source_label.setText(str(target.local_path or target.label))
        self._source_label.setToolTip(str(target.local_path or target.label))

        if self._full_engine:
            self._browser.setUrl(target.url)
        else:
            self._browser.setSource(target.url)
        self._content.setCurrentWidget(self._browser)
        self.set_preview_active(True)
        self._external_btn.setEnabled(True)
        self._reload_btn.setEnabled(True)
        self._dock_external_btn.setEnabled(True)
        self._dock_reload_btn.setEnabled(True)
        return target

    def _ensure_browser(self) -> None:
        if self._browser is not None:
            return
        if self._full_engine:
            try:
                self._browser = QWebEngineView()
                self._browser.loadFinished.connect(lambda _ok: self._apply_page_quality())
            except (RuntimeError, TypeError):
                self._full_engine = False
                self._engine_label.setText("BASIC ENGINE · JAVASCRIPT UNAVAILABLE")
        if self._browser is None:
            self._browser = QTextBrowser()
            self._browser.setOpenExternalLinks(False)
            self._browser.setOpenLinks(False)
        self._browser.setAccessibleName("Rendered website")
        self._content.addWidget(self._browser)
        self.set_graphics_quality(self._graphics_quality)

    def reload(self) -> None:
        if self._target is None:
            return
        if self._full_engine:
            self._browser.reload()
        else:
            self._browser.setSource(QUrl())
            self._browser.setSource(self._target.url)

    def open_external(self) -> bool:
        return bool(self._target and QDesktopServices.openUrl(self._target.url))

    def set_preview_active(self, active: bool) -> None:
        """Freeze site JavaScript and animation while the preview is hidden."""
        if not self._full_engine or self._browser is None or QWebEnginePage is None:
            return
        state = (
            QWebEnginePage.LifecycleState.Active
            if active else QWebEnginePage.LifecycleState.Frozen
        )
        self._browser.page().setLifecycleState(state)

    def set_viewport(self, viewport: str) -> None:
        viewport = viewport if viewport in VIEWPORT_WIDTHS else "desktop"
        self._viewport = viewport
        width = VIEWPORT_WIDTHS[viewport]
        if width is None:
            self._content.setMaximumWidth(16_777_215)
            self._content.setMinimumWidth(0)
        else:
            self._content.setMaximumWidth(width)
            self._content.setMinimumWidth(min(width, 320))
        self._viewport_buttons[viewport].setChecked(True)
        self._dock_viewport_buttons[viewport].setChecked(True)

    def set_graphics_quality(self, quality: str) -> None:
        """Reduce embedded-browser GPU cost on conservative graphics tiers."""

        allowed = {
            "very_low", "low", "medium_low", "medium",
            "high_low", "high", "ultra",
        }
        value = str(quality or "medium").strip().lower().replace(" ", "_")
        self._graphics_quality = value if value in allowed else "medium"
        if (
            QWebEngineSettings is None
            or not self._full_engine
            or self._browser is None
        ):
            return

        settings = self._browser.settings()
        webgl_enabled = self._graphics_quality not in {"very_low", "low", "medium_low"}
        canvas_enabled = self._graphics_quality not in {"very_low", "low"}
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.WebGLEnabled,
            webgl_enabled,
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled,
            canvas_enabled,
        )
        self._apply_page_quality()

    def _apply_page_quality(self) -> None:
        """Make quality tiers observable inside generated pages, not just the HUD."""
        if not self._full_engine or self._browser is None:
            return
        quality = self._graphics_quality
        if quality in {"very_low", "low"}:
            css = "*,*::before,*::after{animation:none!important;transition:none!important;filter:none!important;backdrop-filter:none!important;box-shadow:none!important}"
        elif quality == "medium_low":
            css = "*,*::before,*::after{animation:none!important;transition:none!important;filter:none!important;backdrop-filter:none!important}"
        elif quality == "medium":
            css = "*,*::before,*::after{backdrop-filter:none!important}"
        else:
            css = ""
        script = """
            (() => {
              const id = 'jarvis-quality-override';
              let node = document.getElementById(id);
              if (!node) {
                node = document.createElement('style');
                node.id = id;
                document.head.appendChild(node);
              }
              node.textContent = %s;
              document.documentElement.dataset.jarvisQuality = %s;
            })();
        """ % (repr(css), repr(quality))
        self._browser.page().runJavaScript(script)

    def refresh_theme(self, mode: str, palette: dict[str, str]) -> None:
        self._active_mode = _normalise_persona(mode)
        defaults = {
            "BG": "#000306",
            "DARK": "#00080F",
            "PANEL": "#000C18",
            "BORDER": "#0A2535",
            "BORDER_B": "#1A5C7A",
            "PRI": "#00C8FF",
            "PRI_GHO": "#00141A",
            "WHITE": "#E8F8FF",
            "TEXT_MED": "#3A9AB0",
            "TEXT_DIM": "#1E5A6A",
        }
        defaults.update({key: value for key, value in (palette or {}).items() if value})
        self._palette = defaults
        p = defaults
        active_name = PERSONA_NAMES[self._active_mode]
        self._title.setText(f"{active_name} · WEBSITE PREVIEW")

        self.setStyleSheet(f"QWidget#websitePreview {{ background: {p['BG']}; }}")
        frame_border = "none" if self._focus_mode else f"1px solid {p['BORDER_B']}"
        frame_radius = "0px" if self._focus_mode else "5px"
        self._browser_frame.setStyleSheet(f"""
            QFrame#previewViewport {{
                background: {p['DARK']};
                border: {frame_border};
                border-radius: {frame_radius};
            }}
        """)
        self._title.setStyleSheet(f"color: {p['WHITE']}; background: transparent;")
        self._source_label.setStyleSheet(f"color: {p['TEXT_MED']}; background: transparent;")
        self._creator_label.setStyleSheet(
            f"color: {p['PRI']}; background: {p['PRI_GHO']}; border: 1px solid {p['BORDER_B']}; "
            "border-radius: 4px; padding: 5px 8px; letter-spacing: 1px;"
        )
        self._engine_label.setStyleSheet(f"color: {p['TEXT_DIM']}; background: transparent;")
        self._empty.setStyleSheet(f"color: {p['TEXT_MED']}; background: {p['DARK']};")
        self._dock_panel.setStyleSheet(f"""
            QFrame#websiteDockPanel {{
                background: {p['PANEL']}; border: 1px solid {p['BORDER']};
                border-radius: 5px;
            }}
            QLabel#dockTitle {{ color: {p['WHITE']}; background: transparent; }}
            QLabel#dockHint, QLabel#dockExitHint {{ color: {p['TEXT_DIM']}; background: transparent; }}
        """)

        button_style = f"""
            QPushButton {{
                color: {p['TEXT_MED']}; background: {p['DARK']};
                border: 1px solid {p['BORDER']}; border-radius: 4px;
                min-height: 27px; padding: 0 9px;
            }}
            QPushButton:hover, QPushButton:focus {{
                color: {p['WHITE']}; border-color: {p['PRI']};
            }}
            QPushButton:pressed, QPushButton:checked {{
                color: {p['WHITE']}; background: {p['PRI_GHO']}; border-color: {p['PRI']};
            }}
            QPushButton:disabled {{ color: {p['TEXT_DIM']}; border-color: {p['BORDER']}; }}
        """
        for button in (
            self._close_btn,
            self._reload_btn,
            self._external_btn,
            *self._viewport_buttons.values(),
            *self._dock_viewport_buttons.values(),
            self._dock_reload_btn,
            self._dock_external_btn,
            self._dock_center_btn,
        ):
            button.setStyleSheet(button_style)
        for page in self._decision_pages:
            self._style_decision_page(page)


__all__ = [
    "PreviewTarget",
    "VIEWPORT_WIDTHS",
    "WebsitePreviewWidget",
    "resolve_preview_target",
]
