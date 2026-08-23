import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from actions import deep_research as research
from agent import planner
from agent.task_queue import TaskQueue
from core.qa_audit import declared_tools


class DeepResearchTests(unittest.TestCase):
    def setUp(self):
        research._pending_parameters = None
        research._pending_created_at = 0.0
        research._latest_result = None

    def test_request_normalizes_depth_focus_and_source_limit(self):
        request = research.ResearchRequest.from_parameters({
            "topic": "Local AI privacy",
            "depth": "thorough",
            "focus_areas": "privacy, Mac performance",
            "max_sources": 200,
        })

        self.assertEqual(request.question, "Local AI privacy")
        self.assertEqual(request.depth, "deep")
        self.assertEqual(request.focus_areas, ["privacy", "Mac performance"])
        self.assertEqual(request.max_sources, 50)

    def test_grounding_metadata_extracts_only_web_urls(self):
        response = SimpleNamespace(candidates=[SimpleNamespace(
            grounding_metadata=SimpleNamespace(grounding_chunks=[
                SimpleNamespace(web=SimpleNamespace(title="Primary study", uri="https://example.org/study")),
                SimpleNamespace(web=SimpleNamespace(title="Unsafe", uri="file:///tmp/result")),
                SimpleNamespace(web=None),
            ])
        )])

        self.assertEqual(research._extract_grounding_sources(response), [{
            "title": "Primary study",
            "url": "https://example.org/study",
        }])

    def test_build_keeps_cited_report_in_memory_without_writing(self):
        progress = []
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "decision.md"
            query_results = [
                ("Evidence from the primary study.", [{
                    "title": "Primary study", "url": "https://example.org/study",
                }]),
                ("Evidence from the benchmark.", [
                    {"title": "Primary duplicate", "url": "https://example.org/study/"},
                    {"title": "Benchmark", "url": "https://example.net/benchmark"},
                ]),
            ]
            with (
                patch("google.genai.Client", return_value=object()),
                patch.object(research, "_api_key", return_value="test-key"),
                patch.object(research, "_plan_queries", return_value=["primary evidence", "benchmarks"]),
                patch.object(research, "_research_query", side_effect=query_results),
                patch.object(research, "_synthesize", return_value="## Answer\nSupported conclusion [1] with context [2]."),
            ):
                result = research.build_deep_research(
                    {
                        "question": "Which option is best?",
                        "output_path": str(output),
                        "_persona_name": "ULTRON",
                    },
                    progress_callback=lambda **update: progress.append(update),
                )

            self.assertEqual(len(result.sources), 2)
            self.assertEqual(result.artifacts, [])
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".evidence.json").exists())
            self.assertIn("Supported conclusion [1]", result.report_markdown)
            self.assertIn("CREATED BY ULTRON", result.report_markdown)
            self.assertEqual(result.evidence["persona"], "ULTRON")
            self.assertIn("[Primary study](https://example.org/study)", result.report_markdown)
            self.assertEqual(result.evidence["queries"], ["primary evidence", "benchmarks"])
            self.assertEqual(len(result.evidence["evidence"]), 2)
            self.assertEqual(progress[-1]["percent"], 100)
            self.assertEqual(progress[-1]["phase"], "Deep research complete")

    def test_cancelled_request_never_creates_api_client(self):
        cancel_flag = threading.Event()
        cancel_flag.set()
        with patch("google.genai.Client") as client:
            with self.assertRaises(research.ResearchCancelled):
                research.build_deep_research({"question": "Cancelled"}, cancel_flag=cancel_flag)
        client.assert_not_called()

    def test_queue_uses_specialized_research_job(self):
        queue = Mock()
        queue.submit_job.return_value = "abc123"
        with patch("agent.task_queue.get_queue", return_value=queue):
            message = research.queue_deep_research({"question": "Research batteries"})

        self.assertIn("abc123", message)
        kwargs = queue.submit_job.call_args.kwargs
        self.assertEqual(kwargs["kind"], "research")
        self.assertTrue(callable(kwargs["runner"]))

    def test_queue_completion_keeps_report_in_memory_and_requests_detailed_summary(self):
        queue = Mock()
        queue.submit_job.return_value = "report1"
        speak = Mock()
        completed = research.ResearchResult(
            question="Battery recycling",
            report_markdown="# Report\n\nDetailed evidence and uncertainty.",
            evidence={},
            sources=[{"title": "Study", "url": "https://example.org"}],
        )
        with (
            patch("agent.task_queue.get_queue", return_value=queue),
            patch.object(research, "build_deep_research", return_value=completed),
        ):
            research.queue_deep_research(
                {"question": "Battery recycling"},
                speak=speak,
            )
            runner = queue.submit_job.call_args.kwargs["runner"]
            returned = runner(threading.Event(), lambda **update: None)

        self.assertIs(returned, completed)
        self.assertIs(research._get_latest_result(), completed)
        prompt = speak.call_args.args[0]
        self.assertIn("full, detailed spoken summary", prompt)
        self.assertIn("save it to their Files", prompt)
        self.assertIn("save it to their Desktop", prompt)
        self.assertIn("read the entire report aloud", prompt)

    def test_research_task_is_not_written_to_persistent_task_history(self):
        queue = TaskQueue(max_concurrent=1)
        task_id = queue.submit_job(
            "Deep research: private topic",
            lambda cancel_flag, progress: "complete",
            kind="research",
        )
        task = queue._tasks[task_id]
        task.status = task.status.RUNNING
        queue._active_count = 1
        with patch("agent.task_queue.record_task") as record:
            queue._run_task(task)

        record.assert_not_called()

    def test_background_mode_opens_labeled_status_surface_only(self):
        queue = Mock()
        queue.submit_job.return_value = "background1"
        player = Mock()
        with patch("agent.task_queue.get_queue", return_value=queue):
            research.queue_deep_research(
                {"question": "Research batteries"},
                player=player,
                visible=False,
            )

        player.show_research_progress.assert_called_once_with("Research batteries")

    def test_visible_mode_opens_browser_instead_of_progress_surface(self):
        queue = Mock()
        queue.submit_job.return_value = "visible1"
        player = Mock()
        with patch("agent.task_queue.get_queue", return_value=queue):
            message = research.queue_deep_research(
                {"question": "Research batteries"},
                player=player,
                visible=True,
            )

        player.show_research_progress.assert_not_called()
        self.assertIn("controlled browser", message)

    def test_visible_research_searches_and_opens_a_source_tab(self):
        results = [{
            "title": "Battery study",
            "snippet": "Measured recycling outcomes.",
            "url": "https://example.org/battery-study",
        }]
        browser_results = [
            "Opened: https://www.google.com/search?q=batteries",
            "Opened: https://example.org/battery-study",
            "Full source text from the study.",
        ]
        with (
            patch.object(research, "_search_web", return_value=results),
            patch("actions.browser_control.browser_control", side_effect=browser_results) as browser,
        ):
            findings, sources = research._research_query(
                object(),
                "batteries",
                "Which battery is best?",
                visible=True,
                opened_urls=set(),
            )

        actions = [call.args[0]["action"] for call in browser.call_args_list]
        self.assertEqual(actions, ["search", "new_tab", "get_text"])
        self.assertIn("Full source text from the study", findings)
        self.assertEqual(sources[0]["url"], "https://example.org/battery-study")

    def test_search_uses_second_http_engine_when_first_is_unavailable(self):
        bing_results = [{
            "title": "Independent benchmark",
            "snippet": "Comparison results.",
            "url": "https://benchmark.example/results",
        }]
        with (
            patch.object(research, "_duckduckgo_html_search", side_effect=RuntimeError("blocked")),
            patch.object(research, "_bing_html_search", return_value=bing_results) as bing,
        ):
            results = research._search_web("AI model benchmarks", max_results=3)

        bing.assert_called_once()
        self.assertEqual(results, bing_results)

    def test_quota_failure_uses_source_first_report_instead_of_failing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "quota-fallback.md"
            with (
                patch("google.genai.Client", return_value=object()),
                patch.object(research, "_api_key", return_value="test-key"),
                patch.object(research, "_plan_queries", return_value=["battery evidence"]),
                patch.object(research, "_research_query", return_value=(
                    "Battery study evidence.",
                    [{"title": "Study", "url": "https://example.org/study"}],
                )),
                patch.object(research, "_synthesize", side_effect=RuntimeError("429 RESOURCE_EXHAUSTED")),
            ):
                result = research.build_deep_research({
                    "question": "Which battery is best?",
                    "output_path": str(output),
                })

            self.assertFalse(output.exists())
            self.assertIn("source-first fallback", result.warnings[0])
            self.assertIn("JARVIS reviewed 1 distinct web sources", result.report_markdown)

    def test_save_and_read_actions_require_a_completed_in_memory_report(self):
        self.assertIn(
            "no completed Deep Research report",
            research.request_deep_research({"result_action": "read_report"}),
        )

    def test_report_is_written_only_after_explicit_save_action(self):
        result = research.ResearchResult(
            question="Battery recycling",
            report_markdown="# Battery recycling\n\nDetailed findings.",
            evidence={"sources": []},
            sources=[],
        )
        research._remember_latest_result(result)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "battery-report.md"
            message = research.request_deep_research({
                "result_action": "save_files",
                "output_path": str(output),
            })

            self.assertTrue(output.exists())
            self.assertEqual(output.read_text(encoding="utf-8"), result.report_markdown)
            self.assertIn(str(output), message)

    def test_read_action_returns_the_complete_unsaved_report(self):
        result = research.ResearchResult(
            question="Battery recycling",
            report_markdown="# Full report\n\nEvery material finding.",
            evidence={},
            sources=[],
        )
        research._remember_latest_result(result)

        message = research.request_deep_research({"result_action": "read_report"})
        self.assertIn("Read the complete report", message)
        self.assertIn("Every material finding", message)
        self.assertIn("Do not claim it has been saved", message)

    def test_initial_request_waits_for_display_choice(self):
        with patch.object(research, "queue_deep_research") as queue:
            message = research.request_deep_research({
                "question": "Research battery recycling",
                "depth": "deep",
                "execution_mode": "ask",
            })

        queue.assert_not_called()
        self.assertIn("I have not started it", message)
        self.assertIn("background", message)
        self.assertIn("opening the browser", message)
        self.assertIn("visiting the sources", message)

    def test_visible_confirmation_starts_remembered_request(self):
        research.request_deep_research({
            "question": "Research battery recycling",
            "depth": "deep",
            "execution_mode": "ask",
        })
        with patch.object(research, "queue_deep_research", return_value="started") as queue:
            result = research.request_deep_research({"execution_mode": "visible"})

        self.assertEqual(result, "started")
        self.assertEqual(queue.call_args.args[0]["question"], "Research battery recycling")
        self.assertEqual(queue.call_args.args[0]["depth"], "deep")
        self.assertTrue(queue.call_args.kwargs["visible"])

    def test_visible_mode_cannot_skip_the_initial_choice(self):
        with patch.object(research, "queue_deep_research") as queue:
            message = research.request_deep_research({
                "question": "Research battery recycling",
                "execution_mode": "visible",
            })

        queue.assert_not_called()
        self.assertEqual(message, research.RUN_MODE_QUESTION)

    def test_background_confirmation_does_not_open_live_view(self):
        research.request_deep_research({
            "question": "Research battery recycling",
            "execution_mode": "ask",
        })
        with patch.object(research, "queue_deep_research", return_value="started") as queue:
            research.request_deep_research({"execution_mode": "background"})

        self.assertFalse(queue.call_args.kwargs["visible"])

    def test_live_tool_contract_declares_deep_research_once(self):
        project_root = Path(__file__).resolve().parent.parent
        tools = declared_tools(project_root / "main.py")
        self.assertEqual(tools.count("deep_research"), 1)

    def test_planner_fallback_keeps_deep_research_on_dedicated_action(self):
        plan = planner._fallback_plan("Do deep research on solid-state batteries")
        self.assertEqual(plan["steps"][0]["tool"], "deep_research")
        self.assertEqual(plan["steps"][0]["parameters"]["depth"], "deep")

    def test_completed_research_job_announces_report_result(self):
        spoken = []
        queue = TaskQueue(max_concurrent=1)

        class Result:
            artifacts = ["report.md", "report.evidence.json"]
            warnings = []

            def __str__(self):
                return "Deep research complete. Reviewed 12 sources. Report: report.md"

        task_id = queue.submit_job(
            "Deep research: batteries",
            lambda cancel_flag, progress: Result(),
            speak=spoken.append,
            kind="research",
        )
        task = queue._tasks[task_id]
        task.status = task.status.RUNNING
        queue._active_count = 1
        queue._run_task(task)

        self.assertEqual(spoken, ["Deep research complete. Reviewed 12 sources. Report: report.md"])

    def test_cancelling_queued_visible_job_updates_its_view(self):
        cancelled = []
        queue = TaskQueue(max_concurrent=1)
        task_id = queue.submit_job(
            "Deep research: batteries",
            lambda cancel_flag, progress: None,
            on_cancel=lambda: cancelled.append(True),
            kind="research",
        )

        self.assertTrue(queue.cancel(task_id))
        self.assertEqual(cancelled, [True])
        self.assertEqual(queue.get_status(task_id)["phase"], "Cancelled")


if __name__ == "__main__":
    unittest.main()
