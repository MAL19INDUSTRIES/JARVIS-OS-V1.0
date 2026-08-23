import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import ui


class GraphicsQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ui._load_bundled_fonts()

    def test_setting_is_persistent_and_preserves_other_preferences(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps({"active_mode": "atlas"}), encoding="utf-8")
            with patch.object(ui, "UI_SETTINGS_FILE", settings_file):
                self.assertEqual(ui.set_graphics_quality("high"), "high")
                self.assertEqual(json.loads(settings_file.read_text(encoding="utf-8")), {
                    "active_mode": "atlas",
                    "graphics_quality": "high",
                    "graphics_quality_mode": "manual",
                })

    def test_hud_profiles_change_real_rendering_cost(self):
        hud = ui.HudCanvas("missing.png")
        try:
            hud.set_graphics_quality("very_low")
            self.assertEqual((hud._tmr.interval(), hud._render_stride, hud._noise_count), (200, 7, 0))
            hud.set_graphics_quality("medium_low")
            self.assertEqual((hud._tmr.interval(), hud._render_stride, hud._noise_count), (66, 4, 8))
            hud.set_graphics_quality("medium")
            self.assertEqual((hud._tmr.interval(), hud._render_stride, hud._noise_count), (42, 3, 25))
            hud.set_graphics_quality("high")
            self.assertEqual((hud._tmr.interval(), hud._render_stride, hud._noise_count), (24, 1, 110))
        finally:
            hud._tmr.stop()
            hud.deleteLater()

    def test_settings_exposes_auto_and_seven_manual_quality_choices(self):
        overlay = ui.SettingsOverlay(current_graphics="medium")
        try:
            self.assertEqual(set(overlay._graphics_btns), {
                "auto", "very_low", "low", "medium_low", "medium",
                "high_low", "high", "ultra",
            })
            selected = []
            overlay.graphics_changed.connect(selected.append)
            overlay._select_graphics("high")
            self.assertEqual(selected, ["high"])
        finally:
            overlay.deleteLater()

    def test_hidden_renderers_stop_their_animation_loops(self):
        hud = ui.HudCanvas("missing.png")
        activity = ui.AIActivityCanvas()
        agents = ui.AgentGridWidget()
        try:
            hud.set_rendering_active(False)
            activity.set_rendering_active(False)
            agents.set_animation_active(False)
            self.assertFalse(hud._tmr.isActive())
            self.assertFalse(activity._tmr.isActive())
            self.assertFalse(agents._tmr.isActive())

            hud.set_rendering_active(True)
            self.assertTrue(hud._tmr.isActive())
        finally:
            hud._tmr.stop()
            activity._tmr.stop()
            agents._tmr.stop()
            hud.deleteLater()
            activity.deleteLater()
            agents.deleteLater()

    def test_chat_typing_reuses_one_widget_and_batches_characters(self):
        chat = ui.ChatBubbleWidget()
        try:
            chat.set_graphics_quality("very_low")
            chat._on_message("JARVIS: This is a longer response for the operator.")
            bubble = chat._typing_bubble
            chat._typing_tick()
            self.assertIs(chat._typing_bubble, bubble)
            self.assertEqual(chat._typing_idx, 8)
            self.assertEqual(chat._typing_timer.interval(), 32)
        finally:
            if hasattr(chat, "_typing_timer"):
                chat._typing_timer.stop()
            chat.deleteLater()

    def test_low_quality_mode_transition_uses_reduced_motion(self):
        parent = ui.QWidget()
        overlay = ui.ModeTransitionOverlay("ultron", parent, "low")
        try:
            self.assertTrue(overlay._reduced)
            self.assertEqual(overlay._duration_ms, 180)
            self.assertEqual(overlay._timer.interval(), 80)
            self.assertIsNone(overlay._snapshot)
        finally:
            overlay._timer.stop()
            overlay.deleteLater()
            parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
