"""Cancellable, source-grounded deep research for JARVIS."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

from actions.jarvis_file_stamp import normalize_persona, persona_attribution
from memory.config_manager import get_gemini_key


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()
SYNTHESIS_MODELS = ("gemini-2.5-flash-lite", "gemini-2.5-flash")

DEPTH_CONFIG = {
    "quick": {"queries": 3, "max_sources": 10},
    "standard": {"queries": 6, "max_sources": 20},
    "deep": {"queries": 10, "max_sources": 35},
}

PENDING_TTL_SECONDS = 15 * 60
RUN_MODE_QUESTION = (
    "I have the research brief ready, but I have not started it. "
    "Would you like me to run it in the background with a compact status bar, "
    "or show the research by opening the browser and visiting the sources while I work?"
)
_pending_lock = threading.Lock()
_pending_parameters: dict | None = None
_pending_created_at = 0.0
_latest_result_lock = threading.Lock()
_latest_result: "ResearchResult | None" = None
_tenant_pending: dict[str, tuple[dict, float]] = {}
_tenant_latest_results: dict[str, "ResearchResult"] = {}


class ResearchCancelled(RuntimeError):
    pass


@dataclass
class ResearchRequest:
    question: str
    depth: str = "standard"
    focus_areas: list[str] = field(default_factory=list)
    max_sources: int = 20

    @classmethod
    def from_parameters(cls, parameters: dict | None) -> "ResearchRequest":
        params = parameters or {}
        question = str(
            params.get("question") or params.get("topic") or params.get("query") or ""
        ).strip()
        if not question:
            raise ValueError("Deep research requires a question or topic.")

        depth = str(params.get("depth", "standard") or "standard").strip().lower()
        aliases = {"fast": "quick", "normal": "standard", "thorough": "deep", "full": "deep"}
        depth = aliases.get(depth, depth)
        if depth not in DEPTH_CONFIG:
            raise ValueError("Research depth must be quick, standard, or deep.")

        raw_focus = params.get("focus_areas", []) or []
        if isinstance(raw_focus, str):
            raw_focus = [part.strip() for part in raw_focus.split(",")]
        focus_areas = [str(item).strip() for item in raw_focus if str(item).strip()][:10]

        default_sources = DEPTH_CONFIG[depth]["max_sources"]
        try:
            max_sources = int(params.get("max_sources", default_sources) or default_sources)
        except (TypeError, ValueError):
            max_sources = default_sources
        max_sources = max(5, min(50, max_sources))
        return cls(
            question=question,
            depth=depth,
            focus_areas=focus_areas,
            max_sources=max_sources,
        )


@dataclass
class ResearchResult:
    question: str
    report_markdown: str
    evidence: dict
    sources: list[dict]
    warnings: list[str] = field(default_factory=list)
    saved_paths: list[Path] = field(default_factory=list)

    @property
    def artifacts(self) -> list[str]:
        return [str(path) for path in self.saved_paths]

    def __str__(self) -> str:
        return (
            f"Deep research complete. Reviewed {len(self.sources)} sources. "
            "The report is held in memory and has not been saved."
        )

    def completion_prompt(self) -> str:
        return (
            "[INTERNAL DEEP RESEARCH COMPLETION] Give the user a full, detailed spoken summary "
            "of the report below. Cover the direct answer, strongest evidence, meaningful "
            "counterarguments, practical implications, and confidence gaps. Do not say the report "
            "was saved because it exists only in volatile memory. End by asking whether they want "
            "to save it to their Files, save it to their Desktop, or have you read the entire report aloud.\n\n"
            f"REPORT\n{self.report_markdown}"
        )


def _api_key() -> str:
    key = str(get_gemini_key() or os.environ.get("GEMINI_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("A valid Gemini API key is required for deep research.")
    return key


def _check_cancel(cancel_flag) -> None:
    if cancel_flag is not None and cancel_flag.is_set():
        raise ResearchCancelled("Deep research was cancelled.")


def _progress(callback, percent: int, phase: str, **extra) -> None:
    if callback:
        callback(percent=percent, phase=phase, **extra)


def _response_text(response) -> str:
    direct = str(getattr(response, "text", "") or "").strip()
    if direct:
        return direct
    parts = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            text = str(getattr(part, "text", "") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _valid_source_url(value: str) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _extract_grounding_sources(response) -> list[dict]:
    sources = []
    for candidate in getattr(response, "candidates", []) or []:
        metadata = getattr(candidate, "grounding_metadata", None)
        for chunk in getattr(metadata, "grounding_chunks", []) or []:
            web = getattr(chunk, "web", None)
            url = str(getattr(web, "uri", "") or "").strip()
            if not _valid_source_url(url):
                continue
            sources.append({
                "title": str(getattr(web, "title", "") or urlparse(url).netloc).strip(),
                "url": url,
            })
    return sources


def _json_from_text(text: str) -> dict:
    value = str(text or "").strip()
    value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    start, end = value.find("{"), value.rfind("}")
    if start >= 0 and end > start:
        value = value[start:end + 1]
    data = json.loads(value)
    return data if isinstance(data, dict) else {}


def _plan_queries(client, request: ResearchRequest) -> list[str]:
    """Build a diverse plan locally so research does not burn one API call before it starts."""
    count = DEPTH_CONFIG[request.depth]["queries"]
    question = request.question
    year = datetime.now().year
    queries = [
        question,
        f"{question} primary sources official data",
        f"{question} latest evidence {year}",
        f"{question} independent analysis comparison",
        f"{question} limitations criticism counterarguments",
        f"{question} benchmarks quantitative results",
        f"{question} expert consensus",
        f"{question} case studies real world outcomes",
        f"{question} costs risks tradeoffs",
        f"{question} future outlook uncertainty",
    ]
    queries[1:1] = [f"{question} {area}" for area in request.focus_areas]
    cleaned = []
    for query in queries:
        query = " ".join(str(query or "").split())
        if query and query.casefold() not in {item.casefold() for item in cleaned}:
            cleaned.append(query)
    return cleaned[:count]


def _clean_search_url(url: str) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        value = unquote(parse_qs(parsed.query).get("uddg", [value])[0])
    return value


def _duckduckgo_html_search(query: str, max_results: int) -> list[dict]:
    import requests
    from bs4 import BeautifulSoup

    response = requests.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers={"User-Agent": "Mozilla/5.0 JARVIS Research"},
        timeout=18,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for row in soup.select(".result"):
        link = row.select_one(".result__a")
        if link is None:
            continue
        url = _clean_search_url(link.get("href", ""))
        if not _valid_source_url(url):
            continue
        snippet_node = row.select_one(".result__snippet")
        results.append({
            "title": " ".join(link.get_text(" ", strip=True).split()),
            "snippet": " ".join(snippet_node.get_text(" ", strip=True).split()) if snippet_node else "",
            "url": url,
        })
        if len(results) >= max_results:
            break
    return results


def _bing_html_search(query: str, max_results: int) -> list[dict]:
    import requests
    from bs4 import BeautifulSoup

    response = requests.get(
        "https://www.bing.com/search",
        params={"q": query, "count": max_results},
        headers={"User-Agent": "Mozilla/5.0 JARVIS Research"},
        timeout=18,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for row in soup.select("li.b_algo"):
        link = row.select_one("h2 a")
        if link is None:
            continue
        url = str(link.get("href", "")).strip()
        if not _valid_source_url(url):
            continue
        snippet_node = row.select_one(".b_caption p")
        results.append({
            "title": " ".join(link.get_text(" ", strip=True).split()),
            "snippet": " ".join(snippet_node.get_text(" ", strip=True).split()) if snippet_node else "",
            "url": url,
        })
        if len(results) >= max_results:
            break
    return results


def _search_web(query: str, max_results: int = 6) -> list[dict]:
    errors = []
    try:
        raw_results = _duckduckgo_html_search(query, max_results * 2)
    except Exception as exc:
        errors.append(f"DuckDuckGo HTML: {exc}")
        raw_results = []
    if not raw_results:
        try:
            raw_results = _bing_html_search(query, max_results * 2)
        except Exception as exc:
            errors.append(f"Bing HTML: {exc}")

    diverse = []
    seen_urls = set()
    seen_domains = set()
    overflow = []
    for item in raw_results:
        url = _clean_search_url(item.get("url") or item.get("href") or "")
        if not _valid_source_url(url):
            continue
        normalized = url.rstrip("/").casefold()
        if normalized in seen_urls:
            continue
        seen_urls.add(normalized)
        result = {
            "title": str(item.get("title") or urlparse(url).netloc).strip(),
            "snippet": str(item.get("snippet") or item.get("body") or "").strip(),
            "url": url,
        }
        domain = urlparse(url).netloc.casefold().removeprefix("www.")
        if domain in seen_domains:
            overflow.append(result)
            continue
        seen_domains.add(domain)
        diverse.append(result)
        if len(diverse) >= max_results:
            return diverse
    for result in overflow:
        diverse.append(result)
        if len(diverse) >= max_results:
            break
    if not diverse:
        raise RuntimeError("; ".join(errors) or "No web results were returned.")
    return diverse


def _browser_result_failed(result: str) -> bool:
    lowered = str(result or "").lower()
    return any(marker in lowered for marker in (
        "could not", "error", "timed out", "unknown action", "not started", "failed",
    ))


def _open_visible_research(
    query: str,
    results: list[dict],
    *,
    player=None,
    opened_urls: set[str] | None = None,
    cancel_flag=None,
) -> list[str]:
    """Drive JARVIS's controlled browser through the query and one new source tab."""
    from actions.browser_control import browser_control

    opened_urls = opened_urls if opened_urls is not None else set()
    extracted_pages = []
    _check_cancel(cancel_flag)
    search_result = browser_control(
        {"action": "search", "query": query, "engine": "google"},
        player=player,
    )
    if _browser_result_failed(search_result):
        if player and hasattr(player, "write_log"):
            player.write_log(f"deep_research: Browser search unavailable: {str(search_result)[:120]}")
        return extracted_pages

    for source in results:
        url = source["url"]
        key = url.rstrip("/").casefold()
        if key in opened_urls:
            continue
        opened_urls.add(key)
        _check_cancel(cancel_flag)
        opened = browser_control({"action": "new_tab", "url": url}, player=player)
        if _browser_result_failed(opened):
            continue
        page_text = browser_control({"action": "get_text"}, player=player)
        if page_text and not _browser_result_failed(page_text):
            extracted_pages.append(
                f"Visible source: {source['title']}\nURL: {url}\nPage extract: {page_text[:3500]}"
            )
        break
    return extracted_pages


def _research_query(
    client,
    query: str,
    question: str,
    *,
    visible: bool = False,
    player=None,
    opened_urls: set[str] | None = None,
    cancel_flag=None,
) -> tuple[str, list[dict]]:
    results = _search_web(query, max_results=6)
    page_extracts = []
    if visible:
        page_extracts = _open_visible_research(
            query,
            results,
            player=player,
            opened_urls=opened_urls,
            cancel_flag=cancel_flag,
        )
    snippets = []
    for item in results:
        snippet = item.get("snippet") or "Source discovered; open the URL for full context."
        snippets.append(f"- {item['title']}: {snippet}\n  Source: {item['url']}")
    findings = "\n".join(snippets + page_extracts).strip()
    sources = [{"title": item["title"], "url": item["url"]} for item in results]
    return findings, sources


def _deduplicate_sources(sources: list[dict], limit: int) -> list[dict]:
    unique = []
    seen = set()
    for source in sources:
        url = str(source.get("url", "") or "").strip()
        key = url.rstrip("/").casefold()
        if not key or key in seen or not _valid_source_url(url):
            continue
        seen.add(key)
        unique.append({"title": str(source.get("title", "") or urlparse(url).netloc), "url": url})
        if len(unique) >= limit:
            break
    return unique


def _synthesize(client, request: ResearchRequest, evidence: list[dict], sources: list[dict]) -> str:
    source_ids = {
        source["url"].rstrip("/").casefold(): index
        for index, source in enumerate(sources, start=1)
    }
    evidence_blocks = []
    for index, item in enumerate(evidence, start=1):
        thread_ids = []
        for source in item.get("sources", []):
            source_id = source_ids.get(str(source.get("url", "")).rstrip("/").casefold())
            if source_id and source_id not in thread_ids:
                thread_ids.append(source_id)
        thread_citations = ", ".join(f"[{source_id}]" for source_id in thread_ids) or "No mapped URLs"
        evidence_blocks.append(
            f"### Research thread {index}: {item['query']}\n"
            f"Mapped sources: {thread_citations}\n{item['findings'][:5000]}"
        )
    evidence_text = "\n\n".join(evidence_blocks)
    source_catalog = "\n".join(
        f"[{index}] {source['title']} | {source['url']}"
        for index, source in enumerate(sources, start=1)
    ) or "No extractable source URLs were returned."
    focus = ", ".join(request.focus_areas) if request.focus_areas else "General"
    prompt = f"""
Write a decision-grade deep research report in Markdown.

Question: {request.question}
Research depth: {request.depth}
Focus: {focus}
Current date: {datetime.now().date().isoformat()}

Requirements:
- Begin with a concise executive summary and direct answer.
- Include key findings, evidence, counterarguments, contradictions, unknowns, and practical implications.
- Use calibrated language. Never invent certainty or facts beyond the evidence.
- Cite source numbers inline like [1] whenever supported by the source catalog.
- End with a section named "Confidence and gaps".
- Do not reproduce a sources section; the application appends the verified catalog.

EVIDENCE BRIEFS
{evidence_text}

VERIFIED SOURCE CATALOG
{source_catalog}
""".strip()
    errors = []
    for model in SYNTHESIS_MODELS:
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            report = _response_text(response)
            if report:
                return report.strip()
            errors.append(f"{model}: empty response")
        except Exception as exc:
            errors.append(f"{model}: {exc}")
    raise RuntimeError("; ".join(errors))


def _fallback_synthesis(
    request: ResearchRequest,
    evidence: list[dict],
    sources: list[dict],
    persona: str = "JARVIS",
) -> str:
    """Produce a source-first report even when Gemini synthesis quota is unavailable."""
    source_ids = {
        source["url"].rstrip("/").casefold(): index
        for index, source in enumerate(sources, start=1)
    }
    findings = []
    for item in evidence:
        citations = []
        for source in item.get("sources", []):
            source_id = source_ids.get(str(source.get("url", "")).rstrip("/").casefold())
            if source_id and source_id not in citations:
                citations.append(source_id)
        citation_text = " ".join(f"[{source_id}]" for source_id in citations[:4])
        condensed = " ".join(str(item.get("findings") or "").split())[:900]
        if condensed:
            findings.append(f"- **{item['query']}**: {condensed} {citation_text}".strip())
    evidence_text = "\n".join(findings) or "- No readable evidence extracts were returned."
    creator = normalize_persona(persona)
    return f"""## Executive summary

{creator} reviewed {len(sources)} distinct web sources for this question. The synthesis model was unavailable, so this report preserves the retrieved evidence directly instead of inventing a conclusion. The strongest probable answer should be drawn from the recurring claims below and checked against the linked sources.

## Retrieved evidence

{evidence_text}

## Practical interpretation

- Give the most weight to official, primary, and independently corroborated sources.
- Treat rankings, forecasts, and vendor claims as provisional when methodologies differ.
- Where sources disagree, prefer the most recent evidence with transparent methods and comparable measurements.

## Counterarguments and uncertainty

This fallback report has not received model-assisted cross-source synthesis. Contradictions may remain in the evidence extracts, and source quality varies.

## Confidence and gaps

Confidence is limited until the cited sources are reviewed together. The evidence and URLs are retained so the research remains inspectable rather than failing outright.
""".strip()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:60] or "research"


def _remember_latest_result(result: ResearchResult) -> None:
    global _latest_result
    from core.tenant import get_current_user_id

    user_id = get_current_user_id()
    with _latest_result_lock:
        if user_id:
            _tenant_latest_results[user_id] = result
        else:
            _latest_result = result


def _get_latest_result() -> ResearchResult | None:
    from core.tenant import get_current_user_id

    user_id = get_current_user_id()
    with _latest_result_lock:
        return _tenant_latest_results.get(user_id) if user_id else _latest_result


def _save_report(result: ResearchResult, destination: str, output_path: str = "") -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if output_path:
        candidate = Path(output_path).expanduser()
        report_path = (
            candidate
            if candidate.suffix.lower() == ".md"
            else candidate / f"{_slug(result.question)}-{stamp}.md"
        )
    elif destination == "desktop":
        report_path = Path.home() / "Desktop" / "JARVIS Research" / f"{_slug(result.question)}-{stamp}.md"
    else:
        report_path = Path.home() / "Documents" / "JARVIS Research" / f"{_slug(result.question)}-{stamp}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(result.report_markdown, encoding="utf-8")
    if report_path not in result.saved_paths:
        result.saved_paths.append(report_path)
    return report_path


def _handle_result_action(parameters: dict) -> str | None:
    action = str(parameters.get("result_action", "none") or "none").strip().lower()
    aliases = {
        "save": "save_files",
        "files": "save_files",
        "documents": "save_files",
        "desktop": "save_desktop",
        "read": "read_report",
        "read_aloud": "read_report",
    }
    action = aliases.get(action, action)
    if action == "none":
        return None
    if action not in {"save_files", "save_desktop", "read_report"}:
        raise ValueError("Result action must be save_files, save_desktop, or read_report.")
    result = _get_latest_result()
    if result is None:
        return "There is no completed Deep Research report in memory yet."
    if action == "read_report":
        return (
            "[INTERNAL DEEP RESEARCH READOUT] Read the complete report below aloud to the user. "
            "Preserve every section and material finding, but speak citation numbers naturally. "
            "Do not claim it has been saved.\n\n"
            f"{result.report_markdown}"
        )
    destination = "desktop" if action == "save_desktop" else "files"
    path = _save_report(result, destination, str(parameters.get("output_path", "") or ""))
    return f"The complete research report has been saved to {path}. Would you like me to read it aloud as well?"


def build_deep_research(
    parameters: dict,
    *,
    player=None,
    cancel_flag=None,
    progress_callback: Callable | None = None,
) -> ResearchResult:
    from google import genai

    request = ResearchRequest.from_parameters(parameters)
    _check_cancel(cancel_flag)
    client = genai.Client(api_key=_api_key())
    warnings = []
    _progress(progress_callback, 4, "Planning research questions")
    queries = _plan_queries(client, request)
    if player and hasattr(player, "write_log"):
        player.write_log(f"deep_research: Planned {len(queries)} evidence threads for {request.question[:70]}")

    evidence = []
    all_sources = []
    opened_urls: set[str] = set()
    for index, query in enumerate(queries, start=1):
        _check_cancel(cancel_flag)
        percent = 8 + int((index - 1) / max(1, len(queries)) * 62)
        _progress(progress_callback, percent, f"Researching evidence thread {index}/{len(queries)}")
        if player and hasattr(player, "write_log"):
            player.write_log(f"deep_research [{index}/{len(queries)}]: {query}")
        try:
            findings, sources = _research_query(
                client,
                query,
                request.question,
                visible=bool(parameters.get("_visible_browser", False)),
                player=player,
                opened_urls=opened_urls,
                cancel_flag=cancel_flag,
            )
            evidence.append({"query": query, "findings": findings, "sources": sources})
            all_sources.extend(sources)
        except Exception as exc:
            warnings.append(f"Evidence thread failed ({query}): {exc}")

    _check_cancel(cancel_flag)
    if not evidence:
        details = "; ".join(warnings[:3])
        raise RuntimeError(
            "Could not gather web evidence from any research thread. "
            f"Details: {details or 'No search backend returned a diagnostic.'}"
        )
    sources = _deduplicate_sources(all_sources, request.max_sources)
    if not sources:
        warnings.append("Grounding metadata contained no extractable source URLs.")

    creator_persona = normalize_persona(
        str((parameters or {}).get("_persona_name", "JARVIS"))
    )
    _progress(progress_callback, 76, "Synthesizing findings and contradictions", warnings=warnings)
    try:
        report = _synthesize(client, request, evidence, sources)
    except Exception as exc:
        warnings.append(f"Gemini synthesis unavailable; used source-first fallback: {exc}")
        report = _fallback_synthesis(request, evidence, sources, creator_persona)
    _check_cancel(cancel_flag)
    source_lines = "\n".join(
        f"{index}. [{source['title']}]({source['url']})"
        for index, source in enumerate(sources, start=1)
    ) or "No verified source URLs were returned."
    attribution = persona_attribution(creator_persona)
    final_markdown = (
        f"# Deep Research: {request.question}\n\n"
        f"_Generated by {creator_persona} at "
        f"{datetime.now().astimezone().isoformat(timespec='seconds')} · Depth: {request.depth}_\n\n"
        f"{report}\n\n## Sources\n\n{source_lines}\n\n---\n\n{attribution}\n"
    )
    evidence_payload = {
        "question": request.question,
        "persona": creator_persona,
        "attribution": attribution,
        "depth": request.depth,
        "focus_areas": request.focus_areas,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "queries": queries,
        "evidence": evidence,
        "sources": sources,
        "warnings": warnings,
    }
    _progress(
        progress_callback, 100, "Deep research complete",
        artifacts=[], warnings=warnings,
    )
    if player and hasattr(player, "write_log"):
        player.write_log("deep_research: ✓ Complete; report held in memory and not saved")
    return ResearchResult(request.question, final_markdown, evidence_payload, sources, warnings)


def queue_deep_research(
    parameters: dict,
    player=None,
    speak=None,
    *,
    visible: bool = False,
) -> str:
    request = ResearchRequest.from_parameters(parameters)
    from agent.task_queue import TaskPriority, get_queue
    run_parameters = dict(parameters)
    run_parameters["_visible_browser"] = bool(visible)
    show_background_status = not visible

    def runner(cancel_flag, progress_callback):
        def publish_progress(**update):
            progress_callback(**update)
            if show_background_status and player and hasattr(player, "update_research_progress"):
                player.update_research_progress(
                    question=request.question,
                    percent=update.get("percent", 0),
                    phase=update.get("phase", "Researching"),
                    artifacts=update.get("artifacts") or [],
                    warnings=update.get("warnings") or [],
                )

        try:
            result = build_deep_research(
                run_parameters,
                player=player,
                cancel_flag=cancel_flag,
                progress_callback=publish_progress,
            )
            _remember_latest_result(result)
            if speak:
                speak(result.completion_prompt())
            return result
        except ResearchCancelled:
            if show_background_status and player and hasattr(player, "finish_research_progress"):
                player.finish_research_progress("cancelled", "Research cancelled")
            raise
        except Exception as exc:
            if show_background_status and player and hasattr(player, "finish_research_progress"):
                player.finish_research_progress("failed", str(exc)[:160])
            if speak:
                speak(f"Deep Research failed before completion: {str(exc)[:300]}")
            raise

    if show_background_status and player and hasattr(player, "show_research_progress"):
        player.show_research_progress(request.question)
    try:
        on_cancel = None
        if show_background_status and player and hasattr(player, "finish_research_progress"):
            on_cancel = lambda: player.finish_research_progress("cancelled", "Research cancelled")
        task_id = get_queue().submit_job(
            goal=f"Deep research: {request.question}",
            runner=runner,
            priority=TaskPriority.NORMAL,
            speak=None,
            on_cancel=on_cancel,
            kind="research",
        )
    except Exception as exc:
        if show_background_status and player and hasattr(player, "finish_research_progress"):
            player.finish_research_progress("failed", str(exc)[:160])
        raise
    if visible:
        return (
            f"Visible deep research started (ID: {task_id}). "
            "I am opening the controlled browser and visiting the search results and source pages now."
        )
    return (
        f"Deep research started in the background (ID: {task_id}). "
        "The background status bar will remain visible. When finished, I will give you a detailed summary "
        "and offer to save the report or read it in full."
    )


def _execution_mode(parameters: dict | None) -> str:
    value = str((parameters or {}).get("execution_mode", "ask") or "ask").strip().lower()
    aliases = {
        "foreground": "visible",
        "live": "visible",
        "show": "visible",
        "watch": "visible",
        "quiet": "background",
    }
    value = aliases.get(value, value)
    if value not in {"ask", "background", "visible"}:
        raise ValueError("Execution mode must be ask, background, or visible.")
    return value


def _remember_pending(parameters: dict) -> None:
    global _pending_parameters, _pending_created_at
    stored = dict(parameters)
    stored.pop("execution_mode", None)
    from core.tenant import get_current_user_id

    user_id = get_current_user_id()
    with _pending_lock:
        if user_id:
            _tenant_pending[user_id] = (stored, time.monotonic())
        else:
            _pending_parameters = stored
            _pending_created_at = time.monotonic()


def _take_pending(parameters: dict) -> dict | None:
    global _pending_parameters, _pending_created_at
    supplied = dict(parameters)
    supplied.pop("execution_mode", None)
    from core.tenant import get_current_user_id

    user_id = get_current_user_id()
    with _pending_lock:
        if user_id:
            pending, created_at = _tenant_pending.pop(user_id, (None, 0.0))
            age = time.monotonic() - created_at
        else:
            pending = _pending_parameters
            age = time.monotonic() - _pending_created_at
            _pending_parameters = None
            _pending_created_at = 0.0
    if pending is not None and age <= PENDING_TTL_SECONDS:
        merged = dict(pending)
        merged.update({
            key: value for key, value in supplied.items()
            if value not in (None, "", [])
            and not (key in {"_persona_name", "_persona_attribution"} and key in merged)
        })
        return merged
    return None


def request_deep_research(parameters: dict, player=None, speak=None) -> str:
    """Ask for execution preference, or start a previously confirmed request."""
    params = dict(parameters or {})
    result_action = _handle_result_action(params)
    if result_action is not None:
        return result_action
    mode = _execution_mode(params)
    if mode == "ask":
        request = ResearchRequest.from_parameters(params)
        _remember_pending(params)
        if player and hasattr(player, "write_log"):
            player.write_log(f"deep_research: Waiting for run-mode choice for {request.question[:70]}")
        return RUN_MODE_QUESTION

    resolved = _take_pending(params)
    if resolved is None:
        if params.get("question") or params.get("topic") or params.get("query"):
            ResearchRequest.from_parameters(params)
            _remember_pending(params)
            return RUN_MODE_QUESTION
        return "Tell me what you want researched first, then I will ask how you want it to run."
    return queue_deep_research(
        resolved,
        player=player,
        speak=speak,
        visible=(mode == "visible"),
    )


def deep_research(parameters: dict, response=None, player=None, session_memory=None) -> str:
    try:
        return request_deep_research(parameters or {}, player=player)
    except Exception as exc:
        return f"Deep research failed: {exc}"
