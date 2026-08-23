import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QWidget

import ui
from core.persona_modes import (
    MODE_ACCENTS,
    MODE_DESCRIPTIONS,
    MODE_ORDER,
    MODE_SYSTEM_INSTRUCTIONS,
    MODE_VOICES,
    activation_mode,
)
from main import JarvisLive


class _Client:
    def __init__(self):
        self.on_text_command = None
        self.on_mode_change = None
        self.current_mode = "jarvis"
        self.current_file = None
        self._voice_combo = None
        self.muted = False
        self.events = []

    def activate_mode(self, mode):
        self.current_mode = mode
        self.events.append(("mode", mode))

    def write_log(self, text):
        self.events.append(("log", text))

    def set_state(self, _state):
        self.events.append(("state", _state))

    def sync_voice_display(self, _voice):
        self.events.append(("voice", _voice))

    def clear_subtitle(self):
        self.events.append(("subtitle", "clear"))

    def set_mode_switching(self, switching, target_mode):
        self.events.append(("switching", switching, target_mode))

    def stop_audio_playback(self):
        self.events.append(("audio", "reset"))


class PersonaModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_activation_phrases_are_local_and_exact(self):
        self.assertEqual(activation_mode("Activate serious mode!"), "ultron")
        self.assertEqual(activation_mode("Activate the portal control."), "atlas")
        self.assertEqual(activation_mode("Jarvis, switch to Ultron now"), "ultron")
        self.assertEqual(activation_mode("Hey Jarvis, please switch to Atlas"), "atlas")
        self.assertEqual(activation_mode("return to jarvis"), "jarvis")
        self.assertIsNone(activation_mode("Jarvis, do not switch to Ultron"))
        self.assertIsNone(activation_mode("make it serious"))

    def test_only_three_operational_palettes_remain(self):
        self.assertEqual(ui.ThemeManager.theme_names(), ["jarvis", "ultron", "atlas"])
        ui.ThemeManager.set_theme("ultron")
        self.assertEqual(ui.C.PRI, "#ff2244")
        ui.ThemeManager.set_theme("atlas")
        self.assertEqual(ui.C.PRI, "#a855f7")
        ui.ThemeManager.set_theme("jarvis")

    def test_persona_selector_uses_equal_cards_with_only_persona_identity(self):
        selector = ui.PersonaSelectorOverlay(first_boot=True)
        self.addCleanup(selector.deleteLater)

        self.assertEqual(tuple(selector._buttons), MODE_ORDER)
        self.assertNotIn("CANCEL", [button.text() for button in selector.findChildren(QPushButton)])
        sizes = {(button.width(), button.height()) for button in selector._buttons.values()}
        self.assertEqual(len(sizes), 1)
        for mode, button in selector._buttons.items():
            self.assertIn(MODE_DESCRIPTIONS[mode], button.accessibleName())
            self.assertIn(MODE_ACCENTS[mode], button.styleSheet().lower())

    def test_first_boot_persona_click_emits_choice_and_locks_all_cards(self):
        selector = ui.PersonaSelectorOverlay(first_boot=True)
        self.addCleanup(selector.deleteLater)
        selected = []
        selector.selected.connect(selected.append)

        selector._buttons["atlas"].click()

        self.assertEqual(selected, ["atlas"])
        self.assertTrue(all(not button.isEnabled() for button in selector._buttons.values()))

    def test_persona_selection_persists_without_erasing_other_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Path(temp_dir) / "settings.json"
            settings.write_text('{"graphics_quality":"high","theme":"legacy"}', encoding="utf-8")
            with patch.object(ui, "UI_SETTINGS_FILE", settings):
                self.assertEqual(ui._save_persona_selection("ATLAS"), "atlas")
                saved = __import__("json").loads(settings.read_text(encoding="utf-8"))
                self.assertEqual(saved["graphics_quality"], "high")
                self.assertEqual(saved["active_mode"], "atlas")
                self.assertTrue(saved["persona_onboarding_completed"])
                self.assertNotIn("theme", saved)

    def test_explicit_persona_click_forces_one_colour_transition(self):
        host = QMainWindow()
        host.setCentralWidget(QWidget(host))
        host._mode_switch_in_progress = False
        host._persona_overlay = None
        host._show_persona_selector = ui.MainWindow._show_persona_selector.__get__(host)
        host._close_persona_selector = ui.MainWindow._close_persona_selector.__get__(host)
        host._on_persona_selected = ui.MainWindow._on_persona_selected.__get__(host)
        host._activate_mode = MagicMock()
        host._show_voice_select_then_name = MagicMock()
        self.addCleanup(host.deleteLater)

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            ui, "UI_SETTINGS_FILE", Path(temp_dir) / "settings.json"
        ), patch.object(ui.QTimer, "singleShot"):
            host._show_persona_selector(first_boot=True)
            selector = host._persona_overlay
            selector._buttons["jarvis"].click()

        host._activate_mode.assert_called_once_with(
            "jarvis",
            notify_engine=True,
            transition=True,
            force_transition=True,
        )
        self.assertIsNone(host._persona_overlay)

    def test_transition_profiles_use_the_persona_accent_colours(self):
        for mode in MODE_ORDER:
            rgb = ui.ModeTransitionOverlay._PROFILES[mode]["accent"]
            self.assertEqual(ui.QColor(*rgb).name(), MODE_ACCENTS[mode])

    def test_transition_choreography_is_identical_for_all_personas(self):
        structural_keys = ("title", "tear", "scan_step", "smooth")
        structures = {
            tuple(ui.ModeTransitionOverlay._PROFILES[mode][key] for key in structural_keys)
            for mode in MODE_ORDER
        }
        self.assertEqual(len(structures), 1)

    def test_mode_voices_are_distinct_and_fixed(self):
        client = _Client()
        engine = JarvisLive(client, "puck")
        for mode, voice in MODE_VOICES.items():
            engine.persona_mode = mode
            self.assertEqual(engine._get_current_voice(), voice)
        engine.persona_mode = "jarvis"
        self.assertEqual(engine._get_current_voice(), "puck")
        self.assertEqual(len({engine._get_current_voice(), *MODE_VOICES.values()}), 3)
        self.assertEqual(MODE_VOICES["atlas"], "aoede")
        self.assertIn("calm feminine voice", MODE_SYSTEM_INSTRUCTIONS["atlas"])

    def test_settings_has_no_theme_tab(self):
        overlay = ui.SettingsOverlay(current_graphics="medium")
        self.addCleanup(overlay.deleteLater)
        self.assertEqual(overlay._s_tab_names, ["IDENTITY", "GRAPHICS"])

    def test_mode_button_stays_locked_until_handoff_completes(self):
        host = type("Host", (), {})()
        host._active_mode = "atlas"
        host._mode_switch_in_progress = False
        host._theme_btn = QPushButton()
        host._update_theme_btn = ui.MainWindow._update_theme_btn.__get__(host)
        host._set_mode_switching_ui = ui.MainWindow._set_mode_switching_ui.__get__(host)
        self.addCleanup(host._theme_btn.deleteLater)

        host._set_mode_switching_ui(True, "atlas")
        self.assertFalse(host._theme_btn.isEnabled())
        self.assertEqual(host._theme_btn.text(), "SWITCHING  ·  ATLAS")
        host._set_mode_switching_ui(False, "atlas")
        self.assertTrue(host._theme_btn.isEnabled())
        self.assertEqual(host._theme_btn.text(), "SWITCH MODE  ·  ATLAS")

    def test_deleted_transition_reference_cannot_crash_next_switch(self):
        host = QMainWindow()
        host.setCentralWidget(QWidget(host))
        host._show_mode_transition = ui.MainWindow._show_mode_transition.__get__(host)
        host._clear_mode_transition = ui.MainWindow._clear_mode_transition.__get__(host)

        stale = ui.ModeTransitionOverlay("ultron", host.centralWidget())
        stale.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertTrue(sip.isdeleted(stale))

        # Recreate the reported state: a live Python wrapper around an already
        # deleted Qt object. Showing the next transition must replace it safely.
        host._mode_transition = stale
        host._show_mode_transition("atlas")
        self.assertFalse(sip.isdeleted(host._mode_transition))
        self.assertEqual(host._mode_transition.mode, "atlas")

        modes = ("jarvis", "ultron", "atlas")
        for index in range(60):
            previous = host._mode_transition
            previous.close()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.assertTrue(sip.isdeleted(previous))
            host._show_mode_transition(modes[index % len(modes)])
            self.assertFalse(sip.isdeleted(host._mode_transition))

        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_creator_mark_restores_itself(self):
        host = type("Host", (), {})()
        host._style_maker_signature = ui.MainWindow._style_maker_signature.__get__(host)
        host._build_maker_signature = ui.MainWindow._build_maker_signature.__get__(host)
        host._enforce_creator_mark = ui.MainWindow._enforce_creator_mark.__get__(host)
        strip = host._build_maker_signature()
        self.addCleanup(strip.deleteLater)
        host._maker_signature_lbl.setText("removed")
        host._maker_signature_lbl.hide()
        host._enforce_creator_mark()
        self.assertEqual(host._maker_signature_lbl.text(), ui.CREATOR_MARK)
        self.assertFalse(host._maker_signature_lbl.isHidden())

    def test_saved_mode_replaces_legacy_theme_setting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Path(temp_dir) / "settings.json"
            settings.write_text('{"theme":"platinum"}', encoding="utf-8")
            with patch.object(ui, "UI_SETTINGS_FILE", settings):
                original = ui.ThemeManager.current_name()
                try:
                    ui.ThemeManager.set_theme("atlas")
                    data = ui._read_ui_settings()
                    data.pop("theme", None)
                    data["active_mode"] = "atlas"
                    settings.write_text(__import__("json").dumps(data), encoding="utf-8")
                    self.assertEqual(ui._read_ui_settings(), {"active_mode": "atlas"})
                finally:
                    ui.ThemeManager.set_theme(original)


class PersonaHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_handoff_silences_old_session_and_rejects_overlap(self):
        class Session:
            def __init__(self):
                self.closed = False

            async def close(self):
                self.closed = True

        class PlaybackStream:
            def __init__(self):
                self.aborted = False

            def abort(self):
                self.aborted = True

        client = _Client()
        engine = JarvisLive(client, "puck")
        engine._loop = asyncio.get_running_loop()
        engine.session = Session()
        engine.audio_in_queue = asyncio.Queue()
        engine.audio_in_queue.put_nowait(b"old persona audio")
        engine.out_queue = asyncio.Queue(maxsize=10)
        engine.out_queue.put_nowait({"data": b"mic", "mime_type": "audio/pcm"})
        engine._session_stop_event = asyncio.Event()
        engine._playback_stream = PlaybackStream()

        self.assertTrue(engine.update_mode("atlas"))
        self.assertFalse(engine.update_mode("ultron"))
        await asyncio.sleep(0.05)

        self.assertTrue(engine._mode_switching.is_set())
        self.assertTrue(engine._session_stop_event.is_set())
        self.assertTrue(engine.audio_in_queue.empty())
        self.assertTrue(engine.session.closed)
        self.assertTrue(engine._playback_stream.aborted)
        self.assertEqual(client.events[0], ("audio", "reset"))
        self.assertIn(("switching", True, "atlas"), client.events)
        self.assertFalse(await engine.send_text("old persona must not answer"))
        self.assertFalse(await engine.send_audio_chunk(b"voice"))

        engine._complete_mode_handoff()
        self.assertFalse(engine._mode_switching.is_set())
        self.assertIn(("switching", False, "atlas"), client.events)
        self.assertIn(("voice", "aoede"), client.events)

    async def test_live_transcript_switches_before_old_audio_is_queued(self):
        class Session:
            def __init__(self, response):
                self.response = response
                self.closed = False

            async def receive(self):
                yield self.response

            async def close(self):
                self.closed = True

        server_content = SimpleNamespace(
            input_transcription=SimpleNamespace(text="Jarvis, switch to Ultron now"),
            output_transcription=None,
            turn_complete=False,
        )
        response = SimpleNamespace(server_content=server_content, tool_call=None)
        client = _Client()
        engine = JarvisLive(client, "puck")
        engine._loop = asyncio.get_running_loop()
        engine.session = Session(response)
        engine.audio_in_queue = asyncio.Queue()
        engine.out_queue = asyncio.Queue(maxsize=10)
        engine._turn_done_event = asyncio.Event()
        engine._session_stop_event = asyncio.Event()

        await engine._receive_audio()
        await asyncio.sleep(0.05)

        self.assertEqual(engine.persona_mode, "ultron")
        self.assertTrue(engine.audio_in_queue.empty())
        self.assertTrue(engine.session.closed)
        self.assertIn(("audio", "reset"), client.events)
        self.assertIn(("switching", True, "ultron"), client.events)
        engine._complete_mode_handoff()


if __name__ == "__main__":
    unittest.main()
