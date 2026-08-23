#!/usr/bin/env python3
"""Side-effect-safe capability certification for the development JARVIS build."""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_ROOT = ROOT / ".qa-artifacts"


@dataclass
class CapabilityResult:
    name: str
    status: str
    detail: str
    live_required: bool = False


def _run_tests(*names: str) -> tuple[bool, str]:
    environment = {
        **os.environ,
        "JARVIS_QA_MODE": "1",
        "QT_QPA_PLATFORM": "offscreen",
    }
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "-q", *names],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env=environment,
    )
    output = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part.strip()
    )
    return result.returncode == 0, output[-1200:]


def _tested(name: str, tests: tuple[str, ...], detail: str, *, live: bool = False) -> CapabilityResult:
    passed, output = _run_tests(*tests)
    if passed:
        return CapabilityResult(name, "PASS", detail, live_required=live)
    summary = output.splitlines()[-1] if output else "test process failed"
    return CapabilityResult(name, "FAIL", summary, live_required=live)


def _ai_voice() -> CapabilityResult:
    tests = (
        "tests.test_phase1_decoupling.PhaseOneDecouplingTests.test_client_protocol_and_text_callback_are_wired",
        "tests.test_qa_system.QAModeSafetyTests.test_live_audio_extraction_ignores_non_audio_parts_without_data_shortcut",
        "tests.test_qa_system.QAModeSafetyTests.test_live_config_uses_fast_end_of_speech_detection",
        "tests.test_qa_system.ToolContractTests.test_declared_tool_inventory_is_complete_and_unique",
        "tests.test_startup_clap.StartupClapTests.test_two_distinct_claps_unlock_startup",
    )
    passed, output = _run_tests(*tests)
    if not passed:
        return CapabilityResult("AI / VOICE", "FAIL", output.splitlines()[-1] if output else "contract tests failed", True)
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        inputs = sum(int(device.get("max_input_channels", 0)) > 0 for device in devices)
        outputs = sum(int(device.get("max_output_channels", 0)) > 0 for device in devices)
    except Exception as exc:
        return CapabilityResult("AI / VOICE", "WARN", f"contracts pass; audio enumeration failed: {exc}", True)
    key_ready = bool(os.environ.get("GEMINI_API_KEY", "").strip())
    if not key_ready:
        try:
            from core.secret_store import get_secret_store

            key_ready = bool(get_secret_store().get("gemini_api_key"))
        except Exception:
            key_ready = False
    status = "PASS" if inputs and outputs and key_ready else "WARN"
    detail = f"engine/tool contracts pass; audio inputs={inputs}, outputs={outputs}; Gemini key={'ready' if key_ready else 'missing'}"
    return CapabilityResult("AI / VOICE", status, detail, True)


def _messaging() -> CapabilityResult:
    tests = (
        "tests.test_action_helpers.ActionHelperTests.test_outgoing_message_normalization_adds_terminal_punctuation",
        "tests.test_action_helpers.ActionHelperTests.test_reply_draft_requires_approval_before_send",
        "tests.test_action_helpers.ActionHelperTests.test_instagram_send_prepares_then_approves_visible_draft",
        "tests.test_action_helpers.ActionHelperTests.test_instagram_approval_rejects_a_changed_chat",
        "tests.test_action_helpers.ActionHelperTests.test_instagram_approval_rejects_an_edited_draft",
        "tests.test_action_helpers.ActionHelperTests.test_pending_message_can_be_cancelled_without_sending",
        "tests.test_core_resilience.PureActionContractTests.test_instagram_name_matching_detects_ambiguity",
        "tests.test_qa_system.QAModeSafetyTests.test_real_message_send_is_always_blocked",
    )
    passed, output = _run_tests(*tests)
    if not passed:
        return CapabilityResult("MESSAGING", "FAIL", output.splitlines()[-1] if output else "messaging tests failed", True)
    from actions import send_message

    expected = {
        "Instagram": "_send_instagram",
        "WhatsApp": "_send_whatsapp",
        "iMessage": "_send_imessage",
        "Telegram": "_send_telegram",
        "Signal": "_send_signal",
        "Discord": "_send_discord",
        "Messenger": "_send_messenger",
    }
    broken = [
        platform_name
        for platform_name, handler_name in expected.items()
        if send_message._resolve_platform(platform_name).__name__ != handler_name
    ]
    if broken:
        return CapabilityResult("MESSAGING", "FAIL", "incorrect platform routing: " + ", ".join(broken), True)
    return CapabilityResult(
        "MESSAGING",
        "PASS",
        "Instagram/WhatsApp/iMessage/Telegram/Signal/Discord/Messenger routing and approval boundaries pass",
        True,
    )


def _browser() -> CapabilityResult:
    tests = (
        "tests.test_action_helpers.ActionHelperTests.test_browser_url_normalization_defaults_to_https",
        "tests.test_qa_system.QAModeSafetyTests.test_browser_and_drafts_require_separate_opt_ins",
    )
    passed, output = _run_tests(*tests)
    if not passed:
        return CapabilityResult("BROWSER", "FAIL", output.splitlines()[-1] if output else "browser tests failed")
    try:
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory(prefix="jarvis-browser-self-test-") as directory:
            screenshot = Path(directory) / "local-page.png"
            with sync_playwright() as playwright:
                chrome_error = None
                try:
                    browser = playwright.chromium.launch(channel="chrome", headless=True)
                except Exception as exc:
                    chrome_error = exc
                    try:
                        browser = playwright.chromium.launch(headless=True)
                    except Exception as fallback_exc:
                        raise RuntimeError(
                            f"Chrome channel: {chrome_error}; bundled Chromium: {fallback_exc}"
                        ) from fallback_exc
                page = browser.new_page(viewport={"width": 900, "height": 600})
                page.set_content(
                    "<main style='height:1400px'><input id='q'><button id='go'>Search</button>"
                    "<p id='state'>idle</p></main><script>go.onclick=()=>state.textContent=q.value</script>"
                )
                page.locator("#q").fill("jarvis")
                page.locator("#go").click()
                page.mouse.wheel(0, 500)
                state = page.locator("#state").inner_text()
                page.screenshot(path=str(screenshot))
                browser.close()
            if state != "jarvis" or not screenshot.exists():
                raise RuntimeError("local interaction result was incomplete")
    except Exception as exc:
        return CapabilityResult("BROWSER", "FAIL", f"local Chrome interaction failed: {exc}")
    return CapabilityResult("BROWSER", "PASS", "local navigation surface, click, type, scroll, read, and screenshot pass")


def _system() -> CapabilityResult:
    return _tested(
        "SYSTEM",
        (
            "tests.test_action_helpers.ActionHelperTests.test_open_app_normalization_removes_polite_noise",
            "tests.test_action_helpers.ActionHelperTests.test_successful_macos_direct_launch_has_no_artificial_post_wait",
            "tests.test_core_resilience.PureActionContractTests.test_computer_power_target_must_be_explicit",
            "tests.test_qa_system.QAModeSafetyTests.test_power_actions_remain_blocked_even_with_desktop_opt_in",
        ),
        "app routing and desktop safety contracts pass; real keyboard/mouse actions remain supervised",
        live=True,
    )


def _files() -> CapabilityResult:
    try:
        from actions import file_controller

        with tempfile.TemporaryDirectory(prefix="jarvis-file-self-test-") as directory:
            root = Path(directory)
            destination = root / "moved"
            destination.mkdir()
            with patch.object(file_controller, "_SAFE_ROOTS", [root]), patch.object(
                file_controller,
                "_safe_trash",
                side_effect=lambda target: (target.unlink(), f"Moved to test trash: {target.name}")[1],
            ):
                created = file_controller.create_file(str(root), "audit.txt", "capability audit")
                read = file_controller.read_file(str(root), "audit.txt")
                renamed = file_controller.rename_file(str(root), "audit.txt", "renamed.txt")
                moved = file_controller.move_file(str(root), "renamed.txt", str(destination))
                deleted = file_controller.delete_file(str(destination), "renamed.txt")
            passed = all((
                "File saved" in created,
                "capability audit" in read,
                "Renamed" in renamed,
                "Moved" in moved,
                "test trash" in deleted,
                not (destination / "renamed.txt").exists(),
            ))
            if not passed:
                raise RuntimeError("create/read/rename/move/delete contract did not complete")
    except Exception as exc:
        return CapabilityResult("FILES", "FAIL", str(exc))
    return CapabilityResult("FILES", "PASS", "read, create, rename, move, and recoverable-delete path pass in an isolated workspace")


def _screen_permission() -> bool | None:
    if platform.system() != "Darwin":
        return None
    try:
        graphics = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        preflight = graphics.CGPreflightScreenCaptureAccess
        preflight.restype = ctypes.c_bool
        return bool(preflight())
    except Exception:
        return None


def _vision() -> CapabilityResult:
    tests = (
        "tests.test_action_helpers.ActionHelperTests.test_screen_compression_returns_valid_image",
        "tests.test_action_helpers.ActionHelperTests.test_screen_analysis_hands_finished_result_to_speech",
        "tests.test_action_helpers.ActionHelperTests.test_screen_capture_failure_is_spoken",
        "tests.test_vision_preview.VisionPreviewTests.test_preview_tracks_source_and_lifecycle",
    )
    passed, output = _run_tests(*tests)
    if not passed:
        return CapabilityResult("VISION", "FAIL", output.splitlines()[-1] if output else "vision tests failed", True)
    permission = _screen_permission()
    status = "PASS" if permission is not False else "WARN"
    note = "granted" if permission is True else "not granted" if permission is False else "not queryable"
    return CapabilityResult("VISION", status, f"capture/compression/analysis contracts pass; screen permission={note}", True)


def _agent() -> CapabilityResult:
    return _tested(
        "AGENT",
        (
            "tests.test_core_resilience.CoreResilienceTests.test_task_queue_submit_status_and_cancel_without_worker",
            "tests.test_core_resilience.CoreResilienceTests.test_error_handler_stops_retrying_at_limit_without_network",
            "tests.test_deep_research.DeepResearchTests.test_queue_completion_keeps_report_in_memory_and_requests_detailed_summary",
            "tests.test_deep_research.DeepResearchTests.test_planner_fallback_keeps_deep_research_on_dedicated_action",
            "tests.test_qa_system.ToolContractTests.test_every_declared_tool_has_a_dispatch_path",
        ),
        "planning, queue execution, tool dispatch, and failure recovery contracts pass",
    )


def _memory() -> CapabilityResult:
    return _tested(
        "MEMORY / AWARENESS",
        (
            "tests.test_core_resilience.CoreResilienceTests.test_corrupt_memory_recovers_and_round_trips",
            "tests.test_core_resilience.CoreResilienceTests.test_answer_cache_round_trip_uses_temporary_file",
            "tests.test_core_resilience.CoreResilienceTests.test_awareness_state_is_copied_and_bounded",
            "tests.test_hosted_api.HostedApiTests.test_memory_is_scoped_by_tenant",
        ),
        "memory recovery, answer cache, bounded awareness, and tenant isolation pass",
    )


def run() -> tuple[list[CapabilityResult], Path]:
    checks = (
        _ai_voice,
        _messaging,
        _browser,
        _system,
        _files,
        _vision,
        _agent,
        _memory,
    )
    results: list[CapabilityResult] = []
    print("\nJARVIS CAPABILITY SELF-TEST\n")
    for check in checks:
        result = check()
        results.append(result)
        suffix = " · LIVE CHECK REQUIRED" if result.live_required else ""
        print(f"{result.name:.<24} {result.status}{suffix}")
        print(f"  {result.detail}")

    passed = sum(result.status == "PASS" for result in results)
    failed = sum(result.status == "FAIL" for result in results)
    warnings = sum(result.status == "WARN" for result in results)
    automated_health = round((len(results) - failed) / len(results) * 100)
    live_pending = sum(result.live_required for result in results)
    print(
        f"\nJARVIS AUTOMATED HEALTH: {automated_health}% "
        f"({passed} pass, {warnings} warning, {failed} fail)"
    )
    print(f"LIVE CERTIFICATION: {live_pending} supervised group(s) still required")

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = ARTIFACT_ROOT / f"self-test-{stamp}.json"
    report_path.write_text(
        json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "automated_health": automated_health,
            "live_pending": live_pending,
            "results": [asdict(result) for result in results],
        }, indent=2),
        encoding="utf-8",
    )
    print(f"REPORT: {report_path}")
    return results, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run side-effect-safe JARVIS capability checks.")
    parser.parse_args(argv)
    results, _ = run()
    return 1 if any(result.status == "FAIL" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
