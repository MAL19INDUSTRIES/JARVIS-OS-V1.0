import json
import os
import asyncio
import importlib.util
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core import qa_mode
from core.qa_audit import EXPECTED_TOOLS, declared_tools, repository_findings
from core.qa_report import CheckResult, Finding, QAReport, redact


ROOT = Path(__file__).resolve().parent.parent


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QAModeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "JARVIS_QA_MODE": "1",
            "JARVIS_QA_WORKSPACE": self.tmp.name,
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_normal_runtime_is_unchanged_when_qa_mode_is_off(self):
        with patch.dict(os.environ, {"JARVIS_QA_MODE": "0"}, clear=False):
            self.assertTrue(qa_mode.guard_tool_call("send_message", {}).allowed)

    def test_real_message_send_is_always_blocked(self):
        decision = qa_mode.guard_tool_call("send_message", {"receiver": "Test"})
        self.assertFalse(decision.allowed)
        self.assertIn("never sends", decision.reason)

    def test_power_actions_remain_blocked_even_with_desktop_opt_in(self):
        with patch.dict(os.environ, {"JARVIS_QA_ALLOW_DESKTOP": "1"}, clear=False):
            decision = qa_mode.guard_tool_call("computer_settings", {"action": "shutdown"})
        self.assertFalse(decision.allowed)

    def test_browser_and_drafts_require_separate_opt_ins(self):
        self.assertFalse(qa_mode.guard_tool_call("browser_control", {"action": "navigate"}).allowed)
        self.assertFalse(qa_mode.guard_tool_call("prepare_message_reply", {}).allowed)
        with patch.dict(os.environ, {
            "JARVIS_QA_ALLOW_BROWSER": "1",
            "JARVIS_QA_ALLOW_DRAFTS": "1",
        }, clear=False):
            self.assertTrue(qa_mode.guard_tool_call("browser_control", {"action": "navigate"}).allowed)
            self.assertTrue(qa_mode.guard_tool_call("prepare_message_reply", {}).allowed)

    def test_file_tools_are_confined_to_qa_workspace(self):
        inside = str(Path(self.tmp.name) / "sample.txt")
        self.assertTrue(qa_mode.guard_tool_call("file_controller", {"action": "write", "path": inside}).allowed)
        self.assertFalse(qa_mode.guard_tool_call("file_controller", {"action": "write", "path": "/tmp/outside.txt"}).allowed)
        self.assertFalse(qa_mode.guard_tool_call("dev_agent", {"description": "build"}).allowed)

    def test_game_mutation_and_unapproved_reminders_are_blocked(self):
        self.assertTrue(qa_mode.guard_tool_call("game_updater", {"action": "status"}).allowed)
        self.assertFalse(qa_mode.guard_tool_call("game_updater", {"action": "install"}).allowed)
        self.assertFalse(qa_mode.guard_tool_call("reminder", {"action": "create"}).allowed)

    def test_media_control_requires_supervised_desktop_opt_in(self):
        self.assertFalse(qa_mode.guard_tool_call("media_control", {"action": "play"}).allowed)
        with patch.dict(os.environ, {"JARVIS_QA_ALLOW_DESKTOP": "1"}, clear=False):
            self.assertTrue(qa_mode.guard_tool_call("media_control", {"action": "pause"}).allowed)

    def test_email_access_requires_explicit_qa_opt_in(self):
        self.assertFalse(qa_mode.guard_tool_call("email_control", {"action": "inbox"}).allowed)
        with patch.dict(os.environ, {"JARVIS_QA_ALLOW_EMAIL": "1"}, clear=False):
            self.assertTrue(qa_mode.guard_tool_call("email_control", {"action": "inbox"}).allowed)
            self.assertFalse(qa_mode.guard_tool_call("email_control", {"action": "approve"}).allowed)

    def test_live_dispatch_enforces_qa_guard_before_tool_handler(self):
        import main

        jarvis = main.JarvisLive.__new__(main.JarvisLive)
        jarvis.ui = SimpleNamespace(interaction_gated=False)
        call = SimpleNamespace(
            id="qa-call",
            call_id=None,
            name="send_message",
            args={"receiver": "Nobody", "message_text": "test", "platform": "iMessage"},
        )
        response = asyncio.run(jarvis._execute_tool(call))
        self.assertIn("QA SAFETY BLOCK", response.response["result"])

    def test_live_dispatch_is_blocked_until_ui_is_operationally_ready(self):
        import main

        jarvis = main.JarvisLive.__new__(main.JarvisLive)
        jarvis.ui = SimpleNamespace(interaction_gated=False, operational_ready=False)
        call = SimpleNamespace(
            id="startup-call",
            call_id=None,
            name="jarvis_ui_control",
            args={"action": "open_settings"},
        )
        response = asyncio.run(jarvis._execute_tool(call))
        self.assertIn("Startup sequence active", response.response["result"])

    def test_live_quit_tool_requires_explicit_current_user_transcript(self):
        import main

        commands = []
        jarvis = main.JarvisLive.__new__(main.JarvisLive)
        jarvis.ui = SimpleNamespace(
            handle_ui_command=commands.append,
            _win=SimpleNamespace(),
        )
        jarvis._current_input_transcript = ""
        jarvis._last_input_transcript = ""
        jarvis._last_input_transcript_at = 0.0
        blocked = jarvis._intercept_ui_tool_call(
            "jarvis_ui_control", {"action": "quit_jarvis"}
        )
        self.assertIn("Ignored an unverified shutdown request", blocked)
        self.assertEqual(commands, [])

        jarvis._current_input_transcript = "JARVIS, shut yourself down."
        allowed = jarvis._intercept_ui_tool_call(
            "jarvis_ui_control", {"action": "quit_jarvis"}
        )
        self.assertIn("Shutdown queued", allowed)
        self.assertIn(main.SELF_QUIT_GOODBYE, allowed)
        self.assertEqual(commands, [])
        self.assertTrue(jarvis._pending_self_quit)
        self.assertFalse(jarvis._pending_self_quit_farewell_received)

    def test_self_quit_waits_for_farewell_audio_to_finish(self):
        import main

        commands = []
        jarvis = main.JarvisLive.__new__(main.JarvisLive)
        jarvis.ui = SimpleNamespace(handle_ui_command=commands.append)

        jarvis._queue_self_quit_after_farewell()
        self.assertFalse(jarvis._complete_self_quit_after_audio())
        self.assertEqual(commands, [])

        jarvis._mark_self_quit_farewell_received()
        self.assertTrue(jarvis._complete_self_quit_after_audio())
        self.assertEqual(commands, ["Quit JARVIS"])
        self.assertFalse(jarvis._pending_self_quit)
        self.assertFalse(jarvis._pending_self_quit_farewell_received)

    def test_shutdown_is_not_exposed_as_a_gemini_tool_action(self):
        import main

        declaration = next(
            item for item in main.TOOL_DECLARATIONS
            if item.get("name") == "jarvis_ui_control"
        )
        actions = declaration["parameters"]["properties"]["action"]["enum"]
        self.assertNotIn("quit_jarvis", actions)
        self.assertNotIn("action='quit_jarvis'", main._load_system_prompt())
        self.assertIn(main.SELF_QUIT_GOODBYE, main._load_system_prompt())
        self.assertIn("do not claim that you cannot", main._load_system_prompt())

    def test_live_audio_extraction_ignores_non_audio_parts_without_data_shortcut(self):
        import main

        audio = b"\x01\x00" * 12
        part = SimpleNamespace(
            inline_data=SimpleNamespace(data=audio, mime_type="audio/pcm")
        )

        class Response:
            server_content = SimpleNamespace(
                model_turn=SimpleNamespace(parts=[part])
            )

            @property
            def data(self):
                raise AssertionError("SDK response.data shortcut must not be accessed")

        self.assertEqual(main._live_response_audio_bytes(Response()), audio)

    def test_clean_websocket_close_is_recognized_inside_task_group(self):
        import main

        class ConnectionClosedOK(Exception):
            pass

        clean_close = ConnectionClosedOK(
            "sent 1000 (OK); then received 1000 (OK)"
        )
        wrapped = ExceptionGroup("tour pause", [clean_close])
        self.assertTrue(main._is_normal_live_close_error(clean_close))
        self.assertTrue(main._is_normal_live_close_error(wrapped))
        self.assertFalse(
            main._is_normal_live_close_error(RuntimeError("network failed"))
        )

    def test_connection_reset_is_retryable_inside_task_group(self):
        import main

        reset = ConnectionResetError(54, "Connection reset by peer")
        wrapped = ExceptionGroup("live connection", [reset])
        self.assertTrue(main._is_transient_live_connection_error(reset))
        self.assertTrue(main._is_transient_live_connection_error(wrapped))
        self.assertFalse(
            main._is_transient_live_connection_error(
                ValueError("invalid configuration")
            )
        )

    def test_quota_failure_is_recognized_inside_task_group(self):
        import main

        quota = RuntimeError(
            "1011: You exceeded your current quota; check plan and billing details"
        )
        wrapped = ExceptionGroup("live connection", [quota])
        self.assertTrue(main._is_quota_error(quota))
        self.assertTrue(main._is_quota_error(wrapped))
        self.assertFalse(main._is_quota_error(RuntimeError("connection reset")))

    def test_pcm16_resampling_tracks_requested_sample_rate(self):
        import main
        import numpy as np

        source = np.arange(480, dtype="<i2").tobytes()
        downsampled = main._resample_pcm16(source, 48000, 16000)
        upsampled = main._resample_pcm16(source, 24000, 48000)
        self.assertEqual(len(downsampled), 160 * 2)
        self.assertEqual(len(upsampled), 960 * 2)
        self.assertEqual(main._resample_pcm16(source, 48000, 48000), source)

    def test_audio_candidates_prefer_the_default_devices_native_rate(self):
        import main

        devices = [
            {
                "name": "Mac Speakers",
                "max_input_channels": 0,
                "max_output_channels": 2,
                "default_samplerate": 48000.0,
            },
            {
                "name": "Mac Microphone",
                "max_input_channels": 1,
                "max_output_channels": 0,
                "default_samplerate": 44100.0,
            },
        ]
        default = SimpleNamespace(device=(1, 0))
        with (
            patch.object(main.sd, "query_devices", return_value=devices),
            patch.object(main.sd, "default", default),
            patch.object(main.sd, "check_input_settings"),
            patch.object(main.sd, "check_output_settings"),
        ):
            inputs = main._audio_stream_candidates("input", 16000)
            outputs = main._audio_stream_candidates("output", 24000)

        self.assertEqual(inputs[0], (1, 44100, "Mac Microphone"))
        self.assertEqual(outputs[0], (0, 48000, "Mac Speakers"))

    def test_microphone_open_failure_does_not_escape_the_audio_task(self):
        import main

        logs = []
        jarvis = main.JarvisLive.__new__(main.JarvisLive)
        jarvis.ui = SimpleNamespace(muted=False, write_log=logs.append)
        jarvis._speaking_lock = __import__("threading").Lock()
        jarvis._is_speaking = False
        jarvis._mode_switching = __import__("threading").Event()
        jarvis._shutdown_requested = __import__("threading").Event()
        jarvis._session_stop_event = None
        jarvis._audio_warning_kinds = set()
        jarvis.out_queue = asyncio.Queue(maxsize=10)

        with (
            patch.object(
                main,
                "_audio_stream_candidates",
                return_value=[(0, 48000, "Broken microphone")],
            ),
            patch.object(
                main.sd,
                "InputStream",
                side_effect=RuntimeError("Internal PortAudio error [PaErrorCode -9986]"),
            ),
        ):
            asyncio.run(jarvis._listen_audio())

        self.assertTrue(any("Microphone unavailable" in entry for entry in logs))

    def test_quota_failure_stops_reconnect_loop_after_one_attempt(self):
        import main

        attempts = []
        logs = []

        class QuotaConnection:
            async def __aenter__(self):
                raise RuntimeError(
                    "1011: You exceeded your current quota; check plan and billing details"
                )

            async def __aexit__(self, *_args):
                return False

        class Live:
            def connect(self, **kwargs):
                attempts.append(kwargs)
                return QuotaConnection()

        fake_client = SimpleNamespace(aio=SimpleNamespace(live=Live()))
        jarvis = main.JarvisLive.__new__(main.JarvisLive)
        jarvis._api_key = "test-key"
        jarvis.ui = SimpleNamespace(
            write_log=logs.append,
            set_state=lambda _state: None,
        )
        jarvis._shutdown_requested = __import__("threading").Event()
        jarvis.runtime_limit_seconds = None
        jarvis.required_unlock_path = None
        jarvis.cloud_safe = True
        jarvis._build_config = lambda: {}
        jarvis.session = None
        jarvis.audio_in_queue = None
        jarvis.out_queue = None
        jarvis._turn_done_event = None
        jarvis._session_stop_event = None

        with (
            patch.object(main.genai, "Client", return_value=fake_client),
            patch.object(main, "pick_live_model", return_value="models/test-live"),
        ):
            asyncio.run(jarvis.run())

        self.assertEqual(len(attempts), 1)
        self.assertTrue(any("quota is exhausted" in entry for entry in logs))

    def test_live_reconnect_backoff_is_bounded(self):
        import main

        self.assertEqual(
            [main._live_reconnect_delay(attempt) for attempt in range(1, 9)],
            [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0],
        )

    def test_reconnect_wait_exits_immediately_during_shutdown(self):
        import main

        jarvis = main.JarvisLive.__new__(main.JarvisLive)
        jarvis._shutdown_requested = __import__("threading").Event()
        jarvis._shutdown_requested.set()
        started = time.perf_counter()
        asyncio.run(jarvis._wait_before_reconnect(30.0))
        self.assertLess(time.perf_counter() - started, 0.1)

    def test_tour_lock_tracks_state_without_closing_on_release(self):
        import main

        jarvis = main.JarvisLive.__new__(main.JarvisLive)
        jarvis.session = None
        jarvis._loop = None
        jarvis._tour_active = False

        jarvis.set_tour_active(True)
        self.assertTrue(jarvis._tour_active)
        jarvis.set_tour_active(False)
        self.assertFalse(jarvis._tour_active)

    def test_independent_tool_batch_executes_concurrently_and_preserves_order(self):
        import main

        jarvis = main.JarvisLive.__new__(main.JarvisLive)

        async def execute(call):
            await asyncio.sleep(0.06)
            return call.name

        jarvis._execute_tool = AsyncMock(side_effect=execute)
        calls = [
            SimpleNamespace(name="weather_report"),
            SimpleNamespace(name="web_search"),
        ]
        started = time.perf_counter()
        results = asyncio.run(jarvis._execute_tool_batch(calls))
        elapsed = time.perf_counter() - started
        self.assertEqual(results, ["weather_report", "web_search"])
        self.assertLess(elapsed, 0.105)

    def test_mutating_tool_batch_remains_sequential(self):
        import main

        jarvis = main.JarvisLive.__new__(main.JarvisLive)

        async def execute(call):
            await asyncio.sleep(0.04)
            return call.name

        jarvis._execute_tool = AsyncMock(side_effect=execute)
        calls = [
            SimpleNamespace(name="send_message"),
            SimpleNamespace(name="computer_settings"),
        ]
        started = time.perf_counter()
        results = asyncio.run(jarvis._execute_tool_batch(calls))
        elapsed = time.perf_counter() - started
        self.assertEqual(results, ["send_message", "computer_settings"])
        self.assertGreaterEqual(elapsed, 0.07)

    def test_live_config_uses_fast_end_of_speech_detection(self):
        import main

        jarvis = main.JarvisLive.__new__(main.JarvisLive)
        jarvis.voice_name = "charon"
        with (
            patch.object(main, "load_memory", return_value={}),
            patch.object(main, "format_memory_for_prompt", return_value=""),
            patch.object(main, "_load_system_prompt", return_value="test prompt"),
        ):
            config = jarvis._build_config()

        detection = config.realtime_input_config.automatic_activity_detection
        self.assertEqual(detection.silence_duration_ms, main.LIVE_VAD_SILENCE_MS)
        self.assertEqual(main.LIVE_VAD_SILENCE_MS, 200)
        self.assertEqual(config.thinking_config.thinking_budget, 0)
        self.assertEqual(
            detection.start_of_speech_sensitivity,
            main.types.StartSensitivity.START_SENSITIVITY_HIGH,
        )
        self.assertEqual(
            detection.end_of_speech_sensitivity,
            main.types.EndSensitivity.END_SENSITIVITY_HIGH,
        )


class QAReportTests(unittest.TestCase):
    def test_report_redacts_api_keys_and_token_fields(self):
        fake_key = "AIza" + "A" * 35
        cleaned = redact(f"api_key={fake_key} token=private-value")
        self.assertNotIn(fake_key, cleaned)
        self.assertNotIn("private-value", cleaned)
        self.assertIn("[REDACTED]", cleaned)

    def test_report_writes_markdown_and_json(self):
        report = QAReport.create("automated")
        report.checks.append(CheckResult("sample", "passed", 0.1, "ok"))
        report.findings.append(Finding("P2", "Example", "QA", "Impact"))
        with tempfile.TemporaryDirectory() as directory:
            json_path, markdown_path = report.write(Path(directory))
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "automated")
            self.assertIn("[P2] Example", markdown_path.read_text(encoding="utf-8"))


class ToolContractTests(unittest.TestCase):
    def test_declared_tool_inventory_is_complete_and_unique(self):
        tools = declared_tools(ROOT / "main.py")
        self.assertEqual(set(tools), EXPECTED_TOOLS)
        self.assertEqual(len(tools), len(set(tools)))

    def test_every_declared_tool_has_a_dispatch_path(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        for name in declared_tools(ROOT / "main.py"):
            self.assertIn(f'name == "{name}"', source, name)

    def test_live_tool_schemas_have_names_parameters_and_properties(self):
        import main

        for declaration in main.TOOL_DECLARATIONS:
            self.assertIn("name", declaration)
            parameters = declaration.get("parameters")
            self.assertIsInstance(parameters, dict, declaration["name"])
            self.assertIsInstance(parameters.get("properties"), dict, declaration["name"])
            self.assertIsInstance(parameters.get("required", []), list, declaration["name"])

    def test_repository_audit_returns_structured_findings(self):
        for finding in repository_findings(ROOT):
            self.assertIn(finding.severity, {"P0", "P1", "P2", "P3"})
            self.assertTrue(finding.title)
            self.assertTrue(finding.impact)


class AutomatedChecklistTests(unittest.TestCase):
    def test_automated_probe_accounts_for_every_live_case(self):
        qa_script = _load_script("qa")
        probe_source = (ROOT / "scripts" / "qa_checklist_probe.py").read_text(encoding="utf-8")
        for name, _instructions in qa_script.LIVE_CASES:
            self.assertIn(f'"{name}"', probe_source, name)

    def test_localhost_restriction_failure_is_reported_as_blocked_not_crash(self):
        probe = _load_script("qa_checklist_probe")
        with patch.object(probe, "ThreadingHTTPServer", side_effect=PermissionError("blocked")):
            success, evidence, notes = probe._browser_probe()
        self.assertIsNone(success)
        self.assertIn("blocked", evidence["local_server_error"])
        self.assertIn("blocked", notes)

    def test_automated_file_probe_stays_inside_workspace(self):
        probe = _load_script("qa_checklist_probe")
        with tempfile.TemporaryDirectory() as directory:
            passed, evidence, _notes = probe._file_probe(Path(directory))
        self.assertTrue(passed)
        self.assertIn("Access denied", evidence["outside_write"])


if __name__ == "__main__":
    unittest.main()
