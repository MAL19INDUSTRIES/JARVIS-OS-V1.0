import os
import unittest
from types import MethodType, SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import ui


class UIBrandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_maker_signature_is_present_and_mode_aware(self):
        host = SimpleNamespace()
        host._style_maker_signature = MethodType(
            ui.MainWindow._style_maker_signature, host
        )

        strip = ui.MainWindow._build_maker_signature(host)
        self.addCleanup(strip.deleteLater)

        self.assertEqual(host._maker_signature_lbl.text(), "Creation by AMDCREATIONZ")
        self.assertEqual(strip.objectName(), "JarvisMakerSignature")
        self.assertEqual(strip.height(), 20)
        self.assertIn(ui.C.TEXT_DIM, host._maker_signature_lbl.styleSheet())
        self.assertIn(ui.C.BG, strip.styleSheet())
        self.assertEqual(
            host._maker_signature_lbl.accessibleName(), "Creation by AMDCREATIONZ trademark"
        )


if __name__ == "__main__":
    unittest.main()
