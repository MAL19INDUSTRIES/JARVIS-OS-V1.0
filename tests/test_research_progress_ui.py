import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import ui


class ResearchProgressWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ui._load_bundled_fonts()

    def test_widget_shows_real_phase_progress_and_completed_artifact(self):
        widget = ui.ResearchProgressWidget()
        widget.start("Battery recycling economics")
        self.app.processEvents()
        self.assertFalse(widget.isHidden())
        self.assertEqual(widget._bar.value(), 0)

        widget.update_progress(
            "Battery recycling economics",
            42,
            "Researching evidence thread 3/6",
        )
        self.app.processEvents()
        self.assertEqual(widget._bar.value(), 42)
        self.assertEqual(widget._status.text(), "RUNNING IN THE BACKGROUND  ·  42%")
        self.assertEqual(widget._phase.text(), "Researching evidence thread 3/6")

        widget.update_progress(
            "Battery recycling economics",
            100,
            "Deep research complete",
            artifacts=["/tmp/battery-report.md"],
        )
        self.app.processEvents()
        self.assertEqual(widget._status.text(), "COMPLETE  ·  100%")
        self.assertEqual(widget._phase.text(), "Report ready: battery-report.md")
        widget.deleteLater()

    def test_widget_uses_project_typography(self):
        widget = ui.ResearchProgressWidget()
        self.assertEqual(widget._title.font().family(), ui.UI_FONT)
        self.assertEqual(widget._status.font().family(), ui.TECH_FONT)
        self.assertTrue(widget.accessibleName())
        self.assertTrue(widget._bar.accessibleName())
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
