import json
import inspect
import os
import tempfile
import unittest
import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import ui


class _NoSecrets:
    def get(self, _key):
        return None


class _MetricsSnapshot:
    def snapshot(self):
        return {"cpu": 1.0, "mem": 1.0, "net": 0.0, "gpu": -1.0, "tmp": -1.0}


class UIRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.temp_dir = tempfile.TemporaryDirectory()
        temp_path = Path(cls.temp_dir.name)

        cls.original_update_metrics = staticmethod(ui.MainWindow._update_metrics)
        cls.patchers = [
            patch.object(ui, "UI_SETTINGS_FILE", temp_path / "ui_settings.json"),
            patch.object(ui, "LAYOUT_SETTINGS_FILE", temp_path / "layout_settings.json"),
            patch.object(ui, "API_FILE", temp_path / "api_keys.json"),
            patch.object(ui, "get_secret_store", return_value=_NoSecrets()),
            patch.object(ui.MainWindow, "_setup_system_tray", lambda self: None),
            patch.object(ui.MainWindow, "_update_metrics", lambda self: None),
            patch.object(ui.MainWindow, "_restore_detached_panels", lambda self: None),
            patch.object(ui.MainWindow, "_start_layout_autosave", lambda self: None),
            patch.object(ui.MainWindow, "_start_auto_graphics_detection", lambda self: None),
        ]
        for patcher in cls.patchers:
            patcher.start()

        ui.UI_SETTINGS_FILE.write_text(
            json.dumps({"intro_completed": True, "intro_every_launch": False}),
            encoding="utf-8",
        )
        cls.window = ui.MainWindow("face.png")
        cls.window.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.window.hide()
        cls.window.deleteLater()
        cls.app.processEvents()
        for patcher in reversed(cls.patchers):
            patcher.stop()
        cls.temp_dir.cleanup()

    def test_every_mode_has_a_complete_valid_palette(self):
        required = set(ui.ThemeManager._COLOR_KEYS)
        for name, theme in ui.ThemeManager._THEMES.items():
            self.assertFalse(required - set(theme), name)
            for key in required:
                self.assertRegex(theme[key], r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")

    def test_mode_change_updates_existing_widget_styles(self):
        ui.ThemeManager.set_theme("jarvis")
        ui.ThemeManager.set_theme("ultron")
        self.app.processEvents()
        self.assertEqual(ui.C.BG, "#080203")
        self.assertIn("#080203", self.window.centralWidget().styleSheet().lower())

    def test_graphics_setting_preserves_saved_mode(self):
        ui.UI_SETTINGS_FILE.write_text(
            json.dumps({"graphics_quality": "low", "active_mode": "atlas"}),
            encoding="utf-8",
        )
        ui.set_graphics_quality("high")
        saved = json.loads(ui.UI_SETTINGS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(saved, {
            "graphics_quality": "high",
            "graphics_quality_mode": "manual",
            "active_mode": "atlas",
        })

    def test_legacy_graphics_setting_migrates_to_auto_until_overridden(self):
        ui.UI_SETTINGS_FILE.write_text(
            json.dumps({"graphics_quality": "high"}),
            encoding="utf-8",
        )
        self.assertEqual(ui.get_graphics_mode(), "auto")
        ui.set_graphics_quality("low")
        self.assertEqual(ui.get_graphics_mode(), "manual")
        self.assertEqual(ui.get_graphics_quality(), "low")

    def test_auto_graphics_result_is_saved_with_device_report(self):
        report = {
            "quality": "medium",
            "fingerprint": "device-123",
            "reason": "16 GB RAM · 4-core CPU · Integrated GPU",
        }
        self.assertEqual(ui.save_auto_graphics_result(report), "medium")
        saved = json.loads(ui.UI_SETTINGS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(saved["graphics_quality_mode"], "auto")
        self.assertEqual(saved["graphics_quality"], "medium")
        self.assertEqual(saved["graphics_auto_fingerprint"], "device-123")
        self.assertEqual(saved["graphics_auto_report"], report)

    def test_manual_graphics_choice_wins_over_late_auto_result(self):
        ui.set_graphics_quality("high")
        with patch.object(ui, "save_auto_graphics_result") as save_result, \
             patch.object(self.window, "_apply_graphics_quality_live") as apply_live:
            self.window._finish_auto_graphics_detection({"quality": "low"})
        save_result.assert_not_called()
        apply_live.assert_not_called()
        self.assertEqual(ui.get_graphics_quality(), "high")

    def test_graphics_settings_include_auto_choice(self):
        overlay = ui.SettingsOverlay(
            current_graphics="medium",
            current_graphics_mode="auto",
        )
        self.assertEqual(set(overlay._graphics_btns), {
            "auto", "very_low", "low", "medium_low", "medium",
            "high_low", "high", "ultra",
        })
        overlay.set_auto_graphics_result("high", "Detected discrete graphics")
        self.assertIn("HIGH", overlay._graphics_btns["auto"]._fps.text())
        self.assertIn("Detected discrete graphics", overlay._graphics_note.text())
        overlay.deleteLater()

    def test_explicit_self_quit_commands_route_to_jarvis(self):
        for command in (
            "quit JARVIS",
            "shut yourself down",
            "JARVIS, turn yourself off",
            "go offline JARVIS",
        ):
            self.assertEqual(ui.route_jarvis_ui_command(command), ("quit_jarvis", None))
        self.assertIsNone(ui.route_jarvis_ui_command("shut down my computer"))
        self.assertIsNone(ui.route_jarvis_ui_command("stop talking"))

    def test_quit_button_is_visible_and_accessible(self):
        button = self.window._quit_btn
        self.assertEqual(button.objectName(), "JarvisQuitButton")
        self.assertEqual(button.accessibleName(), "Quit JARVIS")
        self.assertEqual(button.toolTip(), "Quit JARVIS")
        self.assertFalse(button.isHidden())

    def test_dock_uses_crisp_command_rail_visual_language(self):
        rail = self.window._dock_frame
        style = rail.styleSheet().lower()
        self.assertEqual(rail.objectName(), "JarvisCommandRail")
        self.assertEqual(rail.accessibleName(), "JARVIS command rail")
        self.assertIsNone(rail.graphicsEffect())
        self.assertNotIn("qlineargradient", style)
        self.assertNotIn("border-radius: 24px", style)
        self.assertIn("border-radius: 6px", style)
        self.assertEqual(self.window._rail_control_track.objectName(), "CommandControlTrack")
        self.assertEqual(self.window._rail_control_track.accessibleName(), "Command controls")
        self.assertEqual(self.window._command_title_lbl.text(), "JARVIS COMMAND")
        self.assertIn("LOCAL", self.window._rail_mode_lbl.text())

        buttons = rail.findChildren(ui.QPushButton)
        self.assertEqual(len(buttons), 8)
        for button in buttons:
            self.assertTrue(button.accessibleName().strip(), button.text())
            self.assertTrue(button.toolTip().strip(), button.text())
            self.assertNotIn("🎙", button.text())

        primary_buttons = (
            self.window._mute_btn,
            self.window._tts_btn,
            self.window._name_btn,
            self.window._theme_btn,
            self.window._quit_btn,
        )
        visible_labels = {button.text().split("·", 1)[0].strip() for button in primary_buttons}
        self.assertEqual(visible_labels, {"MIC", "VOICE", "NAME", "SWITCH MODE", "QUIT"})

    def test_dock_mute_state_reuses_command_rail_style(self):
        original = self.window._muted
        try:
            self.window._muted = True
            self.window._style_mute_btn()
            self.assertIn("MUTED", self.window._mute_btn.text())
            self.assertEqual(self.window._mute_btn.accessibleName(), "Microphone muted")
            self.assertIn("border-radius: 5px", self.window._mute_btn.styleSheet())
            self.assertNotIn("border-radius: 17px", self.window._mute_btn.styleSheet())
        finally:
            self.window._muted = original
            self.window._style_mute_btn()

    def test_quit_command_uses_shared_shutdown_path(self):
        with patch.object(self.window, "_request_quit") as request_quit, \
             patch.object(ui.QTimer, "singleShot", side_effect=lambda _delay, callback: callback()):
            self.assertTrue(self.window._handle_ui_command("quit JARVIS"))
        request_quit.assert_called_once_with()

    def test_setup_overlay_is_centered_after_first_show(self):
        overlay = self.window._overlay
        self.assertIsNotNone(overlay)
        expected_x = (self.window.centralWidget().width() - overlay.width()) // 2
        expected_y = (self.window.centralWidget().height() - overlay.height()) // 2
        self.assertEqual((overlay.x(), overlay.y()), (expected_x, expected_y))

    def test_intro_settings_preserve_existing_ui_preferences(self):
        ui.UI_SETTINGS_FILE.write_text(
            json.dumps({"graphics_quality": "high", "theme": "stealth_red"}),
            encoding="utf-8",
        )
        ui._save_intro_settings(completed=True, greeting_enabled=True)
        saved = json.loads(ui.UI_SETTINGS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(saved["graphics_quality"], "high")
        self.assertEqual(saved["theme"], "stealth_red")
        self.assertTrue(saved["intro_completed"])
        self.assertTrue(saved["startup_greeting_enabled"])
        self.assertNotIn("intro_every_launch", saved)
        self.assertEqual(saved["intro_version"], ui.INTRO_SEQUENCE_VERSION)

    def test_legacy_intro_completion_replays_once_after_version_upgrade(self):
        original = ui.UI_SETTINGS_FILE.read_text(encoding="utf-8")
        try:
            ui.UI_SETTINGS_FILE.write_text(
                json.dumps({"intro_completed": True, "intro_every_launch": False}),
                encoding="utf-8",
            )
            self.assertEqual(ui._load_intro_settings(), (False, True))
            ui._save_intro_settings(completed=True, greeting_enabled=False)
            self.assertEqual(ui._load_intro_settings(), (True, False))
        finally:
            ui.UI_SETTINGS_FILE.write_text(original, encoding="utf-8")

    def test_setup_exposes_replay_preference(self):
        overlay = ui.SetupOverlay(replay_every_launch=True)
        self.assertTrue(overlay.replay_intro_enabled())
        overlay._replay_intro.setChecked(False)
        self.assertFalse(overlay.replay_intro_enabled())
        overlay.deleteLater()

    def test_setup_validation_state_is_visible_and_recoverable(self):
        overlay = ui.SetupOverlay()
        overlay._key_input.setText("AIza-test-key")
        overlay.set_validating()
        self.assertTrue(overlay._setup_status.isVisibleTo(overlay))
        self.assertIn("VALIDATING GEMINI API KEY", overlay._setup_status.text())
        self.assertFalse(overlay._key_input.isEnabled())
        overlay.set_validation_error("API key is not valid.")
        self.assertTrue(overlay._key_input.isEnabled())
        self.assertTrue(overlay._init_btn.isVisibleTo(overlay))
        self.assertIn("API KEY VALIDATION FAILED", overlay._setup_status.text())
        overlay.deleteLater()

    def test_replay_selected_during_setup_applies_to_current_launch(self):
        original_overlay = self.window._overlay
        original_should_play = self.window._intro_should_play
        original_kind = self.window._startup_sequence_kind
        original_gate = self.window._interaction_gated
        overlay = ui.SetupOverlay(replay_every_launch=True)
        self.window._overlay = overlay
        self.window._intro_should_play = False
        self.window._startup_sequence_kind = ""
        try:
            with patch.object(ui.threading, "Thread") as thread:
                self.window._on_setup_done("AIza" + "x" * 30, "mac", False)
            self.assertTrue(self.window._intro_should_play)
            self.assertIn("VALIDATING GEMINI API KEY", overlay._setup_status.text())
            thread.assert_called_once()
        finally:
            self.window._overlay = original_overlay
            self.window._intro_should_play = original_should_play
            self.window._startup_sequence_kind = original_kind
            self.window._interaction_gated = original_gate
            overlay.deleteLater()

    def test_setup_api_guide_expands_without_clearing_the_key(self):
        overlay = ui.SetupOverlay()
        overlay.show()
        overlay._key_input.setText("AIza-test-key")
        self.assertFalse(overlay._guide_scroll.isVisible())
        overlay._guide_button.click()
        self.app.processEvents()
        self.assertTrue(overlay._guide_scroll.isVisible())
        self.assertEqual(overlay._key_input.text(), "AIza-test-key")
        self.assertIn("Hide API key guide", overlay._guide_button.text())
        overlay._guide_button.click()
        self.assertEqual(overlay._key_input.text(), "AIza-test-key")
        overlay.hide()
        overlay.deleteLater()

    def test_setup_api_guide_opens_official_ai_studio_page(self):
        overlay = ui.SetupOverlay()
        with patch.object(ui.QDesktopServices, "openUrl", return_value=True) as open_url:
            overlay._open_api_key_page()
        self.assertEqual(
            open_url.call_args.args[0].toString(),
            "https://aistudio.google.com/apikey",
        )
        overlay.deleteLater()

    def test_fresh_install_voice_defaults_to_charon(self):
        self.assertEqual(self.window._get_selected_voice(), "charon")

    def test_gemini_voice_selection_drives_tour_and_survives_restart(self):
        original_config = (
            ui.API_FILE.read_text(encoding="utf-8")
            if ui.API_FILE.exists()
            else None
        )
        original_voice = self.window._get_selected_voice()
        original_callback = self.window.on_tts_provider_change
        original_env_voice = os.environ.get("GEMINI_VOICE_NAME")
        try:
            self.window.on_tts_provider_change = None
            with patch.object(ui, "_cache_intro_voice_async") as warm_cache:
                self.window._on_tts_select_done("gemini", "kore", "")

            saved = json.loads(ui.API_FILE.read_text(encoding="utf-8"))
            self.assertEqual(saved["tts_voice_id"], "kore")
            self.assertEqual(saved["voice_name"], "kore")
            self.assertEqual(self.window._get_selected_voice(), "kore")
            self.assertTrue(any(
                call.args[0] == "kore" for call in warm_cache.call_args_list
            ))

            self.window._voice_combo.blockSignals(True)
            self.window._voice_combo.setCurrentIndex(
                self.window._voice_combo.findData("charon")
            )
            self.window._voice_combo.blockSignals(False)
            self.window._load_saved_voice()
            self.assertEqual(self.window._get_selected_voice(), "kore")
            self.assertEqual(os.environ.get("GEMINI_VOICE_NAME"), "kore")
        finally:
            self.window.on_tts_provider_change = original_callback
            self.window._voice_combo.blockSignals(True)
            self.window._voice_combo.setCurrentIndex(
                self.window._voice_combo.findData(original_voice)
            )
            self.window._voice_combo.blockSignals(False)
            if original_config is None:
                ui.API_FILE.unlink(missing_ok=True)
            else:
                ui.API_FILE.write_text(original_config, encoding="utf-8")
            if original_env_voice is None:
                os.environ.pop("GEMINI_VOICE_NAME", None)
            else:
                os.environ["GEMINI_VOICE_NAME"] = original_env_voice

    def test_startup_backdrop_covers_the_live_console_during_setup(self):
        self.window._ensure_startup_backdrop()
        backdrop = self.window._startup_backdrop
        self.assertIsNotNone(backdrop)
        self.assertTrue(backdrop.isVisible())
        self.assertEqual(backdrop.geometry(), self.window.centralWidget().rect())
        self.assertIs(self.window._overlay.parentWidget(), self.window.centralWidget())

    def test_intro_overlay_renders_and_finishes_once(self):
        overlay = ui.FirstRunIntroOverlay(duration_s=1.0, speak=False)
        overlay.resize(960, 640)
        overlay._started_at = ui.time.monotonic() - 0.5
        image = overlay.grab().toImage()
        self.assertFalse(image.isNull())
        emissions = []
        overlay.finished.connect(lambda: emissions.append(True))
        overlay.finish()
        overlay.finish()
        self.assertEqual(emissions, [True])
        overlay.deleteLater()

    def test_live_intro_reveals_the_real_console_widgets_in_sequence(self):
        self.window._prepare_live_intro_widgets()
        groups = {
            group["name"]: group for group in self.window._intro_live_groups
        }
        self.assertIs(groups["core"]["widget"], self.window._ai_core_wrap)
        self.assertIs(groups["awareness"]["widget"], self.window._left_panel)
        self.assertIs(groups["communications"]["widget"], self.window._right_panel)
        self.assertIs(groups["dock"]["widget"], self.window._footer_panel)

        self.window._apply_live_intro_progress(1.2)
        self.assertGreater(groups["core"]["effect"].opacity(), 0.0)
        self.assertEqual(groups["awareness"]["effect"].opacity(), 0.0)

        self.window._apply_live_intro_progress(9.0)
        self.assertTrue(groups["awareness"]["completed"])
        self.assertIsNone(groups["awareness"]["widget"].graphicsEffect())
        self.assertGreater(groups["communications"]["effect"].opacity(), 0.0)
        self.assertIsNone(groups["dock"]["effect"])
        self.assertFalse(groups["dock"]["widget"].isVisible())

        self.window._apply_live_intro_progress(18.0)
        for group in groups.values():
            self.assertTrue(group["completed"])
            self.assertIsNone(group["widget"].graphicsEffect())
        self.window._restore_live_intro_widgets()
        for group in groups.values():
            self.assertIsNone(group["widget"].graphicsEffect())

    def test_settings_exposes_replay_preference_after_setup(self):
        overlay = ui.SettingsOverlay(replay_intro=True)
        self.assertTrue(overlay._s_replay_intro.isChecked())
        changes = []
        overlay.intro_replay_changed.connect(changes.append)
        overlay._s_replay_intro.setChecked(False)
        self.assertEqual(changes, [False])
        tour_requests = []
        overlay.tour_replay_requested.connect(lambda: tour_requests.append(True))
        overlay._s_replay_tour.click()
        self.assertEqual(tour_requests, [True])
        overlay.deleteLater()

    def test_settings_copy_distinguishes_greeting_from_interface_tour(self):
        overlay = ui.SettingsOverlay(replay_intro=True)
        self.assertEqual(overlay._s_replay_intro.text(), "Play greeting at startup")
        self.assertIn("REPLAY INTERFACE TOUR", overlay._s_replay_tour.text())
        overlay.deleteLater()

    def test_manual_tour_replay_activates_hard_interaction_lock(self):
        original = (
            self.window.on_tour_state_change,
            self.window._intro_in_progress,
            self.window._intro_voice_preparing,
            self.window._interaction_gated,
            self.window._manual_tour_replay,
        )
        states = []
        self.window.on_tour_state_change = states.append
        self.window._intro_in_progress = False
        self.window._intro_voice_preparing = False
        try:
            with (
                patch.object(ui, "_intro_voice_cache_path") as cache_path,
                patch.object(self.window, "_prepare_intro_voice") as prepare,
            ):
                cache_path.return_value = Path("/definitely/missing/tour.pcm")
                self.window._request_manual_tour_replay()
            self.assertTrue(self.window._interaction_gated)
            self.assertTrue(self.window._intro_in_progress)
            self.assertEqual(states, [True])
            prepare.assert_called_once()
        finally:
            (
                self.window.on_tour_state_change,
                self.window._intro_in_progress,
                self.window._intro_voice_preparing,
                self.window._interaction_gated,
                self.window._manual_tour_replay,
            ) = original

    def test_failed_tour_replay_returns_to_comms_and_releases_lock(self):
        original = (
            self.window._startup_sequence_kind,
            self.window._manual_tour_replay,
            self.window.on_tour_state_change,
            self.window._mission._active_tab,
        )
        states = []
        try:
            self.window._startup_sequence_kind = "tour"
            self.window._manual_tour_replay = True
            self.window.on_tour_state_change = states.append
            self.window._mission._switch_tab(3)
            self.window._on_intro_playback_failed("test failure", report=False)
            self.app.processEvents()
            self.assertEqual(self.window._mission._active_tab, 0)
            self.assertEqual(states, [False])
        finally:
            (
                self.window._startup_sequence_kind,
                self.window._manual_tour_replay,
                self.window.on_tour_state_change,
                original_tab,
            ) = original
            self.window._mission._switch_tab(original_tab)

    def test_intro_does_not_force_fullscreen(self):
        source = inspect.getsource(ui.MainWindow._start_first_run_intro)
        self.assertNotIn("showFullScreen", source)

    def test_intro_captions_use_the_live_subtitle_widget(self):
        self.window._show_intro_caption("Good evening. I am JARVIS.")
        self.assertEqual(
            self.window._subtitle._chunks,
            [["Good", "evening.", "I", "am", "JARVIS."]],
        )
        self.window._show_intro_caption("Communications linked.")
        self.assertEqual(
            self.window._subtitle._chunks,
            [["Communications", "linked."]],
        )
        self.window._subtitle.clear_subtitle()

    def test_intro_plays_only_prepared_selected_gemini_voice(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            with (
                patch.object(ui, "INTRO_VOICE_CACHE_DIR", Path(cache_dir)),
                patch.object(ui, "_generate_intro_speech_pcm") as generate,
                patch.object(ui, "_play_intro_pcm") as play,
            ):
                overlay = ui.FirstRunIntroOverlay(
                    speak=True,
                    voice_name="kore",
                    api_key="test-key",
                )
                cache_path = ui._intro_voice_cache_path(
                    "kore", overlay._narration, overlay._sequence_kind
                )
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(b"\x00\x00" * 64)
                overlay._start_narration()
                overlay._speech_thread.join(timeout=2.0)
                generate.assert_not_called()
                play.assert_called_once()
                self.assertTrue(cache_path.exists())
                overlay.stop_speech()
                overlay.deleteLater()

    def test_intro_cache_is_versioned_by_performance_and_mastering(self):
        original = ui._intro_voice_cache_path("charon", "intro")
        with patch.object(ui, "INTRO_PERFORMANCE_VERSION", "next-performance"):
            performance_changed = ui._intro_voice_cache_path("charon", "intro")
        with patch.object(ui, "INTRO_MASTERING_VERSION", "next-master"):
            mastering_changed = ui._intro_voice_cache_path("charon", "intro")
        self.assertNotEqual(original, performance_changed)
        self.assertNotEqual(original, mastering_changed)

    def test_intro_voice_preparation_retries_and_caches_selected_voice(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            with (
                patch.object(ui, "INTRO_VOICE_CACHE_DIR", Path(cache_dir)),
                patch.object(
                    ui,
                    "_generate_intro_speech_pcm",
                    side_effect=[b"", b"\x01\x00" * 64],
                ) as generate,
                patch.object(ui.time, "sleep"),
            ):
                ready, message = ui._prepare_intro_voice_cache(
                    "charon", "cinematic intro", "test-key", attempts=2
                )
                self.assertTrue(ready)
                self.assertEqual(message, "")
                self.assertEqual(generate.call_count, 2)
                cache_path = ui._intro_voice_cache_path(
                    "charon", "cinematic intro"
                )
                self.assertEqual(cache_path.read_bytes(), b"\x01\x00" * 64)

    def test_intro_generation_uses_tts_renderer_before_mastering(self):
        with (
            patch.object(
                ui, "_render_intro_with_live", new=AsyncMock(return_value=b"\x01\x00" * 64)
            ) as render,
            patch.object(ui, "_master_intro_pcm", side_effect=lambda pcm: pcm),
        ):
            pcm = ui._generate_intro_speech_pcm(
                "Good evening.", "charon", "AIza" + "x" * 30
            )
        self.assertEqual(pcm, b"\x01\x00" * 64)
        render.assert_awaited_once()

    def test_segmented_intro_uses_exact_tts_chapter_boundaries(self):
        pcm = b"\x01\x00" * (ui.INTRO_SAMPLE_RATE * 4)
        with (
            patch.object(
                ui,
                "_render_intro_segments_with_live",
                new=AsyncMock(
                    return_value=(pcm, [0, len(pcm) // 2, len(pcm)])
                ),
            ) as render,
            patch.object(ui, "_master_intro_pcm", side_effect=lambda value: value),
        ):
            result, boundaries = ui._generate_intro_segmented_speech_pcm(
                ("First chapter.", "Second chapter."),
                "charon",
                "AIza" + "x" * 30,
            )
        self.assertEqual(result, pcm)
        self.assertEqual(boundaries, [0.0, 2.0, 4.0])
        render.assert_awaited_once_with(
            ("First chapter.", "Second chapter."),
            "charon",
            "AIza" + "x" * 30,
        )

    def test_aligned_intro_renders_once_with_the_selected_voice(self):
        pcm = b"\x01\x00" * (ui.INTRO_SAMPLE_RATE * 4)
        with (
            patch.object(
                ui, "_generate_intro_speech_pcm", return_value=pcm
            ) as generate,
            patch.object(
                ui,
                "_intro_caption_boundaries",
                return_value=[0.0, 2.0, 4.0],
            ) as align,
        ):
            result, boundaries = ui._generate_intro_aligned_speech_pcm(
                ("First chapter.", "Second chapter."),
                "kore",
                "test-key",
            )

        self.assertEqual(result, pcm)
        self.assertEqual(boundaries, [0.0, 2.0, 4.0])
        generate.assert_called_once_with(
            "First chapter. Second chapter.",
            "kore",
            "test-key",
        )
        align.assert_called_once_with(
            pcm, ("First chapter.", "Second chapter.")
        )

    def test_intro_quota_error_never_substitutes_a_different_voice(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            with (
                patch.object(ui, "INTRO_VOICE_CACHE_DIR", Path(cache_dir)),
                patch.object(
                    ui,
                    "_generate_intro_aligned_speech_pcm",
                    side_effect=RuntimeError("429 RESOURCE_EXHAUSTED"),
                ),
            ):
                ready, message = ui._prepare_intro_voice_cache(
                    "fenrir",
                    "First chapter. Second chapter.",
                    "test-key",
                    sequence_kind="tour",
                    attempts=1,
                    captions=("First chapter.", "Second chapter."),
                )
                cache_path = ui._intro_voice_cache_path(
                    "fenrir",
                    "First chapter. Second chapter.",
                    "tour",
                )
                self.assertFalse(ready)
                self.assertIn("429 RESOURCE_EXHAUSTED", message)
                self.assertFalse(cache_path.exists())

    def test_intro_renderer_uses_dedicated_tts_with_exact_script(self):
        response = SimpleNamespace(candidates=[
            SimpleNamespace(content=SimpleNamespace(parts=[
                SimpleNamespace(inline_data=SimpleNamespace(
                    data=b"\x01\x00" * 64,
                    mime_type="audio/pcm",
                ))
            ]))
        ])
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=response)
        with (
            patch("google.genai.Client", return_value=client),
        ):
            pcm = asyncio.run(ui._render_intro_with_live(
                "JARVIS online.", "charon", "test-key"
            ))
        self.assertEqual(pcm, b"\x01\x00" * 64)
        request = client.aio.models.generate_content.await_args.kwargs
        self.assertEqual(request["model"], ui.INTRO_TTS_MODELS[0])
        self.assertEqual(request["contents"], "JARVIS online.")
        config = request["config"]
        self.assertEqual(config.response_modalities, ["AUDIO"])
        self.assertIsNone(config.tools)
        self.assertEqual(
            config.speech_config.voice_config.prebuilt_voice_config.voice_name,
            "Charon",
        )
        client.close.assert_called_once()

    def test_segmented_intro_renderer_returns_exact_pcm_boundaries(self):
        responses = [
            SimpleNamespace(candidates=[
                SimpleNamespace(content=SimpleNamespace(parts=[
                    SimpleNamespace(inline_data=SimpleNamespace(
                        data=b"\x01\x00" * 24,
                        mime_type="audio/pcm",
                    ))
                ]))
            ]),
            SimpleNamespace(candidates=[
                SimpleNamespace(content=SimpleNamespace(parts=[
                    SimpleNamespace(inline_data=SimpleNamespace(
                        data=b"\x02\x00" * 48,
                        mime_type="audio/pcm",
                    ))
                ]))
            ]),
        ]
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(side_effect=responses)
        with (
            patch("google.genai.Client", return_value=client),
        ):
            pcm, boundaries = asyncio.run(ui._render_intro_segments_with_live(
                ("First chapter.", "Second chapter."), "charon", "test-key"
            ))
        self.assertEqual(boundaries, [0, 48, 144])
        self.assertEqual(len(pcm), 144)
        self.assertEqual(client.aio.models.generate_content.await_count, 2)
        self.assertEqual(
            [
                call.kwargs["contents"]
                for call in client.aio.models.generate_content.await_args_list
            ],
            ["First chapter.", "Second chapter."],
        )
        client.close.assert_called_once()

    def test_segmented_tts_retries_when_model_returns_no_audio(self):
        empty_response = SimpleNamespace(candidates=[])
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=empty_response)
        with (
            patch("google.genai.Client", return_value=client),
        ):
            with self.assertRaisesRegex(RuntimeError, "returned no audio"):
                asyncio.run(ui._render_intro_segments_with_live(
                    ("Good evening.",), "charon", "test-key"
                ))
        self.assertEqual(
            client.aio.models.generate_content.await_count,
            ui.INTRO_CHAPTER_RENDER_ATTEMPTS * len(ui.INTRO_TTS_MODELS),
        )

    def test_segmented_tts_stops_immediately_on_quota_error(self):
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("429 RESOURCE_EXHAUSTED")
        )
        with patch("google.genai.Client", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "429"):
                asyncio.run(ui._render_intro_segments_with_live(
                    ("Good evening.",), "charon", "test-key"
                ))
        self.assertEqual(client.aio.models.generate_content.await_count, 1)

    def test_single_render_stops_immediately_on_quota_error(self):
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("429 RESOURCE_EXHAUSTED")
        )
        with patch("google.genai.Client", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "429"):
                asyncio.run(ui._render_intro_with_live(
                    "Good evening.", "kore", "test-key"
                ))
        self.assertEqual(client.aio.models.generate_content.await_count, 1)

    def test_time_aware_greeting_boundaries(self):
        self.assertTrue(ui._daily_greeting(datetime(2026, 1, 1, 5)).startswith("Good morning."))
        self.assertTrue(ui._daily_greeting(datetime(2026, 1, 1, 12)).startswith("Good afternoon."))
        self.assertTrue(ui._daily_greeting(datetime(2026, 1, 1, 18)).startswith("Good evening."))

    def test_full_tour_is_chaptered_for_a_ninety_second_delivery(self):
        chapters = ui._tour_chapters(datetime(2026, 1, 1, 19))
        narration = ui._tour_narration(datetime(2026, 1, 1, 19))
        captions = ui._tour_captions(datetime(2026, 1, 1, 19))
        self.assertEqual(len(chapters), 14)
        self.assertEqual(captions, tuple(chapter.caption for chapter in chapters))
        self.assertEqual(narration, " ".join(captions))
        self.assertGreaterEqual(len(narration.split()), 190)
        self.assertLessEqual(len(narration.split()), 225)
        self.assertEqual(ui.FirstRunIntroOverlay._TOUR_DURATION_S, 90.0)
        self.assertEqual(ui.FirstRunIntroOverlay._GREETING_DURATION_S, 18.0)
        self.assertEqual(ui.INTRO_SEQUENCE_VERSION, 5)

    def test_tour_chapters_cover_every_guided_region(self):
        chapters = ui._tour_chapters(datetime(2026, 1, 1, 19))
        self.assertEqual(
            {chapter.focus for chapter in chapters},
            {
                "core", "subtitles", "header", "awareness", "mission_comms",
                "mission_tasks", "mission_assets", "mission_tools", "input",
                "dock", "handoff",
            },
        )
        self.assertEqual(
            [chapter.tab_index for chapter in chapters if chapter.tab_index >= 0],
            [0, 1, 2, 3, 0, 0],
        )

    def test_chapter_signal_tracks_caption_boundaries(self):
        chapters = ui._tour_chapters(datetime(2026, 1, 1, 19))
        overlay = ui.FirstRunIntroOverlay(
            duration_s=90.0,
            speak=False,
            chapters=chapters,
            narration=" ".join(chapter.caption for chapter in chapters),
            captions=tuple(chapter.caption for chapter in chapters),
        )
        emitted = []
        overlay.chapter_changed.connect(lambda focus, label, tab: emitted.append((focus, label, tab)))
        overlay._started_at = ui.time.monotonic()
        overlay._tick()
        self.assertEqual(emitted[0], (chapters[0].focus, chapters[0].label, chapters[0].tab_index))
        last_index = overlay._caption_index_for_timeline(overlay._timeline_duration)
        self.assertEqual(last_index, len(chapters) - 1)
        overlay._timer.stop()
        overlay.deleteLater()

    def test_guided_tour_switches_real_tabs_and_restores_original(self):
        original_kind = self.window._startup_sequence_kind
        original_tab = self.window._mission._active_tab
        intro = ui.FirstRunIntroOverlay(
            self.window.centralWidget(), duration_s=90.0, speak=False,
        )
        try:
            self.window._mission._switch_tab(2)
            self.window._startup_sequence_kind = "tour"
            self.window._prepare_live_intro_widgets("tour")
            self.window._intro_overlay = intro
            intro.setGeometry(self.window.centralWidget().rect())
            self.window._on_intro_chapter_changed("mission_tools", "TOOLS", 3)
            self.assertEqual(self.window._mission._active_tab, 3)
            self.assertEqual(self.window._intro_focus_key, "mission_tools")
            self.assertTrue(intro._spotlight_target.isValid())
            self.assertTrue(intro._persistent_cutouts)
            self.window._restore_live_intro_widgets()
            self.assertEqual(self.window._mission._active_tab, 2)
        finally:
            self.window._intro_overlay = None
            self.window._startup_sequence_kind = original_kind
            self.window._mission._switch_tab(original_tab)
            intro.hide()
            intro.deleteLater()

    def test_voice_and_text_chapter_reveals_the_real_comms_input(self):
        original_kind = self.window._startup_sequence_kind
        original_tab = self.window._mission._active_tab
        intro = ui.FirstRunIntroOverlay(
            self.window.centralWidget(), duration_s=90.0, speak=False,
        )
        try:
            self.window._startup_sequence_kind = "tour"
            self.window._intro_overlay = intro
            intro.setGeometry(self.window.centralWidget().rect())
            self.window._mission._switch_tab(3)
            chapter = next(
                item for item in ui._tour_chapters(datetime(2026, 1, 1, 19))
                if item.focus == "input"
            )
            self.window._on_intro_chapter_changed(
                chapter.focus, chapter.label, chapter.tab_index
            )
            self.assertEqual(self.window._mission._active_tab, 0)
            self.assertTrue(self.window._chat_bubble._input.isVisible())
            self.assertTrue(intro._spotlight_target.isValid())
        finally:
            self.window._intro_overlay = None
            self.window._startup_sequence_kind = original_kind
            self.window._mission._switch_tab(original_tab)
            intro.hide()
            intro.deleteLater()

    def test_tour_leaves_tools_for_comms_on_the_next_non_tool_chapter(self):
        original_kind = self.window._startup_sequence_kind
        original_tab = self.window._mission._active_tab
        intro = ui.FirstRunIntroOverlay(
            self.window.centralWidget(), duration_s=90.0, speak=False,
        )
        try:
            self.window._startup_sequence_kind = "tour"
            self.window._intro_overlay = intro
            intro.setGeometry(self.window.centralWidget().rect())
            self.window._on_intro_chapter_changed(
                "mission_tools", "TOOLS", 3
            )
            self.assertEqual(self.window._mission._active_tab, 3)

            self.window._on_intro_chapter_changed(
                "core", "REACTOR CORE", -1
            )
            self.assertEqual(self.window._mission._active_tab, 0)
        finally:
            self.window._intro_overlay = None
            self.window._startup_sequence_kind = original_kind
            self.window._mission._switch_tab(original_tab)
            intro.hide()
            intro.deleteLater()

    def test_mission_empty_states_are_visible_until_real_activity_arrives(self):
        task_widget = ui.TaskQueueWidget()
        tool_widget = ui.ToolLogWidget()
        task_widget.show()
        tool_widget.show()
        self.app.processEvents()
        self.assertTrue(task_widget._empty_state.isVisible())
        self.assertTrue(tool_widget._empty_state.isVisible())

        task_widget._on_task("Web Search", "calling")
        tool_widget._on_entry("🔧 web_search")
        self.app.processEvents()
        self.assertFalse(task_widget._empty_state.isVisible())
        self.assertFalse(tool_widget._empty_state.isVisible())
        task_widget.deleteLater()
        tool_widget.deleteLater()

    def test_tools_panel_ignores_generic_system_lifecycle_messages(self):
        entries = self.window._mission.tool_widget._entries
        original_entries = list(entries)
        entries.clear()
        try:
            self.window._parse_log_for_context("SYS: JARVIS online.")
            self.app.processEvents()
            self.assertEqual(entries, [])

            self.window._parse_log_for_context("🔧 web_search calling")
            self.app.processEvents()
            self.assertEqual(len(entries), 1)
            self.assertIn("web_search", entries[0]["text"])
        finally:
            entries[:] = original_entries
            self.window._mission.tool_widget._rebuild()

    def test_reduced_motion_spotlight_moves_without_animation(self):
        overlay = ui.FirstRunIntroOverlay(duration_s=90.0, speak=False)
        overlay.set_reduced_motion(True)
        target = ui.QRect(20, 30, 200, 100)
        overlay.set_spotlight(target, "AWARENESS")
        self.assertEqual(overlay._current_spotlight_rect(), ui.QRectF(target))
        self.assertEqual(overlay._spotlight_label, "AWARENESS")
        overlay.deleteLater()

    def test_core_spotlight_is_compact_and_circular(self):
        intro = ui.FirstRunIntroOverlay(
            self.window.centralWidget(), duration_s=90.0, speak=False
        )
        original_intro = self.window._intro_overlay
        original_kind = self.window._startup_sequence_kind
        try:
            self.window._intro_overlay = intro
            self.window._startup_sequence_kind = "tour"
            intro.setGeometry(self.window.centralWidget().rect())
            self.window._on_intro_chapter_changed("core", "REACTOR CORE", -1)
            full = self.window._intro_rect_for_widget(self.window.hud, 0)
            target = intro._spotlight_target
            self.assertEqual(int(target.width()), int(target.height()))
            self.assertLess(target.width(), full.width())
            self.assertEqual(intro._spotlight_shape, "ellipse")
        finally:
            self.window._intro_overlay = original_intro
            self.window._startup_sequence_kind = original_kind
            intro.deleteLater()

    def test_successful_tour_handoff_finishes_on_comms(self):
        original_kind = self.window._startup_sequence_kind
        original_tab = self.window._mission._active_tab
        try:
            self.window._startup_sequence_kind = "tour"
            self.window._mission._switch_tab(3)
            self.window._prepare_live_intro_widgets("tour")
            handoff = ui._tour_chapters(datetime(2026, 1, 1, 19))[-1]
            self.window._on_intro_chapter_changed(
                handoff.focus, handoff.label, handoff.tab_index
            )
            self.assertEqual(self.window._mission._active_tab, 0)
            self.window._restore_live_intro_widgets(handoff_to_comms=True)
            self.assertEqual(self.window._mission._active_tab, 0)
        finally:
            self.window._startup_sequence_kind = original_kind
            self.window._mission._switch_tab(original_tab)

    def test_tour_mask_uses_quieter_single_focus_treatment(self):
        source = inspect.getsource(ui.FirstRunIntroOverlay.paintEvent)
        self.assertIn("qcol(C.BG, 96)", source)
        self.assertIn('self._spotlight_shape == "ellipse"', source)
        self.assertIn("if spotlight.isEmpty():", source)

    def test_long_intro_renderer_has_extended_timeout(self):
        source = inspect.getsource(ui._request_intro_tts)
        self.assertIn("timeout=90.0", source)

    def test_tour_and_greeting_use_distinct_caches(self):
        narration = "JARVIS online."
        self.assertNotEqual(
            ui._intro_voice_cache_path("charon", narration, "tour"),
            ui._intro_voice_cache_path("charon", narration, "greeting"),
        )

    def test_each_selected_voice_uses_its_own_intro_cache(self):
        narration = "JARVIS online."
        self.assertNotEqual(
            ui._intro_voice_cache_path("charon", narration, "tour"),
            ui._intro_voice_cache_path("kore", narration, "tour"),
        )

    def test_intro_mastering_keeps_raw_pcm_valid_and_peak_safe(self):
        source = (1000).to_bytes(2, "little", signed=True) * 240
        mastered = ui._master_intro_pcm(source)
        self.assertEqual(mastered, source)
        self.assertEqual(len(mastered) % 2, 0)
        peak = max(
            abs(int.from_bytes(mastered[i:i + 2], "little", signed=True))
            for i in range(0, len(mastered), 2)
        )
        self.assertLessEqual(peak, 32767)

    def test_intro_caption_boundaries_snap_to_pcm_pauses(self):
        sample_rate = ui.INTRO_SAMPLE_RATE
        tone = (4000).to_bytes(2, "little", signed=True)
        silence = b"\x00\x00"
        pcm = (
            tone * sample_rate
            + silence * int(sample_rate * 0.2)
            + tone * sample_rate
            + silence * int(sample_rate * 0.2)
            + tone * sample_rate
        )
        boundaries = ui._intro_caption_boundaries(pcm, ("one", "two", "three"))
        self.assertAlmostEqual(boundaries[1], 1.1, delta=0.08)
        self.assertAlmostEqual(boundaries[2], 2.3, delta=0.08)
        self.assertAlmostEqual(boundaries[-1], 3.4, delta=0.02)

    def test_exact_intro_timing_sidecar_overrides_estimated_boundaries(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            cache_path = Path(cache_dir) / "charon-test.pcm"
            pcm = b"\x01\x00" * (ui.INTRO_SAMPLE_RATE * 6)
            cache_path.write_bytes(pcm)
            exact = [0.0, 1.25, 3.75, 6.0]
            ui._write_intro_timing_cache(cache_path, exact)
            loaded = ui._load_intro_timing_cache(cache_path, 3, 6.0)
            self.assertEqual(loaded, exact)

    def test_audio_driven_intro_waits_for_playback_clock_before_first_chapter(self):
        overlay = ui.FirstRunIntroOverlay(duration_s=1.0, speak=False)
        overlay._audio_driven = True
        overlay._audio_duration = 20.0
        overlay._started_at = ui.time.monotonic()
        captions = []
        chapters = []
        overlay.caption_changed.connect(captions.append)
        overlay.chapter_changed.connect(lambda *args: chapters.append(args))
        overlay._tick()
        self.assertEqual(captions, [])
        self.assertEqual(chapters, [])
        overlay._on_speech_progress(0.1)
        overlay._tick()
        self.assertTrue(captions)
        self.assertTrue(chapters)
        overlay._timer.stop()
        overlay.deleteLater()

    def test_tour_temporarily_suppresses_presence_popups(self):
        timer = self.window._presence_system._presence_tmr
        timer.start()
        self.window._prepare_live_intro_widgets("tour")
        self.assertFalse(timer.isActive())
        self.window._restore_live_intro_widgets()
        self.assertTrue(timer.isActive())

    def test_tour_popup_cleanup_ignores_deleted_qt_wrappers(self):
        class DeletedPopup:
            def _dismiss(self):
                raise RuntimeError(
                    "wrapped C/C++ object of type BasePopup has been deleted"
                )

        manager = ui.PopupManager(self.window._ai_core_wrap)
        manager.active_popups = [DeletedPopup()]
        manager.dismiss_all_popups()
        self.assertEqual(manager.active_popups, [])

    def test_tour_start_failure_is_reported_and_does_not_escape_qt_slot(self):
        original = (
            self.window._startup_sequence_kind,
            self.window._startup_chapters,
            self.window._startup_captions,
            self.window._startup_narration,
            self.window._manual_tour_replay,
            self.window._intro_in_progress,
            self.window._interaction_gated,
        )
        chapters = ui._tour_chapters(datetime(2026, 1, 1, 19))
        self.window._startup_sequence_kind = "tour"
        self.window._startup_chapters = chapters
        self.window._startup_captions = tuple(chapter.caption for chapter in chapters)
        self.window._startup_narration = " ".join(self.window._startup_captions)
        self.window._manual_tour_replay = True
        self.window._intro_in_progress = True
        self.window._interaction_gated = True
        try:
            with (
                patch.object(
                    self.window._popup_manager,
                    "dismiss_all_popups",
                    side_effect=RuntimeError(
                        "wrapped C/C++ object of type BasePopup has been deleted"
                    ),
                ),
                patch.object(self.window, "_intro_terminal_report") as report,
                patch.object(ui.traceback, "print_exc"),
            ):
                self.window._start_first_run_intro()
            states = [call.args[0] for call in report.call_args_list]
            self.assertIn("FAILED", states)
            self.assertFalse(self.window._intro_in_progress)
            self.assertFalse(self.window._interaction_gated)
        finally:
            (
                self.window._startup_sequence_kind,
                self.window._startup_chapters,
                self.window._startup_captions,
                self.window._startup_narration,
                self.window._manual_tour_replay,
                self.window._intro_in_progress,
                self.window._interaction_gated,
            ) = original

    def test_audio_driven_intro_never_finishes_on_wall_clock_deadline(self):
        overlay = ui.FirstRunIntroOverlay(duration_s=1.0, speak=False)
        overlay._audio_driven = True
        overlay._audio_duration = 20.0
        overlay._caption_boundaries = [
            index * 2.5 for index in range(len(overlay._CAPTIONS) + 1)
        ]
        overlay._speech_position = 10.0
        overlay._started_at = ui.time.monotonic() - 60.0
        emissions = []
        overlay.finished.connect(lambda: emissions.append(True))
        overlay._tick()
        self.assertEqual(emissions, [])
        overlay._speech_position = 20.0
        overlay._speech_finished_at = ui.time.monotonic() - overlay._FINAL_HOLD_S - 0.1
        overlay._tick()
        self.assertEqual(emissions, [True])
        overlay.deleteLater()

    def test_intro_pcm_duration_is_used_as_the_audio_clock(self):
        pcm = b"\x00\x00" * (ui.INTRO_SAMPLE_RATE * 17)
        self.assertEqual(ui._pcm_duration_seconds(pcm), 17.0)

    def test_intro_has_no_platform_voice_fallback(self):
        self.assertFalse(hasattr(ui.FirstRunIntroOverlay, "_start_platform_voice_fallback"))

    def test_key_validation_does_not_complete_intro_early(self):
        source = inspect.getsource(ui.MainWindow._finish_setup_after_key_validation)
        self.assertNotIn("completed=True", source)

    def test_successful_validation_keeps_setup_until_voice_is_ready(self):
        original_overlay = self.window._overlay
        original_should_play = self.window._intro_should_play
        original_ready = self.window._ready
        original_settings = ui.UI_SETTINGS_FILE.read_text(encoding="utf-8")
        original_key = os.environ.get("GEMINI_API_KEY")
        overlay = ui.SetupOverlay(replay_every_launch=True)
        overlay.show()
        self.window._overlay = overlay
        self.window._intro_should_play = True
        self.window._pending_greeting_enabled = True
        self.window._ready = True
        try:
            with patch.object(self.window, "_prepare_intro_voice") as prepare:
                self.window._finish_setup_after_key_validation(
                    "AIza" + "x" * 30,
                    "mac",
                    False,
                    ui.ApiKeyValidationResult(True, "API key validated."),
                )
            prepare.assert_called_once()
            self.assertIs(self.window._overlay, overlay)
            self.assertTrue(overlay.isVisible())
            self.assertFalse(self.window._ready)
        finally:
            overlay.hide()
            overlay.deleteLater()
            self.window._overlay = original_overlay
            self.window._intro_should_play = original_should_play
            self.window._ready = original_ready
            ui.UI_SETTINGS_FILE.write_text(original_settings, encoding="utf-8")
            if original_key is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = original_key

    def test_startup_gate_blocks_text_callbacks_until_ready(self):
        original_ready = self.window._ready
        original_intro = self.window._intro_in_progress
        original_callback = self.window.on_text_command
        callback = MagicMock()
        self.window.on_text_command = callback
        self.window._ready = False
        self.window._intro_in_progress = True
        try:
            self.window._send("run a task")
            callback.assert_not_called()
        finally:
            self.window._ready = original_ready
            self.window._intro_in_progress = original_intro
            self.window.on_text_command = original_callback

    def test_operational_readiness_requires_every_startup_gate_to_clear(self):
        original = (
            self.window._ready,
            self.window._interaction_gated,
            self.window._intro_in_progress,
            self.window._intro_voice_preparing,
            self.window._intro_overlay,
            self.window._overlay,
        )
        try:
            self.window._ready = True
            self.window._interaction_gated = False
            self.window._intro_in_progress = False
            self.window._intro_voice_preparing = False
            self.window._intro_overlay = None
            self.window._overlay = None
            facade = ui.JarvisUI.__new__(ui.JarvisUI)
            facade._win = self.window
            self.assertTrue(facade.operational_ready)
            self.window._intro_in_progress = True
            self.assertFalse(facade.operational_ready)
            self.window._intro_in_progress = False
            self.window._intro_voice_preparing = True
            self.assertFalse(facade.operational_ready)
        finally:
            (
                self.window._ready,
                self.window._interaction_gated,
                self.window._intro_in_progress,
                self.window._intro_voice_preparing,
                self.window._intro_overlay,
                self.window._overlay,
            ) = original

    def test_intro_completion_is_the_operational_readiness_transition(self):
        original_ready = self.window._ready
        original_pending = self.window._pending_ready_after_intro
        original_announced = self.window._ready_announced
        self.window._ready = False
        self.window._pending_ready_after_intro = True
        self.window._ready_announced = False
        try:
            with (
                patch.object(self.window, "_clear_startup_backdrop"),
                patch.object(self.window, "_show_voice_select_then_name"),
            ):
                self.window._continue_after_intro()
            self.assertTrue(self.window._ready)
            self.assertTrue(self.window._ready_announced)
        finally:
            self.window._ready = original_ready
            self.window._pending_ready_after_intro = original_pending
            self.window._ready_announced = original_announced

    def test_splitter_uses_evaluated_stylesheet(self):
        sheet = self.window._splitter.styleSheet()
        self.assertNotIn('f"""', sheet)
        self.assertNotIn("{C.", sheet)
        self.assertIn("QSplitter::handle", sheet)

    def test_qss_alpha_colors_are_explicit_rgba(self):
        self.assertEqual(ui.qss_rgba("#ff2244", 0x22), "rgba(255, 34, 68, 34)")
        source = Path(ui.__file__).read_text(encoding="utf-8")
        self.assertNotRegex(source, r"\{C\.[A-Z_]+\}[0-9A-Fa-f]{2}")

    def test_unavailable_hardware_metrics_are_not_fabricated(self):
        self.window._gpu_info_cached = True
        self.window._gpu_chip = "GPU unavailable"
        self.window._gpu_vram_str = "N/A"
        with patch.object(ui, "_get_metrics", return_value=_MetricsSnapshot()):
            self.original_update_metrics(self.window)
        self.assertEqual(self.window._gpu_pct_lbl.text(), "N/A")
        self.assertEqual(self.window._spark_tmp._value, "N/A")
        self.assertEqual(self.window._gpu_load_bar.value(), 0)



if __name__ == "__main__":
    unittest.main()
