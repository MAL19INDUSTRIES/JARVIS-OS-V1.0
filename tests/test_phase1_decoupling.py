import asyncio
import unittest
from types import SimpleNamespace

from core.jarvis_client import JarvisClient
import main


class StubClient:
    def __init__(self):
        self.on_text_command = None
        self.on_mode_change = None
        self.muted = False
        self.current_file = None
        self.current_mode = "jarvis"
        self._voice_combo = None
        self.events = []

    def write_log(self, text):
        self.events.append(("log", text))

    def set_state(self, state):
        self.events.append(("state", state))

    def show_subtitle(self, text):
        self.events.append(("subtitle", text))

    def clear_subtitle(self):
        self.events.append(("subtitle", None))

    def activate_mode(self, mode):
        self.current_mode = mode
        self.events.append(("mode", mode))

    def set_graphics_quality(self, quality):
        self.events.append(("graphics", quality))

    def sync_voice_display(self, voice_name):
        self.events.append(("voice", voice_name))

    def handle_ui_command(self, action):
        self.events.append(("ui", action))


class PhaseOneDecouplingTests(unittest.TestCase):
    def test_desktop_adapter_exposes_the_engine_contract(self):
        from ui import JarvisUI

        required_members = {
            "on_text_command",
            "on_mode_change",
            "muted",
            "current_file",
            "current_mode",
            "_voice_combo",
            "write_log",
            "set_state",
            "show_subtitle",
            "clear_subtitle",
            "activate_mode",
            "set_graphics_quality",
            "sync_voice_display",
            "handle_ui_command",
        }

        self.assertFalse(required_members - set(dir(JarvisUI)))

    def test_client_protocol_and_text_callback_are_wired(self):
        client = StubClient()
        self.assertIsInstance(client, JarvisClient)

        jarvis = main.JarvisLive(client)

        self.assertIs(jarvis.client, client)
        self.assertIs(jarvis.ui, client)
        self.assertEqual(client.on_text_command, jarvis._on_text_command)

    def test_desktop_mode_keeps_the_complete_tool_inventory(self):
        client = StubClient()
        jarvis = main.JarvisLive(client)

        self.assertFalse(jarvis.cloud_safe)
        self.assertEqual(jarvis.tool_declarations, main.TOOL_DECLARATIONS)

    def test_cloud_safe_mode_loads_only_the_hosted_allowlist(self):
        client = StubClient()
        jarvis = main.JarvisLive(client, cloud_safe=True)
        names = {item["name"] for item in jarvis.tool_declarations}

        self.assertEqual(names, main.CLOUD_SAFE_ACTIONS)
        self.assertTrue(names.isdisjoint(main.LOCAL_MACHINE_ONLY_ACTIONS))

    def test_cloud_safe_mode_rejects_unadvertised_local_tool_calls(self):
        client = StubClient()
        jarvis = main.JarvisLive(client, cloud_safe=True)
        call = SimpleNamespace(id="local-call", name="open_app", args={})

        response = asyncio.run(jarvis._execute_tool(call))

        self.assertIn("unavailable in cloud-safe mode", response.response["result"])
        self.assertEqual(client.events, [])


if __name__ == "__main__":
    unittest.main()
