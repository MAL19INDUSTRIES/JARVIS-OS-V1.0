import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from actions import computer_settings, file_controller, flight_finder, instagram_browser, weather_report, youtube_video
from agent import error_handler
from agent.task_queue import TaskPriority, TaskQueue
from api import status as api_status
from awareness.engine import AwarenessEngine
from core import api_key_validator, live_model
from memory import answer_cache, config_manager, memory_manager


class CoreResilienceTests(unittest.TestCase):
    def test_api_key_normalization_handles_shell_assignment_and_smart_quotes(self):
        token = "AIza" + "a" * 30
        self.assertEqual(
            api_key_validator.normalize_gemini_api_key(f"export GEMINI_API_KEY=“{token}”"),
            token,
        )
        self.assertFalse(api_key_validator._basic_key_check("short").valid)

    def test_live_model_selection_prefers_native_audio(self):
        models = [
            SimpleNamespace(name="models/live-basic", supported_actions=["bidiGenerateContent"]),
            SimpleNamespace(name="models/native-audio-best", supported_actions=["bidiGenerateContent"]),
        ]
        client = SimpleNamespace(models=SimpleNamespace(list=lambda: models))
        with tempfile.TemporaryDirectory() as directory:
            selected = live_model.pick_live_model(client, Path(directory) / "missing.json")
        self.assertEqual(selected, "models/native-audio-best")

    def test_live_model_falls_back_when_listing_fails(self):
        client = SimpleNamespace(models=SimpleNamespace(list=lambda: (_ for _ in ()).throw(RuntimeError("offline"))))
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text(json.dumps({"live_model": "models/test-live"}), encoding="utf-8")
            self.assertEqual(live_model.pick_live_model(client, config), "models/test-live")

    def test_corrupt_memory_recovers_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            memory_manager, "MEMORY_PATH", Path(directory) / "memory.json"
        ):
            memory_manager.MEMORY_PATH.write_text("{broken", encoding="utf-8")
            self.assertEqual(memory_manager.load_memory()["identity"], {})
            memory_manager.update_memory({"identity": {"name": {"value": "Mirsab"}}})
            self.assertEqual(memory_manager.load_memory()["identity"]["name"]["value"], "Mirsab")

    def test_answer_cache_ignores_commands_and_time_sensitive_questions(self):
        self.assertFalse(answer_cache.is_cacheable_question("Open Safari"))
        self.assertFalse(answer_cache.is_cacheable_question("What is the weather today?"))
        self.assertTrue(answer_cache.is_cacheable_question("What is polymorphism?"))

    def test_answer_cache_round_trip_uses_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            answer_cache, "CACHE_PATH", Path(directory) / "answers.json"
        ):
            answer_cache.save_cached_answer("What is polymorphism?", "One interface, multiple implementations.")
            self.assertIn("multiple implementations", answer_cache.get_cached_answer("What is polymorphism?"))

    def test_error_handler_stops_retrying_at_limit_without_network(self):
        result = error_handler.analyze_error({"step": "test"}, "failed", attempt=2, max_attempts=2)
        self.assertEqual(result["decision"], error_handler.ErrorDecision.REPLAN)

    def test_api_status_round_trip_and_clear(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            api_status, "STATUS_PATH", Path(directory) / "status.json"
        ):
            api_status.write_status({"state": "ready"})
            self.assertEqual(api_status.read_status()["state"], "ready")
            api_status.clear_status()
            self.assertEqual(api_status.read_status(), {})

    def test_corrupt_api_config_recovers_without_exception(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            config_manager, "CONFIG_FILE", Path(directory) / "api_keys.json"
        ), patch.object(config_manager, "CONFIG_DIR", Path(directory)):
            config_manager.CONFIG_FILE.write_text("not-json", encoding="utf-8")
            self.assertEqual(config_manager.load_api_keys(), {})
            config_manager.save_api_keys("test-token-value-1234567890")
            self.assertEqual(config_manager.load_api_keys()["gemini_api_key"], "test-token-value-1234567890")

    def test_task_queue_submit_status_and_cancel_without_worker(self):
        queue = TaskQueue()
        task_id = queue.submit("QA task", priority=TaskPriority.HIGH)
        self.assertEqual(queue.get_status(task_id)["status"], "pending")
        self.assertTrue(queue.cancel(task_id))
        self.assertEqual(queue.get_status(task_id)["status"], "cancelled")

    def test_awareness_state_is_copied_and_bounded(self):
        engine = AwarenessEngine(lambda *_: None)
        engine.set_goal("Audit JARVIS")
        for index in range(25):
            engine.record_event(f"event-{index}")
        state = engine.get_state()
        self.assertEqual(state.current_goal, "Audit JARVIS")
        self.assertEqual(len(state.recent_events), 20)


class PureActionContractTests(unittest.TestCase):
    def test_youtube_url_parsing(self):
        video_id = "abcdefghijk"
        self.assertEqual(youtube_video._extract_video_id(f"https://youtu.be/{video_id}"), video_id)
        self.assertTrue(youtube_video._is_valid_youtube_url("https://youtube.com/watch?v=abcdefghijk"))

    def test_flight_url_contains_route_and_passengers(self):
        url = flight_finder._build_google_flights_url("SFO", "LHR", "2026-08-01", passengers=2)
        self.assertIn("SFO", url)
        self.assertIn("LHR", url)
        self.assertIn("adults=2", url)

    def test_instagram_name_matching_detects_ambiguity(self):
        candidates = [{"name": "Alex Smith"}, {"name": "Alex Smyth"}, {"name": "Jordan"}]
        matches, ambiguous = instagram_browser._best_name_matches("Alex", candidates)
        self.assertGreaterEqual(len(matches), 2)
        self.assertTrue(ambiguous)

    def test_computer_power_target_must_be_explicit(self):
        self.assertFalse(computer_settings._has_explicit_computer_power_target({}, "restart JARVIS", None))
        self.assertTrue(computer_settings._has_explicit_computer_power_target({}, "restart my computer", None))

    def test_weather_failure_is_returned_instead_of_raised(self):
        with patch.object(weather_report.webbrowser, "open", return_value=False):
            result = weather_report.weather_action({"city": "London"})
        self.assertIn("couldn't open", result)

    def test_file_controller_is_confined_to_configured_safe_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "hello.txt").write_text("hello", encoding="utf-8")
            with patch.object(file_controller, "_SAFE_ROOTS", [root]):
                self.assertIn("hello.txt", file_controller.list_files(str(root)))
                self.assertIn("Access denied", file_controller.list_files(str(root.parent)))


if __name__ == "__main__":
    unittest.main()
