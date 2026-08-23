"""Non-mutating repository checks used by the QA runner."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from core.qa_report import Finding


EXPECTED_TOOLS = {
    "open_app", "web_search", "weather_report", "check_messages",
    "prepare_message_reply", "send_message", "email_control", "reminder", "youtube_video", "media_control",
    "screen_process", "computer_settings", "browser_control", "file_controller",
    "desktop_control", "code_helper", "website_builder", "dev_agent", "agent_task",
    "computer_control", "game_updater", "flight_finder", "jarvis_ui_control",
    "file_processor", "create_presentation", "deep_research", "graphics_quality", "task_status", "save_memory",
}


def declared_tools(main_path: Path) -> list[str]:
    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "TOOL_DECLARATIONS" for target in node.targets):
            continue
        names = []
        for item in getattr(node.value, "elts", []):
            if not isinstance(item, ast.Dict):
                continue
            for key, value in zip(item.keys, item.values):
                if isinstance(key, ast.Constant) and key.value == "name" and isinstance(value, ast.Constant):
                    names.append(str(value.value))
        return names
    return []


def repository_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    main_path = root / "main.py"
    ui_path = root / "ui.py"
    tools = declared_tools(main_path)
    missing = sorted(EXPECTED_TOOLS - set(tools))
    duplicates = sorted({name for name in tools if tools.count(name) > 1})
    main_source = main_path.read_text(encoding="utf-8")

    if missing or duplicates:
        findings.append(Finding(
            "P0", "Tool declaration contract is inconsistent", "Tool routing",
            "Gemini can request a missing or ambiguous tool handler.",
            "Run the automated contract audit.",
            "Every supported tool is declared exactly once.",
            f"Missing={missing}; duplicates={duplicates}",
        ))
    unhandled = sorted(name for name in tools if f'name == "{name}"' not in main_source)
    if unhandled:
        findings.append(Finding(
            "P0", "Declared tools lack dispatch branches", "Tool routing",
            "A valid Live tool call can return no useful result.",
            "Compare TOOL_DECLARATIONS with JarvisLive._execute_tool.",
            "Every declaration has an execution path.",
            f"Unhandled={unhandled}",
        ))

    exception_count = 0
    for path in [main_path, ui_path, *sorted((root / "actions").glob("*.py"))]:
        source = path.read_text(encoding="utf-8", errors="replace")
        exception_count += len(re.findall(r"except Exception(?:\s+as\s+\w+)?:", source))
    if exception_count >= 100:
        findings.append(Finding(
            "P2", "Broad exception handling reduces failure visibility", "Observability",
            "Real integration failures may be swallowed or reduced to generic UI messages.",
            "Trigger mocked permission, network, and subprocess failures and inspect structured logs.",
            "Failures retain actionable context and are observable in QA reports.",
            f"Found {exception_count} broad Exception handlers in runtime modules.",
        ))

    deprecated_sdk_files = []
    for path in [main_path, *sorted((root / "actions").glob("*.py")), *sorted((root / "agent").glob("*.py"))]:
        if "google.generativeai" in path.read_text(encoding="utf-8", errors="replace"):
            deprecated_sdk_files.append(str(path.relative_to(root)))
    if deprecated_sdk_files:
        findings.append(Finding(
            "P2", "Deprecated Gemini SDK remains in runtime paths", "Dependencies",
            "Those integrations no longer receive fixes and may break as Gemini APIs evolve.",
            "Run the unit suite and exercise tools importing google.generativeai.",
            "Runtime integrations consistently use the supported google.genai SDK.",
            "Affected files: " + ", ".join(deprecated_sdk_files),
        ))

    ui_source = ui_path.read_text(encoding="utf-8", errors="replace")
    hardcoded = len(re.findall(r"#[0-9A-Fa-f]{6,8}", ui_source))
    if hardcoded >= 50:
        findings.append(Finding(
            "P2", "UI contains extensive hard-coded color values", "Theming",
            "Some controls may not update consistently when themes change.",
            "Switch through all themes and inspect existing overlays and detached panels.",
            "Runtime colors come from theme tokens or are explicitly invariant.",
            f"Found {hardcoded} hexadecimal color literals in ui.py.",
        ))
    return findings
