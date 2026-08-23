import json
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import ui
from core.phone_link import PhoneLinkError, PhoneLinkService, _phone_handoff


class PhoneLinkServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.state_path = Path(self.temporary.name) / "phone_link.json"
        self.dispatched = []
        self.service = PhoneLinkService(
            state_path=self.state_path,
            port=8765,
            dispatch=self.dispatched.append,
            persona=lambda: "JARVIS",
        )

    def tearDown(self):
        self.service.stop()
        self.temporary.cleanup()

    def _pair(self):
        with patch.object(self.service, "start"), patch("core.phone_link._lan_host", return_value="jarvis.local"):
            pairing = self.service.create_pairing()
        result = self.service.exchange_pairing(pairing.token, "Mirsab's iPhone")
        return pairing, result

    def test_pairing_is_single_use_and_remembered_as_a_hash(self):
        pairing, result = self._pair()
        self.assertEqual(pairing.url.split("#", 1)[0], "http://jarvis.local:8765/phone/")
        self.assertNotIn(pairing.token, self.state_path.read_text(encoding="utf-8"))
        self.assertNotIn(result["device_token"], self.state_path.read_text(encoding="utf-8"))
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["devices"][0]["name"], "Mirsab's iPhone")
        self.assertIsNotNone(self.service.authenticate(result["device_token"]))
        with self.assertRaises(PhoneLinkError):
            self.service.exchange_pairing(pairing.token, "Replay")

    def test_revoked_phone_can_no_longer_authenticate(self):
        _, result = self._pair()
        device = self.service.authenticate(result["device_token"])
        self.assertTrue(self.service.revoke_device(device["id"]))
        self.assertIsNone(self.service.authenticate(result["device_token"]))

    def test_chat_dispatches_and_transcript_filters_desktop_logs(self):
        _, result = self._pair()
        device = self.service.authenticate(result["device_token"])
        response = self.service.receive_chat(device, "How are the systems?")
        self.assertTrue(response["accepted"])
        self.assertEqual(self.dispatched, ["How are the systems?"])
        self.service.publish_log("SYS: hidden diagnostic")
        self.service.publish_log("Jarvis: All systems nominal.")
        session = self.service.session(device)
        self.assertEqual(session["persona"], "JARVIS")
        self.assertEqual(session["messages"][-1]["content"], "All systems nominal.")
        self.assertNotIn("hidden diagnostic", [item["content"] for item in session["messages"]])

    def test_phone_actions_are_handoffs_not_silent_execution(self):
        call = _phone_handoff("call +1 (415) 555-0123")
        self.assertEqual(call["kind"], "call")
        self.assertEqual(call["url"], "tel:+14155550123")
        message = _phone_handoff("message 4155550123: Running ten minutes late")
        self.assertEqual(message["kind"], "message")
        self.assertEqual(message["copy"], "Running ten minutes late")
        self.assertIsNone(_phone_handoff("delete all my photos"))


class PhoneLinkWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ui._load_bundled_fonts()

    def test_native_button_opens_spacious_center_workspace(self):
        with patch.object(ui.MainWindow, "_start_auto_graphics_detection"):
            window = ui.MainWindow("missing.png")
        window.show()
        self.app.processEvents()
        try:
            window._phone_link_btn.click()
            self.app.processEvents()
            self.assertIs(window._core_stack.currentWidget(), window._phone_link_workspace)
            self.assertEqual(
                window._phone_link_workspace._stack.currentWidget(),
                window._phone_link_workspace._confirm_page,
            )
            self.assertIn(
                "You want me to access your phone?",
                window._phone_link_workspace._confirm_page.findChildren(ui.QLabel)[1].text(),
            )
            window._phone_link_workspace.close_requested.emit()
            self.app.processEvents()
            self.assertIs(window._core_stack.currentWidget(), window.hud)
        finally:
            window._force_quit = True
            window.close()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
