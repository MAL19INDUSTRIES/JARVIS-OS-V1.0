import json
import queue
import re
import threading
import time
import unicodedata
from pathlib import Path


AMBIGUOUS_PREFIX = "RECIPIENT_AMBIGUOUS|"
NO_MATCH_PREFIX = "RECIPIENT_NOT_FOUND|"
INSTAGRAM_INBOX_URL = "https://www.instagram.com/direct/inbox/"
INSTAGRAM_PROFILE = Path.home() / ".jarvis_profiles" / "instagram"


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", str(text or ""))
        if not unicodedata.combining(ch)
    )


def _name_norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _strip_accents(text).lower())


def _sound_norm(text: str) -> str:
    value = _name_norm(text)
    for old, new in (
        ("eigh", "ay"),
        ("ai", "ay"),
        ("ei", "ay"),
        ("ey", "ay"),
        ("ie", "y"),
        ("ph", "f"),
        ("ck", "k"),
        ("qu", "k"),
        ("c", "k"),
        ("q", "k"),
        ("z", "s"),
        ("x", "ks"),
        ("y", "i"),
    ):
        value = value.replace(old, new)
    return re.sub(r"(.)\1+", r"\1", value)


def _name_score(query: str, candidate: str) -> float:
    import difflib

    q = _name_norm(query)
    c = _name_norm(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c or c in q:
        return 0.92
    score = difflib.SequenceMatcher(None, q, c).ratio()
    qs = _sound_norm(query)
    cs = _sound_norm(candidate)
    if qs and cs:
        if qs == cs:
            score = max(score, 0.96)
        elif qs in cs or cs in qs:
            score = max(score, 0.9)
        else:
            score = max(score, difflib.SequenceMatcher(None, qs, cs).ratio() * 0.95)
    return score


def _best_name_matches(query: str, candidates: list[dict], *, limit: int = 5) -> tuple[list[dict], bool]:
    scored: list[tuple[float, dict]] = []
    for candidate in candidates:
        name = str(candidate.get("name", "") or "").strip()
        aliases = [name] + [str(a or "") for a in candidate.get("aliases", [])]
        score = max((_name_score(query, alias) for alias in aliases), default=0.0)
        if score >= 0.72:
            item = dict(candidate)
            item["score"] = round(score, 3)
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("name", "")).lower()))
    matches = [item for _, item in scored[:limit]]
    if not matches:
        return [], False
    top = float(matches[0].get("score", 0.0))
    ambiguous = len(matches) > 1 and float(matches[1].get("score", 0.0)) >= max(0.78, top - 0.08)
    return matches, ambiguous


def _ambiguous_result(original: str, message: str, choices: list[dict]) -> str:
    safe_choices = []
    for index, choice in enumerate(choices[:5], start=1):
        safe_choices.append({
            "index": index,
            "name": str(choice.get("name", "") or "").strip(),
            "handle": str(choice.get("handle", "") or "").strip(),
            "platform": "Instagram",
        })
    payload = {
        "platform": "Instagram",
        "original": original,
        "message_text": message,
        "choices": safe_choices,
    }
    names = ", ".join(f"{choice['index']}. {choice['name']}" for choice in safe_choices)
    return AMBIGUOUS_PREFIX + json.dumps(payload, separators=(",", ":")) + f"\nMultiple matches for '{original}': {names}. Which one?"


def _literal_name_norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().strip("@")).casefold()


def _has_literal_recipient_match(query: str, candidate: dict) -> bool:
    target = _literal_name_norm(query)
    if not target:
        return False
    aliases = [
        str(candidate.get("name", "") or ""),
        str(candidate.get("handle", "") or ""),
        *[str(alias or "") for alias in candidate.get("aliases", [])],
    ]
    return any(_literal_name_norm(alias) == target for alias in aliases if alias)


def _recipient_confirmation_result(original: str, message: str, choice: dict) -> str:
    name = str(choice.get("name", "") or "").strip()
    handle = str(choice.get("handle", "") or "").strip()
    payload = {
        "platform": "Instagram",
        "original": original,
        "message_text": message,
        "confirm_single": True,
        "choices": [{
            "index": 1,
            "name": name,
            "handle": handle,
            "platform": "Instagram",
        }],
    }
    return (
        AMBIGUOUS_PREFIX
        + json.dumps(payload, separators=(",", ":"))
        + f"\nDid you mean {name or handle}?"
    )


class _InstagramBrowser:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._tasks: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._init_error: Exception | None = None
        self._pw = None
        self._context = None
        self._page = None
        self._pending: dict = {}

    def _merge_chat_rows(self, rows: list[dict]) -> list[dict]:
        merged: dict[str, dict] = {}
        order: list[str] = []
        for row in rows:
            name = str(row.get("name", "") or "").strip()
            if not name:
                continue
            handle = str(row.get("handle", "") or "").strip()
            key = _name_norm(name)
            if not key:
                continue
            if key not in merged:
                merged[key] = {
                    "name": name,
                    "handle": handle,
                    "aliases": [],
                    "text": str(row.get("text", "") or ""),
                }
                order.append(key)
            current = merged[key]
            if handle and "/direct/" in handle and "/direct/" not in str(current.get("handle", "")):
                current["handle"] = handle
            elif not current.get("handle") and handle:
                current["handle"] = handle
            aliases = [name, handle] + [str(alias or "") for alias in row.get("aliases", [])]
            for alias in aliases:
                alias = alias.strip().strip("/")
                if alias and alias not in current["aliases"]:
                    current["aliases"].append(alias)
            if row.get("text") and not current.get("text"):
                current["text"] = str(row.get("text", "") or "")
        return [merged[key] for key in order]

    def _start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="InstagramBrowser")
        self._thread.start()
        self._ready.wait(timeout=20)

    def _worker(self) -> None:
        try:
            from playwright.sync_api import sync_playwright

            self._pw = sync_playwright().start()
        except Exception as exc:
            self._init_error = exc
        finally:
            self._ready.set()

        while True:
            method_name, args, kwargs, result_q = self._tasks.get()
            if method_name is None:
                break
            try:
                if self._init_error:
                    raise RuntimeError(
                        "Playwright is not ready. Install browser support with: python3 -m playwright install chromium"
                    ) from self._init_error
                result = getattr(self, method_name)(*args, **kwargs)
                result_q.put((True, result))
            except Exception as exc:
                result_q.put((False, exc))

    def _closed_error(self, exc: Exception) -> bool:
        text = str(exc or "").lower()
        return (
            "target page, context or browser has been closed" in text
            or "browsercontext.new_page" in text and "closed" in text
            or "page.bring_to_front" in text and "closed" in text
        )

    def _discard_context(self) -> None:
        for obj in (self._context,):
            if obj is None:
                continue
            try:
                obj.close()
            except Exception:
                pass
        self._context = None
        self._page = None
        self._pending = {}

    def _call(self, method_name: str, *args, timeout: float = 90.0, **kwargs):
        self._start()
        last_error = None
        for attempt in range(2):
            result_q: queue.Queue = queue.Queue(maxsize=1)
            self._tasks.put((method_name, args, kwargs, result_q))
            ok, value = result_q.get(timeout=timeout)
            if ok:
                return value
            last_error = value
            if attempt == 0 and self._closed_error(value):
                reset_q: queue.Queue = queue.Queue(maxsize=1)
                self._tasks.put(("_discard_context", (), {}, reset_q))
                try:
                    reset_q.get(timeout=10)
                except Exception:
                    pass
                continue
            raise value
        raise last_error

    def _ensure_page(self):
        if self._context is None:
            INSTAGRAM_PROFILE.mkdir(parents=True, exist_ok=True)
            chromium = self._pw.chromium
            kwargs = {
                "headless": False,
                "no_viewport": True,
                "viewport": None,
                "args": [
                    "--start-maximized",
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--disable-default-apps",
                    "--no-default-browser-check",
                ],
            }
            try:
                self._context = chromium.launch_persistent_context(
                    str(INSTAGRAM_PROFILE),
                    channel="chrome",
                    **kwargs,
                )
            except Exception:
                self._context = chromium.launch_persistent_context(str(INSTAGRAM_PROFILE), **kwargs)
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        try:
            page_closed = self._page is None or self._page.is_closed()
        except Exception:
            self._discard_context()
            return self._ensure_page()
        if page_closed:
            self._page = self._context.new_page()
        return self._page

    def _open_inbox(self):
        page = self._ensure_page()
        if "instagram.com/direct" not in str(page.url or ""):
            page.goto(INSTAGRAM_INBOX_URL, wait_until="domcontentloaded", timeout=30_000)
        page.bring_to_front()
        page.wait_for_timeout(800)
        self._dismiss_interruptions(page)
        page.wait_for_timeout(250)
        self._dismiss_interruptions(page)
        return page

    def _limit_modal_visible(self, page) -> bool:
        try:
            return bool(page.evaluate(
                """
() => {
  const text = String(document.body && document.body.innerText || '').replace(/\\s+/g, ' ').toLowerCase();
  return text.includes("you've reached your daily limit")
    || text.includes("you have reached your daily limit")
    || text.includes('daily limit')
    || text.includes('time limit')
    || text.includes("you're in sleep mode")
    || text.includes('you are in sleep mode')
    || text.includes('sleep mode');
}
"""
            ))
        except Exception:
            return False

    def _dismiss_interruptions(self, page) -> bool:
        """Close Instagram interruption dialogs that block normal DM work."""
        dismissed = False
        if self._limit_modal_visible(page):
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(150)
                dismissed = True
            except Exception:
                pass
        try:
            result = page.evaluate(
                """
() => {
  const clean = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 8 && r.height > 8 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const bodyText = clean(document.body && document.body.innerText).toLowerCase();
  const hasLimit = bodyText.includes("you've reached your daily limit")
    || bodyText.includes("you have reached your daily limit")
    || bodyText.includes('daily limit')
    || bodyText.includes('time limit');
  const hasSleepMode = bodyText.includes("you're in sleep mode")
    || bodyText.includes('you are in sleep mode')
    || bodyText.includes('sleep mode');
  const dialogs = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"]')).filter(visible);
  const roots = dialogs.length ? dialogs : ((hasLimit || hasSleepMode) ? [document.body] : []);
  let clicked = false;
  const clickEl = (el) => {
    if (!el || !visible(el)) return false;
    el.click();
    clicked = true;
    return true;
  };
  for (const dialog of roots) {
    const text = clean(dialog.innerText || dialog.textContent).toLowerCase();
    const isLimit = hasLimit || text.includes('time limit') || text.includes('limit reached') || text.includes('daily limit');
    const isSleepMode = hasSleepMode || text.includes("you're in sleep mode") || text.includes('you are in sleep mode') || text.includes('sleep mode');
    const isRoutine = isLimit || isSleepMode || text.includes('turn on notifications') || text.includes('save login info');
    if (!isRoutine) continue;
    const buttons = Array.from(dialog.querySelectorAll('button, div[role="button"], [aria-label], svg[aria-label]')).filter(visible);
    const close = buttons.find(el => {
      const label = clean([el.getAttribute && el.getAttribute('aria-label'), el.getAttribute && el.getAttribute('title'), el.innerText, el.textContent].filter(Boolean).join(' ')).toLowerCase();
      return label === 'close'
        || label === 'x'
        || label.includes('close')
        || label.includes('not now')
        || label.includes('dismiss')
        || label === 'ok'
        || label === 'okay'
        || label === 'done'
        || label === 'continue'
        || label.includes('continue')
        || label.includes('use instagram')
        || label.includes('turn off')
        || label.includes('disable sleep');
    });
    if (clickEl(close)) return true;
    const rect = dialog.getBoundingClientRect && dialog.getBoundingClientRect();
    if (rect && (isLimit || isSleepMode)) {
      const topRight = document.elementFromPoint(Math.max(0, rect.right - 24), Math.max(0, rect.top + 24));
      if (clickEl(topRight && (topRight.closest('button, div[role="button"], [aria-label]') || topRight))) return true;
    }
  }
  return clicked;
}
"""
            )
            dismissed = bool(result) or dismissed
            page.wait_for_timeout(250)
        except Exception:
            pass
        if self._limit_modal_visible(page):
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(150)
                dismissed = True
            except Exception:
                pass
        return dismissed and not self._limit_modal_visible(page)

    def _login_required(self, page) -> bool:
        url = str(page.url or "").lower()
        if "/accounts/login" in url or "/accounts/emailsignup" in url:
            return True
        try:
            if page.locator('input[name="username"], input[name="password"]').count() > 0:
                return True
        except Exception:
            pass
        return False

    def _login_message(self) -> str:
        return "Instagram login required. I opened the JARVIS Instagram browser; log in there, then try again."

    def _read_rows(self, page) -> list[dict]:
        rows = page.evaluate(
            """
() => {
  const clean = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
  const ignoredLine = (line) => /^(active|online|seen|sent|you sent|replied|typing|now|today|yesterday|message|messages|notes|requests|primary|general|channels|\\d+[smhdw]\\b|.* ago$)$/i.test(line);
  const badName = (line) => !line || /^(home|search|explore|reels|create|profile|more|threads|notifications|meta ai)$/i.test(line) || ignoredLine(line);
  const visible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 30 && r.height > 18 && s.display !== 'none' && s.visibility !== 'hidden' && r.bottom > 70;
  };
  const profileNameFromAlt = (el) => {
    const images = Array.from((el.querySelector && el.querySelectorAll('img[alt]')) || []);
    for (const img of images) {
      const alt = clean(img && img.getAttribute('alt'));
      const match = alt.match(/^(.*?)'s profile picture$/i) || alt.match(/^(.*?) profile picture$/i);
      const name = clean(match ? match[1] : '');
      if (name && !badName(name)) return name;
    }
    return '';
  };
  const rowName = (el) => {
    const fromAlt = profileNameFromAlt(el);
    if (fromAlt && !badName(fromAlt)) return fromAlt;
    const raw = String(el.innerText || el.textContent || '');
    const lines = raw.split(/\\n+/).map(clean).filter(Boolean);
    const fromText = lines.find(line => !badName(line));
    return clean(fromText || '');
  };
  const rowText = (el) => String(el.innerText || el.textContent || '')
    .split(/\\n+/).map(clean).filter(Boolean).slice(0, 5).join(' | ').slice(0, 180);
  const rowHref = (el) => {
    if (el.href && /\\/direct\\//.test(el.href)) return el.href;
    const nested = el.querySelector && el.querySelector('a[href*="/direct/"]');
    if (nested) return nested.href || nested.getAttribute('href') || '';
    return '';
  };
  const profileAlias = (el) => {
    const profileLink = el.querySelector && el.querySelector('a[href^="/"]:not([href*="/direct/"])');
    const href = (el.href || (el.getAttribute && el.getAttribute('href')) || (profileLink && profileLink.getAttribute('href')) || '').trim();
    if (!href || /\\/direct\\//.test(href)) return '';
    const parts = href.split('/').filter(Boolean);
    return clean(parts[parts.length - 1] || '');
  };
  const leftLimit = Math.max(360, window.innerWidth * 0.42);
  const messagesHeadingBottom = (() => {
    const labels = Array.from(document.querySelectorAll('span, div, h1, h2, h3'))
      .filter(visible)
      .map(el => ({el, text: clean(el.innerText || el.textContent), rect: el.getBoundingClientRect()}))
      .filter(item => item.rect.left >= 60 && item.rect.left <= leftLimit && item.rect.top > 60 && item.rect.top < innerHeight * 0.7 && /^messages$/i.test(item.text));
    labels.sort((a, b) => a.rect.top - b.rect.top);
    return labels.length ? labels[0].rect.bottom : 0;
  })();
  const rows = [];
  const seen = new Set();
  const candidates = Array.from(document.querySelectorAll([
    'a[href*="/direct/t/"]',
    'a[href*="/direct/"]',
    'div[role="button"]',
    '[tabindex="0"]'
  ].join(',')));
  for (const el of candidates) {
    const rect = el.getBoundingClientRect && el.getBoundingClientRect();
    if (!rect || rect.width < 80 || rect.height < 28) continue;
    if (rect.left > leftLimit || rect.left < 60 || rect.right < 180) continue;
    if (messagesHeadingBottom && rect.top <= messagesHeadingBottom + 4) continue;
    const href = rowHref(el);
    const rawText = rowText(el);
    // Instagram's 2026 inbox renders conversation rows as wide role=button
    // containers without a /direct/ anchor or a literal Messages heading.
    // Notes use small/tall tiles, so require the stable list-row geometry and
    // a profile image before treating an unlinked button as a conversation.
    const structuralChatRow = !!(
      el.matches && el.matches('div[role="button"], [tabindex="0"]')
      && el.querySelector && el.querySelector('img')
      && rect.width >= 220 && rect.height >= 44 && rect.height <= 120
      && rect.top > 240
    );
    if (!href && !messagesHeadingBottom && !structuralChatRow) continue;
    if (!href && !rawText && !profileNameFromAlt(el)) continue;
    let name = rowName(el);
    name = name.replace(/^@/, '').trim();
    if (badName(name)) continue;
    const key = name.toLowerCase() + '|' + (href || rawText);
    if (seen.has(key)) continue;
    seen.add(key);
    const aliases = [name];
    const profile = profileAlias(el);
    if (profile && !/^direct$/i.test(profile)) aliases.push(profile);
    if (href) {
      const parts = String(href).split('/').filter(Boolean);
      const last = parts[parts.length - 1] || '';
      if (last && !/^direct$/i.test(last)) aliases.push(last);
    }
    rows.push({name, handle: href || name, aliases, text: rawText});
    if (rows.length >= 40) break;
  }
  return rows;
}
"""
        )
        return self._merge_chat_rows([row for row in rows if isinstance(row, dict) and row.get("name")])

    def _scroll_dm_list(self, page) -> dict:
        return page.evaluate(
            """
() => {
  const findScrollable = () => {
    const leftLimit = Math.max(360, window.innerWidth * 0.42);
    const clean = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
    const visible = (el) => {
      if (!el || !el.getBoundingClientRect) return false;
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 8 && r.height > 8 && s.display !== 'none' && s.visibility !== 'hidden';
    };
    const headings = Array.from(document.querySelectorAll('span, div, h1, h2, h3'))
      .filter(visible)
      .map(el => ({text: clean(el.innerText || el.textContent), rect: el.getBoundingClientRect()}))
      .filter(item => item.rect.left >= 60 && item.rect.left <= leftLimit && item.rect.top > 60 && item.rect.top < innerHeight * 0.7 && /^messages$/i.test(item.text))
      .sort((a, b) => a.rect.top - b.rect.top);
    const headingBottom = headings.length ? headings[0].rect.bottom : 0;
    const candidates = Array.from(document.querySelectorAll('div, section, main'))
      .filter(el => {
        const r = el.getBoundingClientRect && el.getBoundingClientRect();
        if (!r || r.left > leftLimit || r.height < 120) return false;
        if (headingBottom && r.bottom <= headingBottom + 20) return false;
        return el.scrollHeight > el.clientHeight + 20;
      })
      .sort((a, b) => {
        const ar = a.getBoundingClientRect();
        const br = b.getBoundingClientRect();
        const aScore = (headingBottom && ar.top <= headingBottom + 40 ? 10000 : 0) + (a.scrollHeight - a.clientHeight);
        const bScore = (headingBottom && br.top <= headingBottom + 40 ? 10000 : 0) + (b.scrollHeight - b.clientHeight);
        return bScore - aScore;
      });
    return candidates[0] || document.scrollingElement || document.documentElement;
  };
  const scrollable = findScrollable();
  if (!scrollable) return {ok:false, reachedEnd:true};
  const before = scrollable.scrollTop;
  scrollable.scrollTop = before + 650;
  const reachedEnd = (scrollable.scrollTop + scrollable.clientHeight) >= (scrollable.scrollHeight - 4);
  return {ok:true, moved: scrollable.scrollTop !== before, reachedEnd};
}
"""
        )

    def _reset_dm_list(self, page) -> None:
        page.evaluate(
            """
() => {
  const setNativeValue = (el, value) => {
    const proto = el.tagName && el.tagName.toLowerCase() === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (setter) setter.call(el, value);
    else el.value = value;
    el.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'deleteContentBackward'}));
    el.dispatchEvent(new Event('change', {bubbles:true}));
  };
  for (const input of Array.from(document.querySelectorAll('input[placeholder], input[aria-label]'))) {
    const label = [input.getAttribute('placeholder'), input.getAttribute('aria-label')].filter(Boolean).join(' ').toLowerCase();
    if (label.includes('search')) setNativeValue(input, '');
  }
  const findScrollable = () => {
    const leftLimit = Math.max(360, window.innerWidth * 0.42);
    const clean = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
    const visible = (el) => {
      if (!el || !el.getBoundingClientRect) return false;
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 8 && r.height > 8 && s.display !== 'none' && s.visibility !== 'hidden';
    };
    const headings = Array.from(document.querySelectorAll('span, div, h1, h2, h3'))
      .filter(visible)
      .map(el => ({text: clean(el.innerText || el.textContent), rect: el.getBoundingClientRect()}))
      .filter(item => item.rect.left >= 60 && item.rect.left <= leftLimit && item.rect.top > 60 && item.rect.top < innerHeight * 0.7 && /^messages$/i.test(item.text))
      .sort((a, b) => a.rect.top - b.rect.top);
    const headingBottom = headings.length ? headings[0].rect.bottom : 0;
    const candidates = Array.from(document.querySelectorAll('div, section, main'))
      .filter(el => {
        const r = el.getBoundingClientRect && el.getBoundingClientRect();
        if (!r || r.left > leftLimit || r.height < 120) return false;
        if (headingBottom && r.bottom <= headingBottom + 20) return false;
        return el.scrollHeight > el.clientHeight + 20;
      })
      .sort((a, b) => {
        const ar = a.getBoundingClientRect();
        const br = b.getBoundingClientRect();
        const aScore = (headingBottom && ar.top <= headingBottom + 40 ? 10000 : 0) + (a.scrollHeight - a.clientHeight);
        const bScore = (headingBottom && br.top <= headingBottom + 40 ? 10000 : 0) + (b.scrollHeight - b.clientHeight);
        return bScore - aScore;
      });
    return candidates[0] || document.scrollingElement || document.documentElement;
  };
  const scrollable = findScrollable();
  if (scrollable) scrollable.scrollTop = 0;
}
"""
        )

    def _resolve_chat(self, page, receiver: str, message: str) -> tuple[dict | None, str | None]:
        receiver = str(receiver or "").strip()
        if not receiver:
            return None, None
        if receiver.startswith("http") and "instagram.com/direct" in receiver:
            return {"name": receiver, "handle": receiver, "aliases": [receiver]}, None

        self._reset_dm_list(page)
        all_rows: list[dict] = []
        best_ambiguous: list[dict] = []
        for _ in range(10):
            self._dismiss_interruptions(page)
            rows = self._read_rows(page)
            for row in rows:
                key = str(row.get("handle") or row.get("name") or "")
                if key and all(str(existing.get("handle")) != key for existing in all_rows):
                    all_rows.append(row)
            matches, ambiguous = _best_name_matches(receiver, all_rows)
            if matches and not ambiguous:
                if not _has_literal_recipient_match(receiver, matches[0]):
                    return None, _recipient_confirmation_result(receiver, message, matches[0])
                return matches[0], None
            if matches and ambiguous:
                best_ambiguous = matches
            scroll = self._scroll_dm_list(page)
            if not scroll.get("ok") or scroll.get("reachedEnd") or not scroll.get("moved"):
                break
            page.wait_for_timeout(250)

        if best_ambiguous:
            return None, _ambiguous_result(receiver, message, best_ambiguous)
        if not all_rows:
            self._dismiss_interruptions(page)
            url = str(page.url or "")
            title = ""
            body_sample = ""
            try:
                title = str(page.title() or "")
                body_sample = str(page.locator("body").inner_text(timeout=1500) or "").replace("\n", " ")[:240]
            except Exception:
                pass
            if self._limit_modal_visible(page):
                return None, (
                    "Instagram's daily-limit notification is still blocking the DM list. "
                    "I tried to close it automatically, but Instagram did not dismiss it. "
                    "Close that popup in the JARVIS Instagram browser, then try again. "
                    f"Debug: url={url or 'unknown'}, title={title or 'unknown'}, visible_text={body_sample or 'none'}"
                )
            return None, (
                "I could not read your Instagram DM list. Log into the JARVIS Instagram browser and open Direct Messages, then try again. "
                f"Debug: url={url or 'unknown'}, title={title or 'unknown'}, visible_text={body_sample or 'none'}"
            )
        sample = ", ".join(str(row.get("name", "")) for row in all_rows[:8])
        return None, (
            f"{NO_MATCH_PREFIX}No recent Instagram chat sounded like '{receiver}'. "
            f"Visible chats: {sample}. I only search chats already in your Instagram messages, not global Instagram search. "
            "Open that DM in the JARVIS Instagram browser and leave the recipient blank, or message someone from the visible/recent DM list."
        )

    def _open_chat(self, page, chat: dict) -> bool:
        handle = str(chat.get("handle") or "").strip()
        if handle.startswith("http"):
            page.goto(handle, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(900)
            return True
        target = _name_norm(str(chat.get("name", "") or ""))
        return bool(page.evaluate(
            """
(target) => {
  const norm = (s) => String(s || '').normalize('NFKD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '');
  const clean = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
  const ignoredLine = (line) => /^(active|online|seen|sent|you sent|replied|typing|now|today|yesterday|message|messages|notes|requests|primary|general|channels|\\d+[smhdw]\\b|.* ago$)$/i.test(line);
  const badName = (line) => !line || /^(home|search|explore|reels|create|profile|more|threads|notifications|meta ai)$/i.test(line) || ignoredLine(line);
  const profileNameFromAlt = (el) => {
    const images = Array.from((el.querySelector && el.querySelectorAll('img[alt]')) || []);
    for (const img of images) {
      const alt = clean(img && img.getAttribute('alt'));
      const match = alt.match(/^(.*?)'s profile picture$/i) || alt.match(/^(.*?) profile picture$/i);
      const name = clean(match ? match[1] : '');
      if (name && !badName(name)) return name;
    }
    return '';
  };
  const rowName = (el) => {
    const fromAlt = profileNameFromAlt(el);
    if (fromAlt && !badName(fromAlt)) return fromAlt;
    const lines = String(el.innerText || el.textContent || '').split(/\\n+/).map(clean).filter(Boolean);
    return clean(lines.find(line => !badName(line)) || '');
  };
  const rowHref = (el) => {
    if (el.href && /\\/direct\\//.test(el.href)) return el.href;
    const nested = el.querySelector && el.querySelector('a[href*="/direct/"]');
    if (nested) return nested.href || nested.getAttribute('href') || '';
    return '';
  };
  const leftLimit = Math.max(360, window.innerWidth * 0.42);
  const messagesHeadingBottom = (() => {
    const visible = (el) => {
      if (!el || !el.getBoundingClientRect) return false;
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 30 && r.height > 18 && s.display !== 'none' && s.visibility !== 'hidden' && r.bottom > 70;
    };
    const labels = Array.from(document.querySelectorAll('span, div, h1, h2, h3'))
      .filter(visible)
      .map(el => ({text: clean(el.innerText || el.textContent), rect: el.getBoundingClientRect()}))
      .filter(item => item.rect.left >= 60 && item.rect.left <= leftLimit && item.rect.top > 60 && item.rect.top < innerHeight * 0.7 && /^messages$/i.test(item.text));
    labels.sort((a, b) => a.rect.top - b.rect.top);
    return labels.length ? labels[0].rect.bottom : 0;
  })();
  const candidates = Array.from(document.querySelectorAll([
    'a[href*="/direct/t/"]',
    'a[href*="/direct/"]',
    'div[role="button"]',
    '[tabindex="0"]'
  ].join(',')));
  for (const el of candidates) {
    const rect = el.getBoundingClientRect && el.getBoundingClientRect();
    if (!rect || rect.width < 80 || rect.height < 28) continue;
    if (rect.left > leftLimit || rect.left < 60 || rect.right < 120) continue;
    if (messagesHeadingBottom && rect.top <= messagesHeadingBottom + 4) continue;
    const structuralChatRow = !!(
      el.matches && el.matches('div[role="button"], [tabindex="0"]')
      && el.querySelector && el.querySelector('img')
      && rect.width >= 220 && rect.height >= 44 && rect.height <= 120
      && rect.top > 240
    );
    if (!rowHref(el) && !messagesHeadingBottom && !structuralChatRow) continue;
    const first = rowName(el);
    if (!badName(first) && (norm(first) === target || norm(first).includes(target) || target.includes(norm(first)))) {
      el.scrollIntoView({block:'center'});
      el.click();
      return true;
    }
  }
  return false;
}
""",
            target,
        ))

    def _active_recipient(self, page) -> str:
        data = page.evaluate(
            """
() => {
  const clean = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 20 && r.height > 10 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const sidebarRight = (document.querySelector('a[href*="/direct/t/"]')?.getBoundingClientRect()?.right) || (window.innerWidth * 0.32);
  const candidates = Array.from(document.querySelectorAll('header h1, header h2, header a, header span, h1, h2, a[href^="/"]'))
    .filter(visible)
    .filter(el => {
      const r = el.getBoundingClientRect();
      return r.left > sidebarRight + 20 && r.top < Math.max(180, innerHeight * 0.25);
    })
    .map(el => clean(el.innerText || el.textContent))
    .filter(Boolean)
    .map(text => text.split(/\\n+/).map(clean).filter(Boolean)[0] || text)
    .filter(text => !/^(messages|search|notes|requests|active|online|seen|sent|typing|message)$/i.test(text));
  return candidates[0] || '';
}
"""
        )
        return str(data or "").strip()

    def _active_chat_text(self, page) -> str:
        try:
            return str(page.evaluate(
                """
() => {
  const clean = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 20 && r.height > 10 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const sidebarRight = (document.querySelector('a[href*="/direct/t/"]')?.getBoundingClientRect()?.right) || (window.innerWidth * 0.32);
  const chunks = [];
  for (const el of Array.from(document.querySelectorAll('main header, main h1, main h2, main a[href^="/"], main span, main div'))) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.left <= sidebarRight + 20 || r.top > Math.max(260, innerHeight * 0.35)) continue;
    const text = clean(el.innerText || el.textContent);
    if (!text || text.length > 180) continue;
    if (/^(message|active|online|seen|sent|typing|details|info)$/i.test(text)) continue;
    chunks.push(text);
    if (chunks.length >= 12) break;
  }
  return chunks.join(' | ');
}
"""
            ) or "")
        except Exception:
            return ""

    def _verify_active_chat(self, page, chat: dict | str) -> bool:
        current_url = str(getattr(page, "url", "") or "").lower()
        if isinstance(chat, dict):
            expected_values = [
                str(chat.get("name", "") or ""),
                str(chat.get("handle", "") or ""),
                *[str(alias or "") for alias in chat.get("aliases", [])],
            ]
        else:
            expected_values = [str(chat or "")]
        expected_norms = {
            _name_norm(value.strip().strip("/"))
            for value in expected_values
            if value and not str(value).startswith("http")
        }
        expected_norms = {value for value in expected_norms if value and value != "direct"}
        if not expected_norms:
            return True
        active = _name_norm(self._active_recipient(page))
        pane_text = _name_norm(self._active_chat_text(page))
        if (
            (active and any(expected in active or active in expected for expected in expected_norms))
            or (pane_text and any(expected in pane_text for expected in expected_norms))
        ):
            return True

        # Instagram often renders decorative/profile text in the header that
        # does not equal the DM row label. If we matched and clicked a DM row
        # and the page is now on an actual direct thread, trust that controlled
        # navigation rather than blocking on a flaky header read.
        if "instagram.com/direct/t/" in current_url or "/direct/t/" in current_url:
            return True
        return False

    def _focus_composer(self, page) -> bool:
        return bool(page.evaluate(
            """
() => {
  const visible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 20 && r.height > 10 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const labelOf = (el) => [
    el.getAttribute && el.getAttribute('aria-label'),
    el.getAttribute && el.getAttribute('placeholder'),
    el.getAttribute && el.getAttribute('role'),
    el.getAttribute && el.getAttribute('name'),
    el.innerText,
    el.textContent
  ].filter(Boolean).join(' ').toLowerCase();
  const candidates = Array.from(document.querySelectorAll(
    'div[contenteditable="true"][role="textbox"], div[contenteditable="true"], textarea, input[type="text"]'
  )).filter(visible);
  const composer = candidates.filter(el => {
    const label = labelOf(el);
    const r = el.getBoundingClientRect();
    return label.includes('message') || label.includes('reply') || label.includes('chat') || r.bottom > innerHeight * 0.55;
  }).sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom)[0] || null;
  if (!composer) return false;
  composer.focus();
  return true;
}
"""
        ))

    def _fill_composer(self, page, message: str) -> bool:
        self._dismiss_interruptions(page)
        self._clear_composer(page)
        if not self._focus_composer(page):
            return False
        typed_message = re.sub(r"\s*\n+\s*", " ", str(message or "")).strip()
        page.keyboard.type(typed_message, delay=8)
        page.wait_for_timeout(150)
        return True

    def _composer_text(self, page) -> str:
        try:
            return str(page.evaluate(
                """
() => {
  const visible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 20 && r.height > 10 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const composer = Array.from(document.querySelectorAll(
    'div[contenteditable="true"][role="textbox"], div[contenteditable="true"], textarea, input[type="text"]'
  )).filter(visible).sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom)[0] || null;
  if (!composer) return '';
  if (composer.tagName && /^(textarea|input)$/i.test(composer.tagName)) return String(composer.value || '');
  return String(composer.innerText || composer.textContent || '');
}
"""
            ) or "").strip()
        except Exception:
            return ""

    def _send_composer(self, page) -> bool:
        sent = bool(page.evaluate(
            """
() => {
  const visible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 20 && r.height > 10 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const labelOf = (el) => [
    el.getAttribute && el.getAttribute('aria-label'),
    el.getAttribute && el.getAttribute('title'),
    el.innerText,
    el.textContent
  ].filter(Boolean).join(' ').trim().toLowerCase();
  const buttons = Array.from(document.querySelectorAll('button, div[role="button"], [aria-label]'))
    .filter(visible)
    .filter(el => /^(send|send message)$/i.test(labelOf(el)) || labelOf(el).includes('send'));
  const button = buttons[buttons.length - 1] || null;
  if (!button) return false;
  button.click();
  return true;
}
"""
        ))
        if sent:
            page.wait_for_timeout(500)
            if not self._composer_text(page):
                return True
        composer = page.locator('div[contenteditable="true"][role="textbox"], div[contenteditable="true"], textarea, input[type="text"]').last
        composer.press("Enter", timeout=3_000)
        page.wait_for_timeout(500)
        return not bool(self._composer_text(page))

    def _clear_composer(self, page) -> bool:
        return bool(page.evaluate(
            """
() => {
  const visible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 20 && r.height > 10 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const composer = Array.from(document.querySelectorAll(
    'div[contenteditable="true"][role="textbox"], div[contenteditable="true"], textarea, input[type="text"]'
  )).filter(visible).sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom)[0] || null;
  if (!composer) return false;
  composer.focus();
  if (composer.tagName && /^(textarea|input)$/i.test(composer.tagName)) {
    const proto = composer.tagName.toLowerCase() === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (setter) setter.call(composer, '');
    else composer.value = '';
    composer.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'deleteContentBackward'}));
  } else {
    composer.innerHTML = '';
    composer.textContent = '';
    composer.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'deleteContentBackward'}));
  }
  return true;
}
"""
        ))

    def _prepare_draft(self, receiver: str, message: str) -> str:
        page = self._open_inbox()
        if self._login_required(page):
            return self._login_message()

        chat = None
        recipient = str(receiver or "").strip()
        if recipient:
            chat, error = self._resolve_chat(page, recipient, message)
            if error:
                return error
            if chat and not self._open_chat(page, chat):
                return f"Found Instagram chat '{chat.get('name')}', but could not open it."
            page.wait_for_timeout(900)
            if chat and not self._verify_active_chat(page, chat):
                return f"I could not verify that the open Instagram chat belongs to '{chat.get('name') or recipient}'."
            recipient = str(chat.get("name") or recipient) if chat else recipient
        else:
            recipient = self._active_recipient(page)
            if not recipient:
                return "Open an Instagram DM in the JARVIS Instagram browser, or provide a recipient name."

        if not self._fill_composer(page, message):
            return "I could not type into the Instagram composer. Keep the JARVIS Instagram browser on the desired DM and try again."

        self._pending = {
            "recipient": recipient,
            "message": message,
            "created_at": time.time(),
            "url": page.url,
        }
        return f"Draft typed in the open Instagram chat. Awaiting your approval to send."

    def _send_draft(self) -> str:
        page = self._open_inbox()
        if self._login_required(page):
            return self._login_message()
        if not self._pending:
            return "Could not find a pending Instagram draft. Ask JARVIS to prepare the Instagram message again."
        self._dismiss_interruptions(page)

        pending_url = str(self._pending.get("url") or "").split("?", 1)[0].rstrip("/")
        current_url = str(page.url or "").split("?", 1)[0].rstrip("/")
        if pending_url and current_url != pending_url:
            return (
                "Instagram chat changed after the draft was prepared, so I did not send it. "
                "Return to the original draft or cancel and prepare the message again."
            )

        expected = re.sub(r"\s+", " ", str(self._pending.get("message") or "")).strip()
        visible_draft = re.sub(r"\s+", " ", self._composer_text(page)).strip()
        if not visible_draft or visible_draft != expected:
            return (
                "The visible Instagram draft no longer matches the approved message, so I did not send it. "
                "Cancel and prepare the message again."
            )
        if not self._send_composer(page):
            return (
                "Instagram did not clear the approved draft after the send attempt, "
                "so I cannot confirm it was sent. The draft remains visible."
            )
        recipient = str(self._pending.get("recipient") or "current chat")
        self._pending = {}
        return f"Message sent to {recipient} via Instagram."

    def _clear_draft(self) -> bool:
        page = self._open_inbox()
        cleared = self._clear_composer(page)
        self._pending = {}
        return cleared

    def _read_open_chat(self) -> dict:
        page = self._open_inbox()
        if self._login_required(page):
            return {"ok": False, "platform": "Instagram", "error": self._login_message()}
        recipient = self._active_recipient(page)
        data = page.evaluate(
            """
(recipient) => {
  const clean = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
  const noise = (line) => /^(active|online|seen|sent|delivered|read|typing|now|message|message\\.\\.\\.|details|info)$/i.test(line)
    || /^(active|seen|sent|delivered|read).*(ago|now)$/i.test(line)
    || /^\\d+[smhdw]\\b/i.test(line)
    || / ago$/i.test(line);
  const visible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 20 && r.height > 10 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const sidebarRight = (document.querySelector('a[href*="/direct/t/"]')?.getBoundingClientRect()?.right) || (window.innerWidth * 0.32);
  const lines = [];
  const seen = new Set();
  for (const el of Array.from(document.querySelectorAll('main div, main span, main p'))) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.left <= sidebarRight + 20 || r.top < 80 || r.bottom > innerHeight - 40) continue;
    const text = clean(el.innerText || el.textContent);
    if (!text || text.length > 500) continue;
    for (const line of text.split(/\\n+/).map(clean).filter(Boolean)) {
      if (noise(line)) continue;
      if (recipient && line === recipient) continue;
      if (/^(account|your note)$/i.test(line)) continue;
      const key = line.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      lines.push(line);
    }
  }
  const conversation = lines.slice(-30);
  return {
    visible_messages: conversation.slice(-10),
    conversation_context: conversation,
    message_count: conversation.length,
    latest_message: lines[lines.length - 1] || ''
  };
}
""",
            recipient,
        )
        messages = data.get("visible_messages", []) if isinstance(data, dict) else []
        conversation = data.get("conversation_context", messages) if isinstance(data, dict) else messages
        latest = data.get("latest_message", "") if isinstance(data, dict) else ""
        return {
            "ok": bool(recipient or messages),
            "platform": "Instagram",
            "recipient": recipient,
            "latest_message": latest,
            "visible_messages": messages,
            "conversation_context": conversation,
            "message_count": data.get("message_count", len(conversation)) if isinstance(data, dict) else len(conversation),
            "can_reply": bool(recipient and messages),
            "source": page.url,
        }


_instagram = _InstagramBrowser()


def prepare_instagram_draft(receiver: str, message: str) -> str:
    try:
        return _instagram._call("_prepare_draft", receiver, message)
    except Exception as exc:
        return f"Could not prepare Instagram draft: {exc}"


def send_instagram_draft() -> str:
    try:
        return _instagram._call("_send_draft")
    except Exception as exc:
        return f"Could not send Instagram draft: {exc}"


def clear_instagram_draft() -> bool:
    try:
        return bool(_instagram._call("_clear_draft", timeout=30.0))
    except Exception:
        return False


def read_instagram_open_chat() -> dict:
    try:
        return _instagram._call("_read_open_chat", timeout=45.0)
    except Exception as exc:
        return {"ok": False, "platform": "Instagram", "error": f"Could not read Instagram chat: {exc}"}
