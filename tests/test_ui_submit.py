import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import ui


class UISubmitTests(unittest.TestCase):
    def _window_stub(self, callback=None):
        return SimpleNamespace(
            _log=SimpleNamespace(append_log=MagicMock()),
            _log_sig=SimpleNamespace(emit=MagicMock()),
            _set_command_center=MagicMock(),
            on_text_command=callback,
        )

    def test_command_center_message_no_longer_crashes_normalization(self):
        window = self._window_stub()
        ui.MainWindow._send(window, "Open the Command Center!!!")
        window._set_command_center.assert_called_once_with(True)

    def test_regular_message_reaches_jarvis_callback(self):
        received = []
        done = threading.Event()

        def callback(text):
            received.append(text)
            done.set()

        window = self._window_stub(callback)
        ui.MainWindow._send(window, "Send Alex a message")
        self.assertTrue(done.wait(1.0))
        self.assertEqual(received, ["Send Alex a message"])

    def test_callback_failure_is_logged_instead_of_escaping_qt(self):
        done = threading.Event()

        def callback(_text):
            done.set()
            raise RuntimeError("routing failed")

        window = self._window_stub(callback)
        ui.MainWindow._send(window, "Hello JARVIS")
        self.assertTrue(done.wait(1.0))
        for _ in range(100):
            if window._log_sig.emit.called:
                break
            time.sleep(0.005)
        window._log_sig.emit.assert_called_once_with("ERR: Message processing failed: routing failed")


if __name__ == "__main__":
    unittest.main()
