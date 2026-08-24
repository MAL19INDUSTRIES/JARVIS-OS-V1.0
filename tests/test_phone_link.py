import json
import os
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import ui
from core.phone_link import (
    PairingInfo,
    PhoneLinkError,
    PhoneLinkService,
    _phone_handoff,
    _phone_handoff_limitation,
)
from ui_phone_link import PhoneLinkWorkspaceWidget


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
        natural = _phone_handoff("Can you open Instagram on my phone")
        self.assertEqual(natural["kind"], "open")
        self.assertEqual(natural["label"], "Open Instagram")
        natural_message = _phone_handoff("Please text 4155550123 saying Running late")
        self.assertEqual(natural_message["copy"], "Running late")
        self.assertEqual(
            natural_message["url"],
            "sms:4155550123&body=Running%20late",
        )
        self.assertEqual(
            _phone_handoff("Would you dial the number 415-555-0199 on my iPhone")["url"],
            "tel:4155550199",
        )
        self.assertEqual(
            _phone_handoff("Take me to the YouTube app on my phone")["label"],
            "Open Youtube",
        )
        self.assertIn("phone number", _phone_handoff_limitation("Call Alex"))
        self.assertIn("not available", _phone_handoff_limitation("Open the camera"))
        self.assertIn(
            "other apps",
            _phone_handoff_limitation("Read my notifications", native=True),
        )
        self.assertIsNone(_phone_handoff("delete all my photos"))

    def test_native_phone_actions_use_the_companion_contract(self):
        call = _phone_handoff("Call Alex", native=True)
        self.assertEqual(call["kind"], "call-contact")
        self.assertEqual(call["contact"], "Alex")
        message = _phone_handoff("Text Sam saying On my way", native=True)
        self.assertEqual(message["kind"], "message-contact")
        self.assertEqual(message["copy"], "On my way")
        self.assertEqual(_phone_handoff("Open the camera", native=True)["kind"], "camera")
        self.assertEqual(
            _phone_handoff("Enable JARVIS notifications", native=True)["kind"],
            "notifications",
        )
        self.assertIsNone(_phone_handoff("Open the camera"))

    def test_native_pairing_is_remembered_as_a_native_client(self):
        with patch.object(self.service, "start"), patch(
            "core.phone_link._lan_host", return_value="jarvis.local"
        ):
            pairing = self.service.create_pairing()
        result = self.service.exchange_pairing(pairing.token, "Test iPhone", "ios-native")
        device = self.service.authenticate(result["device_token"])
        self.assertEqual(device["client_kind"], "ios-native")
        response = self.service.receive_chat(device, "Open the camera")
        self.assertEqual(response["handoff"]["kind"], "camera")

    def test_mobile_handoff_is_a_native_link_not_async_navigation(self):
        root = Path(__file__).resolve().parents[1] / "assets" / "phone_link"
        html = (root / "index.html").read_text(encoding="utf-8")
        script = (root / "phone.js").read_text(encoding="utf-8")
        self.assertIn('<a id="handoff-button"', html)
        self.assertIn('handoffButton.setAttribute("href", data.url)', script)
        self.assertNotIn("location.href = handoffData.url", script)
        self.assertIn("pairInBrowser(pairToken)", script)
        self.assertIn("Add to Home Screen", html)
        self.assertNotIn("OPEN JARVIS APP", html)
        self.assertNotIn("jarvisphone://pair", script)

    def test_capability_question_is_answered_without_false_model_refusal(self):
        _, result = self._pair()
        device = self.service.authenticate(result["device_token"])
        response = self.service.receive_chat(device, "What can you do on my phone?")
        self.assertEqual(response["handled"], "capabilities")
        self.assertEqual(self.dispatched, [])
        self.assertIn("prepare calls", self.service.session(device)["messages"][-1]["content"])


class PhoneLinkWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ui._load_bundled_fonts()

    def test_native_button_opens_spacious_center_workspace(self):
        temporary = TemporaryDirectory()
        service = PhoneLinkService(state_path=Path(temporary.name) / "state.json")
        with patch.object(ui.MainWindow, "_start_auto_graphics_detection"), \
             patch("ui.PhoneLinkService", return_value=service):
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
            temporary.cleanup()

    def test_phone_message_carries_verified_channel_context_to_model(self):
        received = []
        done = threading.Event()

        def callback(value):
            received.append(value)
            done.set()

        stub = SimpleNamespace(
            _log=SimpleNamespace(append_log=MagicMock()),
            _log_sig=SimpleNamespace(emit=MagicMock()),
            on_text_command=callback,
        )
        ui.MainWindow._receive_phone_message(stub, "Open Instagram")
        self.assertTrue(done.wait(1.0))
        self.assertIn("[VERIFIED PHONE LINK MESSAGE]", received[0])
        self.assertIn('User message: "Open Instagram"', received[0])
        self.assertIn("Never say that Phone Link can do nothing", received[0])

    def test_qr_step_opens_as_a_focused_modal(self):
        temporary = TemporaryDirectory()
        service = PhoneLinkService(state_path=Path(temporary.name) / "state.json")
        pairing = PairingInfo(
            "http://jarvis.local:8765/phone/#pair=modal-test",
            "modal-test",
            time.time() + 120,
        )
        palette = ui.MainWindow._preview_palette()
        workspace = PhoneLinkWorkspaceWidget(service, palette)
        workspace.resize(940, 620)
        workspace.show()
        try:
            with patch.object(service, "create_pairing", return_value=pairing):
                workspace.begin_pairing()
            self.app.processEvents()
            dialog = workspace._qr_dialog
            self.assertIsNotNone(dialog)
            self.assertTrue(dialog.isVisible())
            self.assertTrue(dialog.isModal())
            self.assertEqual(dialog.size().width(), 432)
            self.assertFalse(dialog._qr.pixmap().isNull())
            self.assertIs(workspace._stack.currentWidget(), workspace._confirm_page)
            self.assertFalse(hasattr(workspace, "_pair_page"))
            self.assertIsNotNone(workspace.graphicsEffect())
            dialog._pairing = PairingInfo(pairing.url, pairing.token, time.time() - 1)
            dialog._tick()
            self.assertTrue(dialog._refresh.isVisible())
            self.assertIn("expired", dialog._instruction.text().lower())
            renewed = PairingInfo(pairing.url, "renewed", time.time() + 120)
            with patch.object(service, "create_pairing", return_value=renewed):
                dialog._renew()
            self.assertFalse(dialog._refresh.isVisible())
            self.assertIn("Expires in 2:00", dialog._detail.text())
            dialog.reject()
            self.app.processEvents()
            self.assertIsNone(workspace.graphicsEffect())
        finally:
            workspace.stop()
            workspace.close()
            workspace.deleteLater()
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
