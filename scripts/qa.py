#!/usr/bin/env python3
"""Reusable staged QA runner for the complete JARVIS application."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.qa_audit import declared_tools, repository_findings
from core.qa_report import CheckResult, Finding, QAReport, redact


ARTIFACT_ROOT = ROOT / ".qa-artifacts"
LIVE_CASES = (
    ("Clean startup and API-only gate", "Remove the key from the test environment. Confirm only API setup is interactive and voice/tools remain gated."),
    ("Invalid then valid Gemini key", "Enter an invalid key, verify recovery, then validate the configured test key."),
    ("Selected voice and introduction", "Confirm the chosen voice is used for the introduction and normal conversation."),
    ("Subtitle and audio synchronization", "Confirm subtitles do not outrun speech and speech is not cut off when captions finish."),
    ("Microphone turn-taking and interruption", "Speak, interrupt JARVIS, mute, and unmute. Confirm state and audio remain synchronized."),
    ("Gemini disconnect and reconnect", "Temporarily interrupt networking, restore it, and verify bounded reconnect behavior."),
    ("Window and secondary display", "Move JARVIS between displays, resize to minimum, and confirm it never forces fullscreen."),
    ("Themes, graphics, settings, compact mode", "Exercise every theme and graphics profile, Auto mode, settings, dock panels, and compact mode."),
    ("Keyboard and focus accessibility", "Navigate startup, API setup, settings, dock, and text input without a mouse. Confirm visible focus."),
    ("Controlled browser page", "With browser opt-in enabled, use only a localhost test page for navigate, click, type, and read actions."),
    ("Temporary file workflow", "Create, read, summarize, rename, archive, and trash files only inside the QA workspace."),
    ("Messaging draft safety", "Prepare a draft to a sandbox target. Confirm nothing sends and cancellation clears the draft."),
    ("Read-only message awareness", "Read the current sandbox conversation and confirm recipient matching without revealing contact details."),
    ("Reminder lifecycle", "With reminder opt-in enabled, create a QA-labelled reminder, verify it, then cancel it."),
    ("Screen and permission handling", "Test screen awareness once denied and once allowed. Confirm actionable, non-crashing feedback."),
    ("Read-only information tools", "Exercise weather, approved web search, flight lookup, task status, and game status."),
    ("Reversible desktop actions", "With desktop opt-in enabled, use screenshot and a controlled test text field. Do not close apps or alter connectivity."),
    ("Thirty-minute soak", "Run normal voice and typed interactions for 30 minutes while collecting process health samples."),
)


def _artifact_dir(report: QAReport) -> Path:
    return ARTIFACT_ROOT / report.run_id


def _run_check(name: str, command: list[str], env: dict[str, str]) -> CheckResult:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        return CheckResult(
            name=name,
            status="passed" if result.returncode == 0 else "failed",
            duration_seconds=time.monotonic() - started,
            details=redact(output[-4000:]),
        )
    except subprocess.TimeoutExpired:
        return CheckResult(name, "failed", time.monotonic() - started, "Timed out after 300 seconds.")
    except OSError as exc:
        return CheckResult(name, "failed", time.monotonic() - started, f"Could not start check: {exc}")


def _secret_scan() -> CheckResult:
    started = time.monotonic()
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    candidates = [ROOT / line for line in result.stdout.splitlines() if line.strip()]
    key_pattern = re.compile(r"AIza[0-9A-Za-z_-]{35}")
    unsafe = []
    for path in candidates:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            if key_pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                unsafe.append(str(path.relative_to(ROOT)))
        except OSError:
            continue
    return CheckResult(
        "tracked secret scan",
        "failed" if unsafe else "passed",
        time.monotonic() - started,
        f"Potential Gemini key pattern in: {', '.join(unsafe)}" if unsafe else "No tracked Gemini key patterns found.",
    )


def automated(_args) -> int:
    report = QAReport.create("automated")
    directory = _artifact_dir(report)
    workspace = directory / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "JARVIS_QA_MODE": "1",
        "JARVIS_QA_WORKSPACE": str(workspace),
        "QT_QPA_PLATFORM": env.get("QT_QPA_PLATFORM", "offscreen"),
        "PYTHONUNBUFFERED": "1",
    })
    report.checks.extend([
        _run_check("source compilation", [sys.executable, "-m", "compileall", "-q", "actions", "agent", "api", "awareness", "config", "core", "memory", "main.py", "ui.py"], env),
        _run_check("dependency consistency", [sys.executable, "-m", "pip", "check"], env),
        _run_check("complete unittest suite", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], env),
        _run_check("offscreen UI evidence", [sys.executable, "scripts/qa_ui_probe.py", str(directory / "ui")], env),
        _secret_scan(),
    ])
    report.findings.extend(repository_findings(ROOT))
    probe_path = directory / "ui" / "ui-probe.json"
    if probe_path.exists():
        probe = json.loads(probe_path.read_text(encoding="utf-8"))
        missing = []
        for surface, metrics in probe.items():
            for control in metrics.get("missing_accessible_names", []):
                missing.append(f"{surface}: {control}")
        if missing:
            report.findings.append(Finding(
                "P1", "Custom controls lack accessible names", "Accessibility",
                "VoiceOver may announce these controls generically instead of identifying their action or state.",
                "Open Settings > Graphics and navigate the four quality cards with VoiceOver.",
                "Every custom graphics card announces its quality, resolved Auto value, and selected state.",
                "; ".join(missing),
            ))
    unit_covered = {
        "agent_task", "browser_control", "email_control", "file_controller", "file_processor",
        "deep_research", "flight_finder", "graphics_quality", "jarvis_ui_control", "open_app",
        "media_control", "reminder", "save_memory", "screen_process", "send_message",
        "task_status", "weather_report", "web_search", "youtube_video",
    }
    safety_covered = {
        "browser_control", "code_helper", "computer_control", "computer_settings",
        "desktop_control", "dev_agent", "game_updater", "prepare_message_reply",
        "email_control", "media_control", "reminder", "send_message",
    }
    report.metadata["tool_coverage"] = {}
    for name in declared_tools(ROOT / "main.py"):
        coverage = ["declaration + dispatch contract"]
        if name in unit_covered:
            coverage.append("isolated unit/helper path")
        if name in safety_covered:
            coverage.append("QA safety path")
        coverage.append("supervised integration pending")
        report.metadata["tool_coverage"][name] = "; ".join(coverage)
    report.metadata["ui_audit"] = {
        "Accessibility": {"score": 2, "finding": "Core setup is keyboard-readable, but explicit accessible names are sparse."},
        "Performance": {"score": 2, "finding": "Graphics profiles exist; the required live soak measurement is still pending."},
        "Responsive Design": {"score": 3, "finding": "Minimum and standard desktop sizes render; display scaling and second-monitor checks remain live."},
        "Theming": {"score": 2, "finding": "Theme switching exists, but static analysis found extensive hard-coded colors."},
        "Anti-Patterns": {"score": 3, "finding": "The interface is distinctive and task-oriented; some control vocabulary remains inconsistent."},
        "total": 12,
        "rating": "Acceptable (significant work needed)",
        "anti_pattern_verdict": "Pass with reservations: distinctive JARVIS identity, not a generic generated dashboard.",
    }
    for check in report.checks:
        if check.status == "failed":
            report.findings.append(Finding(
                "P1",
                f"Automated check failed: {check.name}",
                "Automated QA",
                "A release baseline cannot be trusted while this check fails.",
                f"Run: {' '.join(check.name.split())} through scripts/qa.py automated.",
                "Check exits successfully.",
                check.details,
            ))
    json_path, md_path = report.write(directory)
    print(f"Automated QA complete: {md_path}")
    print(f"Machine-readable report: {json_path}")
    return 1 if any(check.status == "failed" for check in report.checks) else 0


def _answer_case(name: str, instructions: str) -> dict:
    print(f"\n{name}\n{instructions}")
    while True:
        answer = input("Result [p=pass, f=fail, b=blocked, s=skip, q=save and quit]: ").strip().lower()
        mapping = {"p": "passed", "f": "failed", "b": "blocked", "s": "skipped", "q": "quit"}
        if answer in mapping:
            break
    if answer == "q":
        return {"name": name, "status": "quit", "notes": ""}
    notes = input("Notes (optional): ").strip()
    return {"name": name, "status": mapping[answer], "notes": notes}


def _soak(pid: int, minutes: float, directory: Path) -> CheckResult:
    import psutil

    started = time.monotonic()
    process = psutil.Process(pid)
    samples = []
    deadline = started + max(0.0, minutes) * 60
    process.cpu_percent(None)
    while time.monotonic() < deadline:
        try:
            samples.append({
                "timestamp": time.time(),
                "cpu_percent": process.cpu_percent(None),
                "rss_mb": process.memory_info().rss / (1024 * 1024),
                "threads": process.num_threads(),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            return CheckResult("process soak", "failed", time.monotonic() - started, str(exc))
        time.sleep(min(10.0, max(0.1, deadline - time.monotonic())))
    (directory / "soak-samples.json").write_text(json.dumps(samples, indent=2), encoding="utf-8")
    if not samples:
        return CheckResult("process soak", "skipped", 0.0, "No soak duration requested.")
    first, last = samples[0], samples[-1]
    growth = last["rss_mb"] - first["rss_mb"]
    status = "failed" if growth > 250 or last["threads"] > first["threads"] + 25 else "passed"
    details = f"{len(samples)} samples; RSS change={growth:.1f} MB; thread change={last['threads'] - first['threads']}"
    return CheckResult("process soak", status, time.monotonic() - started, details)


def live(args) -> int:
    report = QAReport.create("supervised-live")
    directory = _artifact_dir(report)
    workspace = directory / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    print("JARVIS supervised QA")
    print(f"Set these before launching JARVIS in another terminal:\nJARVIS_QA_MODE=1\nJARVIS_QA_WORKSPACE={workspace}")
    print("Dangerous actions and real message sends remain blocked.")
    for name, instructions in LIVE_CASES:
        case = _answer_case(name, instructions)
        if case["status"] == "quit":
            break
        report.live_cases.append(case)
        if case["status"] == "failed":
            report.findings.append(Finding(
                "P1", f"Live case failed: {name}", "Supervised macOS QA",
                "A user-visible workflow failed on the certification device.",
                instructions, "Case passes on the current Mac.", case["notes"],
            ))
    if args.pid and args.soak_minutes > 0:
        report.checks.append(_soak(args.pid, args.soak_minutes, directory))
    json_path, md_path = report.write(directory)
    print(f"Live QA saved: {md_path}")
    print(f"Machine-readable report: {json_path}")
    return 1 if any(case["status"] == "failed" for case in report.live_cases) else 0


def checklist_auto(args) -> int:
    report = QAReport.create("automated-checklist")
    directory = _artifact_dir(report)
    workspace = directory / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "JARVIS_QA_MODE": "1",
        "JARVIS_QA_WORKSPACE": str(workspace),
        "QT_QPA_PLATFORM": env.get("QT_QPA_PLATFORM", "offscreen"),
        "PYTHONUNBUFFERED": "1",
    })
    command = [
        sys.executable,
        "scripts/qa_checklist_probe.py",
        str(directory),
        "--stability-seconds",
        str(args.stability_seconds),
    ]
    check = _run_check("automated live checklist", command, env)
    report.checks.append(check)
    results_path = directory / "checklist-results.json"
    if results_path.exists():
        report.live_cases = json.loads(results_path.read_text(encoding="utf-8"))
    else:
        report.findings.append(Finding(
            "P1", "Automated checklist produced no results", "Automated checklist",
            "Live integration coverage could not be assessed.",
            "Run python3 scripts/qa.py checklist-auto.",
            "The runner writes checklist-results.json.",
            check.details,
        ))
    for case in report.live_cases:
        if case.get("status") == "failed":
            report.findings.append(Finding(
                "P1", f"Automated checklist failed: {case.get('name', 'unknown')}",
                "Automated checklist",
                "A safely reproducible integration probe failed.",
                case.get("notes", "Run the automated checklist."),
                "The automated portion of this case passes.",
                json.dumps(case.get("evidence", {}), ensure_ascii=False)[:1000],
            ))
    status_counts = {}
    for case in report.live_cases:
        status = case.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    report.metadata["checklist_status_counts"] = status_counts
    json_path, md_path = report.write(directory)
    print(f"Automated checklist complete: {md_path}")
    print(f"Machine-readable report: {json_path}")
    return 1 if check.status == "failed" or report.findings else 0


def report_command(_args) -> int:
    reports = sorted(ARTIFACT_ROOT.glob("*/qa-report.json"), reverse=True)
    if not reports:
        print("No QA artifacts exist. Run scripts/qa.py automated first.", file=sys.stderr)
        return 1
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in reports]
    latest_by_mode = {}
    for payload in payloads:
        if payload.get("mode") in {"automated", "automated-checklist", "supervised-live"}:
            latest_by_mode.setdefault(payload["mode"], payload)
    report = QAReport.create("combined")
    report.metadata["source_runs"] = {
        mode: payload.get("run_id") for mode, payload in latest_by_mode.items()
    }
    for payload in latest_by_mode.values():
        report.checks.extend(CheckResult(**item) for item in payload.get("checks", []))
        report.findings.extend(Finding(**item) for item in payload.get("findings", []))
        report.live_cases.extend(payload.get("live_cases", []))
        for key in ("ui_audit", "tool_coverage"):
            if key in payload.get("metadata", {}):
                report.metadata[key] = payload["metadata"][key]
    _, md_path = report.write(_artifact_dir(report))
    print(md_path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run staged, side-effect-safe JARVIS QA.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    automated_parser = subparsers.add_parser("automated", help="Run safe automated checks and generate a report.")
    automated_parser.set_defaults(func=automated)
    live_parser = subparsers.add_parser("live", help="Record the supervised macOS checklist.")
    live_parser.add_argument("--pid", type=int, help="Running JARVIS PID to monitor during the soak test.")
    live_parser.add_argument("--soak-minutes", type=float, default=0.0)
    live_parser.set_defaults(func=live)
    checklist_parser = subparsers.add_parser(
        "checklist-auto",
        help="Automate every safe checklist item and label perception-only checks.",
    )
    checklist_parser.add_argument(
        "--stability-seconds",
        type=float,
        default=5.0,
        help="Duration of the short automatic stability probe (default: 5).",
    )
    checklist_parser.set_defaults(func=checklist_auto)
    report_parser = subparsers.add_parser("report", help="Regenerate the latest Markdown report.")
    report_parser.set_defaults(func=report_command)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
