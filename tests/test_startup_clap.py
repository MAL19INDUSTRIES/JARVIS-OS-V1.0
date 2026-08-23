import os
import time
import unittest
from unittest.mock import patch

import numpy as np

import main


class _ClapStream:
    def __init__(self, callback, emit_claps=False, **_kwargs):
        self.callback = callback
        self.emit_claps = emit_claps

    def __enter__(self):
        if self.emit_claps:
            samples = np.full((512, 1), 0.8, dtype=np.float32)
            self.callback(samples, 512, None, None)
            time.sleep(main.STARTUP_CLAP_COOLDOWN_SECONDS + 0.03)
            self.callback(samples, 512, None, None)
        return self

    def __exit__(self, *_args):
        return False


class StartupClapTests(unittest.TestCase):
    def test_two_distinct_claps_unlock_startup(self):
        factory = lambda **kwargs: _ClapStream(emit_claps=True, **kwargs)
        self.assertTrue(main.wait_for_startup_claps(timeout=1, stream_factory=factory))

    def test_gate_can_be_bypassed_for_missing_microphone_access(self):
        with patch.dict(os.environ, {"JARVIS_SKIP_CLAP_GATE": "1"}):
            self.assertTrue(main.wait_for_startup_claps(stream_factory=lambda **_: self.fail("opened mic")))

    def test_gate_times_out_without_claps(self):
        factory = lambda **kwargs: _ClapStream(emit_claps=False, **kwargs)
        self.assertFalse(main.wait_for_startup_claps(timeout=0.06, stream_factory=factory))


if __name__ == "__main__":
    unittest.main()
