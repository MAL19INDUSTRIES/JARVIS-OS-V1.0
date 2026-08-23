import os
import tempfile
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QStackedWidget

from actions import code_helper, dev_agent
import ui
from ui_website_preview import WebsitePreviewWidget, resolve_preview_target


class _PreviewClient:
    def __init__(self):
        self.calls = []

    def show_website_preview(self, source, persona):
        self.calls.append((source, persona))


class WebsitePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_directory_resolves_saved_index_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            site = Path(temp_dir)
            index = site / "index.html"
            index.write_text("<h1>Local site</h1>", encoding="utf-8")

            target = resolve_preview_target(site)

            self.assertEqual(target.local_path, index.resolve())
            self.assertTrue(target.url.isLocalFile())

    def test_preview_keeps_creator_when_active_persona_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index = Path(temp_dir) / "index.html"
            index.write_text("<h1>Portal</h1>", encoding="utf-8")
            preview = WebsitePreviewWidget()
            self.addCleanup(preview.deleteLater)

            preview.load_preview(index, "ultron")
            preview.refresh_theme("atlas", {"PRI": "#a855f7"})

            self.assertEqual(preview.target.local_path, index.resolve())
            self.assertEqual(preview._creator_label.text(), "CREATED BY ULTRON")
            self.assertEqual(preview._title.text(), "ATLAS · WEBSITE PREVIEW")

    def test_preview_has_responsive_viewport_controls(self):
        preview = WebsitePreviewWidget()
        self.addCleanup(preview.deleteLater)
        self.assertIsNone(preview._browser)
        preview.set_viewport("mobile")
        self.assertEqual(preview._viewport, "mobile")
        self.assertEqual(preview._content.maximumWidth(), 390)
        preview.set_viewport("desktop")
        self.assertGreater(preview._content.maximumWidth(), 10_000)

    def test_focus_mode_removes_all_preview_chrome(self):
        preview = WebsitePreviewWidget()
        self.addCleanup(preview.deleteLater)
        preview.set_focus_mode(True)
        self.assertTrue(preview._chrome_header.isHidden())
        self.assertTrue(preview._viewport_bar.isHidden())
        self.assertEqual(preview._root_layout.contentsMargins().left(), 0)
        preview.set_focus_mode(False)
        self.assertFalse(preview._chrome_header.isHidden())

    def test_focus_preview_docks_with_minimal_device_controls(self):
        preview = WebsitePreviewWidget()
        self.addCleanup(preview.deleteLater)
        preview.set_focus_mode(True)
        preview.set_docked(True, animated=False)
        self.assertTrue(preview.docked)
        self.assertFalse(preview._dock_panel.isHidden())
        self.assertEqual(preview._dock_panel.maximumWidth(), 196)
        preview._dock_viewport_buttons["tablet"].click()
        self.assertEqual(preview._viewport, "tablet")
        self.assertEqual(preview._content.maximumWidth(), 820)
        preview.set_docked(False, animated=False)
        self.assertTrue(preview._dock_panel.isHidden())

    def test_orb_double_click_requests_project_exit(self):
        orb = ui.WebsiteOrbControl("missing.png")
        self.addCleanup(orb.deleteLater)
        requested = []
        orb.exit_requested.connect(lambda: requested.append(True))
        orb.show()
        QTest.mouseDClick(orb, ui.Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(requested, [True])

    def test_website_focus_leaves_only_orb_until_chat_is_opened(self):
        window = ui.MainWindow("missing.png")
        window.show()
        self.app.processEvents()
        try:
            window._enter_website_focus("build-focus", "atlas")
            self.app.processEvents()
            self.assertTrue(window._website_focus_active)
            for widget in (
                window._header, window._left_panel, window._right_panel,
                window._command_bar, window._tool_progress, window._focus_dialogue,
                window._subtitle, window._maker_signature,
            ):
                self.assertFalse(widget.isVisible())
            self.assertIs(window._core_stack.currentWidget(), window._website_preview)
            self.assertTrue(window._website_orb.isVisible())
            self.assertFalse(window._website_mini_chat.isVisible())
            self.assertLess(window._website_orb.x(), window.centralWidget().width() // 2)
            self.assertGreater(window._website_orb.y(), window.centralWidget().height() // 2)

            window._website_orb.set_subtitle("The tablet preview is ready.")
            self.assertTrue(window._website_orb._subtitle.isVisible())
            self.assertIn("tablet preview", window._website_orb._subtitle.text())

            self.assertTrue(window._handle_ui_command("dock_website_preview"))
            self.assertTrue(window._website_preview.docked)
            self.assertTrue(window._handle_ui_command("website_tablet_view"))
            self.assertEqual(window._website_preview._viewport, "tablet")
            window._send("center the preview")
            self.assertFalse(window._website_preview.docked)

            commands = []
            window._website_mini_chat.command_submitted.connect(commands.append)
            window._toggle_website_mini_chat()
            self.app.processEvents()
            self.assertTrue(window._website_mini_chat.isVisible())
            self.assertEqual(window._website_mini_chat.findChildren(ui.QPushButton), [])
            window._website_mini_chat._input.setText("Use option B")
            window._website_mini_chat._input.returnPressed.emit()
            self.assertEqual(commands, ["Use option B"])

            window._request_website_focus_exit()
            self.app.processEvents()
            self.assertTrue(window._website_exit_confirm.isVisible())
            self.assertTrue(window._website_focus_active)
            window._cancel_website_focus_exit()
            self.assertFalse(window._website_exit_confirm.isVisible())

            window._exit_website_focus()
            self.assertFalse(window._website_focus_active)
            self.assertFalse(window._website_orb.isVisible())
            self.assertIs(window._core_stack.currentWidget(), window.hud)
        finally:
            window._force_quit = True
            window.close()

    def test_code_helper_saves_automatic_html_under_local_documents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original = code_helper.WEBSITES_DIR
            code_helper.WEBSITES_DIR = Path(temp_dir) / "JARVIS Websites"
            try:
                path = code_helper._resolve_save_path("", "html")
            finally:
                code_helper.WEBSITES_DIR = original
            self.assertEqual(
                path,
                Path(temp_dir) / "JARVIS Websites" / "jarvis_website" / "index.html",
            )

    def test_dev_agent_finds_and_announces_local_website_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            entry = project / "index.html"
            entry.write_text("<h1>Site</h1>", encoding="utf-8")
            files = [
                {"path": "styles.css"},
                {"path": "index.html"},
            ]
            client = _PreviewClient()

            found = dev_agent._notify_website_preview(
                client, project, files, "index.html", "ATLAS"
            )

            self.assertEqual(found, entry.resolve())
            self.assertEqual(client.calls, [(str(entry.resolve()), "ATLAS")])
            self.assertTrue(dev_agent._is_website_plan(files, "index.html"))

    def test_integrated_preview_pauses_hud_and_survives_persona_style_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index = Path(temp_dir) / "index.html"
            index.write_text("<h1>Local</h1>", encoding="utf-8")
            stack = QStackedWidget()
            hud = ui.HudCanvas("missing.png")
            activity = ui.AIActivityCanvas()
            preview = WebsitePreviewWidget()
            stack.addWidget(hud)
            stack.addWidget(preview)
            host = SimpleNamespace(
                _active_mode="atlas",
                _graphics_quality="low",
                _website_preview=preview,
                _core_stack=stack,
                hud=hud,
                _ai_canvas=activity,
            )
            host._preview_palette = ui.MainWindow._preview_palette
            host._show_website_preview = MethodType(ui.MainWindow._show_website_preview, host)
            try:
                self.assertTrue(host._show_website_preview(str(index), "ultron"))
                self.assertIs(stack.currentWidget(), preview)
                self.assertFalse(hud._tmr.isActive())
                self.assertEqual(preview._title.text(), "ATLAS · WEBSITE PREVIEW")
                self.assertEqual(preview._creator_label.text(), "CREATED BY ULTRON")
            finally:
                hud._tmr.stop()
                activity._tmr.stop()
                stack.deleteLater()


if __name__ == "__main__":
    unittest.main()
