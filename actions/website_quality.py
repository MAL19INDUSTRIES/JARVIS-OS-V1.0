"""Deterministic and rendered quality checks for generated websites."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1000},
    "tablet": {"width": 820, "height": 1180},
    "mobile": {"width": 390, "height": 844},
}


def audit_source(files: dict[str, str], routes: list[dict[str, Any]]) -> list[dict[str, str]]:
    combined = "\n".join(files.values())
    app_source = "\n".join(
        content for path, content in files.items() if Path(path).suffix.lower() in {".tsx", ".jsx", ".html"}
    )
    css_source = "\n".join(content for path, content in files.items() if Path(path).suffix.lower() == ".css")
    issues: list[dict[str, str]] = []

    def add(severity: str, code: str, message: str) -> None:
        issues.append({"severity": severity, "code": code, "message": message})

    if not re.search(r"<main\b", app_source, re.I):
        add("major", "missing-main", "The generated website has no semantic main landmark.")
    if not re.search(r"<h1\b", app_source, re.I):
        add("major", "missing-h1", "The generated website has no page-level heading.")
    if re.search(r"<img\b(?![^>]*\balt=)[^>]*>", app_source, re.I | re.S):
        add("major", "missing-image-alt", "At least one image is missing alt text.")
    if ":focus-visible" not in css_source:
        add("major", "missing-focus", "Keyboard-visible focus styling is missing.")
    if "prefers-reduced-motion" not in css_source:
        add("major", "missing-reduced-motion", "Reduced-motion behavior is missing.")
    if re.search(r"background-clip\s*:\s*text", css_source, re.I):
        add("major", "gradient-text", "Gradient text is prohibited by the design quality policy.")
    if re.search(r"backdrop-filter\s*:\s*blur", css_source, re.I):
        add("minor", "decorative-blur", "Decorative backdrop blur should be removed unless functionally necessary.")
    if len(re.findall(r"border-radius\s*:\s*(?:999|9999)px", css_source, re.I)) > 5:
        add("minor", "pill-overuse", "The design overuses pill-shaped controls.")
    if len(re.findall(r"className=[\"'][^\"']*card", app_source, re.I)) >= 6:
        add("minor", "card-grid", "The page appears to rely on a repetitive card grid.")
    if "viewport-fit=cover" not in combined:
        add("minor", "safe-area", "The viewport metadata does not opt into safe-area handling.")
    for route in routes:
        path = str(route.get("path") or "")
        if path and path != "/" and path not in combined:
            add("major", "missing-route", f"Requested route '{path}' is not represented in generated source.")
    return issues


def capture_routes(
    base_url: str,
    routes: list[dict[str, Any]],
    output_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Capture routes and inspect live layout using Playwright Chromium."""

    if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
        return [], [{"severity": "info", "code": "visual-qa-test-skip", "message": "Visual QA is disabled in the offscreen test environment."}]
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return [], [{"severity": "major", "code": "playwright-unavailable", "message": f"Playwright is unavailable: {exc}"}]

    screenshots: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            for route in routes or [{"path": "/", "name": "Home"}]:
                route_path = str(route.get("path") or "/")
                route_slug = re.sub(r"[^a-z0-9]+", "-", route_path.lower()).strip("-") or "home"
                for viewport, size in VIEWPORTS.items():
                    page = browser.new_page(viewport=size)
                    page.goto(f"{base_url.rstrip('/')}{route_path}", wait_until="networkidle")
                    overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 1")
                    if overflow:
                        issues.append({"severity": "major", "code": "horizontal-overflow", "message": f"{route_path} overflows horizontally at {viewport}."})
                    unnamed = page.evaluate("""
                        [...document.querySelectorAll('button,a[href]')].filter((node) => {
                          const name = (node.getAttribute('aria-label') || node.textContent || '').trim();
                          return !name;
                        }).length
                    """)
                    if unnamed:
                        issues.append({"severity": "major", "code": "unnamed-control", "message": f"{route_path} has {unnamed} unnamed controls at {viewport}."})
                    output = output_dir / f"{route_slug}-{viewport}.png"
                    page.screenshot(path=str(output), full_page=True)
                    screenshots.append({"route": route_path, "viewport": viewport, "path": str(output)})
                    page.close()
            browser.close()
    except Exception as exc:
        issues.append({
            "severity": "major",
            "code": "visual-render-failed",
            "message": f"Visual QA could not render the website. Run 'playwright install chromium' and retry: {exc}",
        })
    return screenshots, issues


__all__ = ["VIEWPORTS", "audit_source", "capture_routes"]
