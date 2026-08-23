import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

import ui


class VisionPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ui._load_bundled_fonts()

    @staticmethod
    def _image_bytes() -> bytes:
        image = QImage(160, 90, QImage.Format.Format_RGB888)
        image.fill(QColor("#12384a"))
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "JPEG")
        buffer.close()
        return bytes(data)

    def test_screen_workspace_uses_frozen_captured_frame(self):
        host = QWidget()
        host.resize(900, 640)
        host.show()
        preview = ui.VisionWorkspaceWidget(host)
        preview.resize(700, 480)
        try:
            preview.start("screen", self._image_bytes())
            self.app.processEvents()
            self.assertIs(preview.parentWidget(), host)
            self.assertFalse(preview.isWindow())
            self.assertEqual(preview._source, "screen")
            self.assertEqual(preview._source_label.text(), "SCREEN CAPTURE")
            self.assertEqual(preview._status.text(), "CAPTURED // ANALYZING")
            self.assertFalse(preview._frame_timer.isActive())
            self.assertFalse(preview._frame.pixmap().isNull())

            preview.finish(2500)
            self.assertEqual(preview._status.text(), "ANALYSIS COMPLETE")
            self.assertTrue(preview._hide_timer.isActive())
        finally:
            preview.stop()
            preview.deleteLater()
            host.deleteLater()

    def test_camera_workspace_runs_live_capture_timer(self):
        preview = ui.VisionWorkspaceWidget()
        try:
            with patch.object(preview, "_open_source"), \
                 patch.object(preview, "_update_frame"):
                preview.start("camera", self._image_bytes())
                self.assertEqual(preview._source_label.text(), "CAMERA FEED")
                self.assertTrue(preview._frame_timer.isActive())
                preview.stop()
                self.assertFalse(preview._frame_timer.isActive())
        finally:
            preview.stop()
            preview.deleteLater()

    def test_main_window_restores_previous_center_workspace(self):
        with patch.object(ui.MainWindow, "_start_auto_graphics_detection"):
            window = ui.MainWindow("missing.png")
        window.show()
        self.app.processEvents()
        try:
            window._show_vision_preview({
                "source": "screen",
                "image_bytes": self._image_bytes(),
            })
            self.assertIs(window._core_stack.currentWidget(), window._vision_preview)
            self.assertIs(window._vision_previous_core_widget, window.hud)

            window._vision_preview.close_requested.emit()
            self.app.processEvents()
            self.assertIs(window._core_stack.currentWidget(), window.hud)

            window._core_stack.setCurrentWidget(window._website_preview)
            window._show_vision_preview({
                "source": "screen",
                "image_bytes": self._image_bytes(),
            })
            window._hide_vision_preview(1)
            QTest.qWait(10)
            self.assertIs(window._core_stack.currentWidget(), window._website_preview)
        finally:
            window.hide()
            window.deleteLater()

    def test_preview_cadence_follows_graphics_quality(self):
        preview = ui.VisionWorkspaceWidget()
        try:
            preview.set_graphics_quality("low")
            self.assertEqual(preview._frame_timer.interval(), 80)
            preview.set_graphics_quality("medium")
            self.assertEqual(preview._frame_timer.interval(), 42)
            preview.set_graphics_quality("high")
            self.assertEqual(preview._frame_timer.interval(), 33)
        finally:
            preview.stop()
            preview.deleteLater()


if __name__ == "__main__":
    unittest.main()
