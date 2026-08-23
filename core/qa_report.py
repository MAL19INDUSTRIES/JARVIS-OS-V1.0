"""Structured QA results and redacted artifact generation."""

from __future__ import annotations

import json
import platform
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


_SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?i)(api[_ -]?key|token|secret)(\s*[:=]\s*)[^\s,;]+"),
)


def redact(text: str) -> str:
    cleaned = str(text or "")
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            cleaned = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", cleaned)
        else:
            cleaned = pattern.sub("[REDACTED]", cleaned)
    return cleaned


@dataclass
class CheckResult:
    name: str
    status: str
    duration_seconds: float = 0.0
    details: str = ""


@dataclass
class Finding:
    severity: str
    title: str
    subsystem: str
    impact: str
    reproduction: str = ""
    expected: str = ""
    actual: str = ""
    evidence: str = ""


@dataclass
class QAReport:
    run_id: str
    started_at: str
    mode: str
    checks: list[CheckResult] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    live_cases: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(cls, mode: str) -> "QAReport":
        now = datetime.now().astimezone()
        return cls(
            run_id=now.strftime("%Y%m%d-%H%M%S"),
            started_at=now.isoformat(timespec="seconds"),
            mode=mode,
            metadata={
                "platform": platform.platform(),
                "python": sys.version.split()[0],
                "machine": platform.machine(),
            },
        )

    def to_dict(self) -> dict:
        payload = asdict(self)
        return json.loads(redact(json.dumps(payload, ensure_ascii=False)))

    def write(self, directory: Path) -> tuple[Path, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        json_path = directory / "qa-report.json"
        md_path = directory / "qa-report.md"
        json_path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        md_path.write_text(self.to_markdown(), encoding="utf-8")
        return json_path, md_path

    def to_markdown(self) -> str:
        severity_counts = {level: 0 for level in ("P0", "P1", "P2", "P3")}
        for finding in self.findings:
            severity_counts[finding.severity] = severity_counts.get(finding.severity, 0) + 1
        passed = sum(check.status == "passed" for check in self.checks)
        failed = sum(check.status == "failed" for check in self.checks)
        lines = [
            "# JARVIS QA Report",
            "",
            f"- Run: `{self.run_id}`",
            f"- Mode: `{self.mode}`",
            f"- Environment: {self.metadata.get('platform', '')}",
            f"- Checks: {passed} passed, {failed} failed",
            "- Findings: " + ", ".join(f"{key}={value}" for key, value in severity_counts.items()),
            "",
            "## Check Results",
            "",
            "| Check | Status | Duration | Details |",
            "|---|---|---:|---|",
        ]
        for check in self.checks:
            details = redact(check.details).replace("\n", " ").replace("|", "\\|")[:500]
            lines.append(f"| {check.name} | {check.status} | {check.duration_seconds:.2f}s | {details} |")
        lines.extend(["", "## Findings", ""])
        if not self.findings:
            lines.append("No automated defects were recorded.")
        for finding in sorted(self.findings, key=lambda item: item.severity):
            lines.extend([
                f"### [{finding.severity}] {finding.title}",
                "",
                f"- Subsystem: {finding.subsystem}",
                f"- Impact: {finding.impact}",
                f"- Reproduction: {finding.reproduction or 'See associated check.'}",
                f"- Expected: {finding.expected or 'Check passes.'}",
                f"- Actual: {redact(finding.actual or finding.evidence)}",
                "",
            ])
        if self.live_cases:
            lines.extend(["## Supervised Live Checklist", "", "| Case | Status | Notes |", "|---|---|---|"])
            for case in self.live_cases:
                notes = redact(case.get("notes", "")).replace("|", "\\|")
                lines.append(f"| {case.get('name', '')} | {case.get('status', '')} | {notes} |")
        ui_audit = self.metadata.get("ui_audit")
        if isinstance(ui_audit, dict):
            lines.extend([
                "",
                "## UI Audit Health",
                "",
                "| Dimension | Score | Key finding |",
                "|---|---:|---|",
            ])
            for dimension in ("Accessibility", "Performance", "Responsive Design", "Theming", "Anti-Patterns"):
                item = ui_audit.get(dimension, {})
                lines.append(f"| {dimension} | {item.get('score', 0)}/4 | {item.get('finding', '')} |")
            lines.extend([
                f"| **Total** | **{ui_audit.get('total', 0)}/20** | **{ui_audit.get('rating', '')}** |",
                "",
                f"Anti-pattern verdict: **{ui_audit.get('anti_pattern_verdict', 'Not assessed')}**",
            ])
        tool_coverage = self.metadata.get("tool_coverage")
        if isinstance(tool_coverage, dict):
            lines.extend(["", "## Tool Coverage Matrix", "", "| Tool | Automated coverage |", "|---|---|"])
            for tool, coverage in sorted(tool_coverage.items()):
                lines.append(f"| `{tool}` | {coverage} |")
        return redact("\n".join(lines).rstrip() + "\n")
