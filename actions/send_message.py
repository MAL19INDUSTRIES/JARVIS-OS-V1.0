import json
import io
import difflib
import re
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

from actions.safe_text_entry import safe_type_then_enter
from actions.instagram_browser import (
    prepare_instagram_draft as _controlled_instagram_prepare_draft,
    send_instagram_draft as _controlled_instagram_send_draft,
    clear_instagram_draft as _controlled_instagram_clear_draft,
)

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.06
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

JARVIS_TEXT_FOOTER = "CREATED BY JARVIS"
PERSONA_TEXT_FOOTERS = {
    "JARVIS": JARVIS_TEXT_FOOTER,
    "ULTRON": "CREATED BY ULTRON",
    "ATLAS": "CREATED BY ATLAS",
}
_PERSONA_FOOTER_RE = re.compile(
    r"(?im)^\s*CREATED BY (?:JARVIS|ULTRON|ATLAS)\s*$"
)
AMBIGUOUS_PREFIX = "RECIPIENT_AMBIGUOUS|"
NO_MATCH_PREFIX = "RECIPIENT_NOT_FOUND|"
MESSAGE_DUPLICATE_TTL_SECONDS = 120.0
CONTACTS_CACHE_TTL_SECONDS = 300.0
_recent_send_fingerprints: dict[str, float] = {}
_contacts_cache: tuple[float, list[dict]] = (0.0, [])
_contacts_scan_failed_until = 0.0
_last_browser_focus_error = ""
_pending_message_approval: dict = {}
_pending_message_lock = threading.Lock()


def _set_pending_message(platform: str, receiver: str, message: str) -> None:
    with _pending_message_lock:
        _pending_message_approval.clear()
        _pending_message_approval.update({
            "platform": str(platform or "").strip(),
            "receiver": str(receiver or "").strip(),
            "message_text": str(message or "").strip(),
            "created_at": time.time(),
        })


def _get_pending_message() -> dict:
    with _pending_message_lock:
        return dict(_pending_message_approval)


def _clear_pending_message() -> None:
    with _pending_message_lock:
        _pending_message_approval.clear()


def _is_instagram_platform(platform: str) -> bool:
    key = re.sub(r"[^a-z]+", " ", str(platform or "").lower()).strip()
    return key in {"instagram", "ig", "insta"} or "instagram" in key.split()


def normalize_outgoing_message_text(text: str) -> str:
    message = re.sub(r"[ \t]+", " ", str(text or "").strip())
    message = re.sub(r"\s+\n", "\n", message)
    message = re.sub(r"\n\s+", "\n", message)
    if not message:
        return ""

    def fix_sentence(match: re.Match) -> str:
        prefix = match.group(1)
        char = match.group(2)
        return prefix + char.upper()

    message = re.sub(r"(^|[.!?]\s+)([a-z])", fix_sentence, message)
    if not re.search(r"[.!?…]$", message) and not _PERSONA_FOOTER_RE.search(message):
        message += "."
    return message


def _friendly_browser_focus_error(error: str) -> str:
    text = str(error or "").strip()
    lowered = text.lower()
    if lowered in {"wrong_url", "composer_not_found"}:
        return ""
    if "executing javascript through applescript is turned off" in lowered:
        return (
            "Chrome is blocking browser automation. In Chrome, enable "
            "View > Developer > Allow JavaScript from Apple Events, then keep the desired web chat open and try again."
        )
    return text


def _set_browser_focus_error(error: str) -> None:
    global _last_browser_focus_error
    _last_browser_focus_error = _friendly_browser_focus_error(error)


def _browser_focus_error() -> str:
    return _last_browser_focus_error


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", str(text or ""))
        if not unicodedata.combining(ch)
    )


def _name_norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _strip_accents(text).lower())


def _message_norm(text: str) -> str:
    value = str(text or "")
    value = re.sub(
        r"\bcreated\s+by\s+(?:jarvis|ultron|atlas)\b",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = _strip_accents(value).lower()
    return re.sub(r"[^a-z0-9]+", "", value)


def _send_fingerprint(platform: str, receiver: str, message: str) -> str:
    return "|".join((
        _name_norm(platform),
        _name_norm(receiver),
        _message_norm(message),
    ))


def _prune_recent_sends(now: float | None = None) -> None:
    now = time.time() if now is None else now
    expired = [
        key for key, sent_at in _recent_send_fingerprints.items()
        if now - sent_at > MESSAGE_DUPLICATE_TTL_SECONDS
    ]
    for key in expired:
        _recent_send_fingerprints.pop(key, None)


def _duplicate_message_result(platform: str, receiver: str) -> str:
    target = receiver or "current chat"
    return f"Duplicate message suppressed; already sent to {target} via {platform}."


def _check_duplicate_send(platform: str, receiver: str, message: str) -> str | None:
    now = time.time()
    _prune_recent_sends(now)
    key = _send_fingerprint(platform, receiver, message)
    sent_at = _recent_send_fingerprints.get(key)
    if sent_at and now - sent_at <= MESSAGE_DUPLICATE_TTL_SECONDS:
        return _duplicate_message_result(platform, receiver)
    return None


def _record_successful_send(platform: str, receiver: str, message: str) -> None:
    _prune_recent_sends()
    _recent_send_fingerprints[_send_fingerprint(platform, receiver, message)] = time.time()


def _message_send_succeeded(result: str) -> bool:
    lowered = str(result or "").lower()
    return (
        "message sent" in lowered
        or "safely sent" in lowered
        or "sent in the open" in lowered
        or "sent to" in lowered
    ) and "could not" not in lowered and "duplicate message suppressed" not in lowered


def _sound_norm(text: str) -> str:
    value = _name_norm(text)
    replacements = (
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
    )
    for old, new in replacements:
        value = value.replace(old, new)
    return re.sub(r"(.)\1+", r"\1", value)


def _name_score(query: str, candidate: str) -> float:
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


def _ambiguous_result(platform: str, original: str, message: str, choices: list[dict]) -> str:
    safe_choices = []
    for index, choice in enumerate(choices[:5], start=1):
        safe_choices.append({
            "index": index,
            "name": str(choice.get("name", "") or "").strip(),
            "handle": str(choice.get("handle", "") or "").strip(),
            "platform": platform,
        })
    payload = {
        "platform": platform,
        "original": original,
        "message_text": message,
        "choices": safe_choices,
    }
    names = ", ".join(f"{c['index']}. {c['name']}" for c in safe_choices)
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


def _recipient_confirmation_result(platform: str, original: str, message: str, choice: dict) -> str:
    name = str(choice.get("name", "") or "").strip()
    handle = str(choice.get("handle", "") or "").strip()
    payload = {
        "platform": platform,
        "original": original,
        "message_text": message,
        "confirm_single": True,
        "choices": [{
            "index": 1,
            "name": name,
            "handle": handle,
            "platform": platform,
        }],
    }
    return (
        AMBIGUOUS_PREFIX
        + json.dumps(payload, separators=(",", ":"))
        + f"\nDid you mean {name or handle}?"
    )

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _get_os() -> str:
    try:
        cfg = json.loads(
            (_base_dir() / "config" / "api_keys.json").read_text(encoding="utf-8")
        )
        return cfg.get("os_system", "windows").lower()
    except Exception:
        return "windows"


def _get_api_key() -> str:
    try:
        cfg = json.loads(
            (_base_dir() / "config" / "api_keys.json").read_text(encoding="utf-8")
        )
        return cfg.get("gemini_api_key", "").strip()
    except Exception:
        return ""


def _require_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")


def _paste_text(text: str) -> None:
    _require_pyautogui()

    os_name = _get_os()
    paste_hotkey = ("command", "v") if os_name == "mac" else ("ctrl", "v")

    if _PYPERCLIP:
        try:
            pyperclip.copy(text)
            time.sleep(0.15)
            pyautogui.hotkey(*paste_hotkey)
            time.sleep(0.1)
            return
        except Exception as e:
            print(f"[SendMessage] ⚠️ Clipboard paste failed, typing instead: {e}")
    pyautogui.write(text, interval=0.03)


def _type_text_visible(text: str, interval: float = 0.035) -> None:
    """Type user-visible message text instead of pasting it from the clipboard."""
    _require_pyautogui()
    for ch in str(text or ""):
        if ch == "\n":
            pyautogui.hotkey("shift", "enter")
            time.sleep(interval * 2)
            continue
        try:
            pyautogui.write(ch, interval=interval)
        except Exception:
            # Last-resort fallback for characters PyAutoGUI cannot synthesize.
            _paste_text(ch)
        time.sleep(interval)


def _osascript_quote(value: str) -> str:
    return json.dumps(str(value or ""))


def _run_osascript(script: str, *, javascript: bool = False, timeout: float = 6.0) -> subprocess.CompletedProcess:
    cmd = ["osascript"]
    if javascript:
        cmd.extend(["-l", "JavaScript"])
    cmd.extend(["-e", script])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _contacts_jxa(query: str = "", *, limit: int = 0, timeout: float = 5.0) -> str:
    script = f"""
ObjC.import('stdlib');
const Contacts = Application('Contacts');
const query = {json.dumps(str(query or "").casefold())};
const limit = {int(limit or 0)};
function val(fn) {{
  try {{
    const value = fn();
    if (value === undefined || value === null) return '';
    return String(value);
  }} catch (e) {{
    return '';
  }}
}}
function firstValue(items) {{
  try {{
    const list = items();
    if (!list || list.length === 0) return '';
    return val(() => list[0].value());
  }} catch (e) {{
    return '';
  }}
}}
const rows = [];
const people = Contacts.people();
for (let i = 0; i < people.length; i++) {{
  const p = people[i];
  const name = val(() => p.name()).trim();
  if (!name) continue;
  const first = val(() => p.firstName()).trim();
  const last = val(() => p.lastName()).trim();
  const nick = val(() => p.nickname()).trim();
  const org = val(() => p.organization()).trim();
  const aliases = [name, first, last, nick, org].filter(Boolean);
  const haystack = aliases.join(' ').toLocaleLowerCase();
  if (query && !haystack.includes(query)) continue;
  const handle = firstValue(() => p.phones()) || firstValue(() => p.emails());
  if (!handle) continue;
  rows.push([name, handle, aliases.join('|')].join('\\t'));
  if (limit > 0 && rows.length >= limit) break;
}}
rows.join('\\n');
"""
    result = _run_osascript(script, javascript=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout or ""


def _resolve_contacts_handle(receiver: str) -> str:
    global _contacts_scan_failed_until
    receiver = str(receiver or "").strip()
    if not receiver:
        return ""
    if "@" in receiver or re.search(r"\d", receiver):
        return receiver
    if _get_os() != "mac":
        return receiver

    try:
        matches = _parse_contact_lines(_contacts_jxa(receiver, limit=1, timeout=3.0))
        if matches:
            return str(matches[0].get("handle", "") or receiver)
    except Exception as e:
        print(f"[SendMessage] ⚠️ Contact lookup failed: {e}")
        _contacts_scan_failed_until = time.time() + 60.0
    return receiver


def _direct_contact_matches(receiver: str) -> list[dict]:
    global _contacts_scan_failed_until
    receiver = str(receiver or "").strip()
    if not receiver or _get_os() != "mac":
        return []
    if time.time() < _contacts_scan_failed_until:
        return []
    try:
        return _parse_contact_lines(_contacts_jxa(receiver, limit=8, timeout=3.0))
    except Exception as e:
        print(f"[SendMessage] ⚠️ Direct contact lookup failed: {e}")
        _contacts_scan_failed_until = time.time() + 60.0
        return []


def _parse_contact_lines(text: str) -> list[dict]:
    candidates = []
    seen = set()
    for line in str(text or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name, handle = parts[0].strip(), parts[1].strip()
        raw_aliases = parts[2] if len(parts) > 2 else ""
        key = (name.lower(), handle)
        if not name or not handle or key in seen:
            continue
        seen.add(key)
        aliases = [part.strip() for part in raw_aliases.split("|") if part.strip()]
        aliases.extend(name.split())
        candidates.append({"name": name, "handle": handle, "aliases": aliases})
    return candidates


def _load_contacts_candidates() -> list[dict]:
    global _contacts_cache, _contacts_scan_failed_until
    if _get_os() != "mac":
        return []
    now = time.time()
    cached_at, cached_contacts = _contacts_cache
    if cached_contacts and now - cached_at <= CONTACTS_CACHE_TTL_SECONDS:
        return list(cached_contacts)
    if now < _contacts_scan_failed_until:
        return []
    try:
        raw_contacts = _contacts_jxa("", limit=0, timeout=5.0)
    except Exception as e:
        print(f"[SendMessage] ⚠️ Contacts scan failed: {e}")
        _contacts_scan_failed_until = time.time() + 60.0
        return []
    candidates = _parse_contact_lines(raw_contacts)
    if candidates:
        _contacts_cache = (time.time(), list(candidates))
    return candidates


def _resolve_imessage_recipient(receiver: str, message: str) -> tuple[str | None, str | None]:
    receiver = str(receiver or "").strip()
    if not receiver:
        return None, "Please specify an iMessage recipient."
    if "@" in receiver or re.search(r"\d", receiver):
        return receiver, None

    direct_matches = _direct_contact_matches(receiver)
    if direct_matches:
        matches, ambiguous = _best_name_matches(receiver, direct_matches)
        if matches and not ambiguous:
            if not _has_literal_recipient_match(receiver, matches[0]):
                return None, _recipient_confirmation_result("iMessage", receiver, message, matches[0])
            return str(matches[0].get("handle", "") or receiver), None
        if matches and ambiguous:
            return None, _ambiguous_result("iMessage", receiver, message, matches)

    contacts = _load_contacts_candidates()
    if not contacts:
        return None, (
            "I could not scan Contacts. Grant Terminal or VS Code access to Contacts and Automation "
            "in macOS System Settings, or provide the phone number/email directly."
        )

    matches, ambiguous = _best_name_matches(receiver, contacts)
    if not matches:
        sample = ", ".join(c["name"] for c in contacts[:8])
        return None, f"{NO_MATCH_PREFIX}No iMessage contact sounded like '{receiver}'. Recent contact examples: {sample}"
    if ambiguous:
        return None, _ambiguous_result("iMessage", receiver, message, matches)
    if not _has_literal_recipient_match(receiver, matches[0]):
        return None, _recipient_confirmation_result("iMessage", receiver, message, matches[0])
    return str(matches[0].get("handle", "") or receiver), None


def _send_imessage(receiver: str, message: str) -> str:
    if _get_os() != "mac":
        return "iMessage sending is only available on macOS."
    if not receiver:
        return "Please specify an iMessage recipient."

    handle, error = _resolve_imessage_recipient(receiver, message)
    if error:
        return error
    if not handle:
        return f"Could not resolve iMessage recipient '{receiver}'."
    duplicate = _check_duplicate_send("iMessage", handle, message)
    if duplicate:
        return duplicate
    escaped_handle = _osascript_quote(handle)
    escaped_message = _osascript_quote(message)
    script = f'''
set targetHandle to {escaped_handle}
set messageText to {escaped_message}
tell application "Messages"
    activate
    set sentOK to false
    try
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy targetHandle of targetService
        send messageText to targetBuddy
        set sentOK to true
    end try
    if sentOK is false then
        try
            set targetService to 1st service whose service type = SMS
            set targetBuddy to buddy targetHandle of targetService
            send messageText to targetBuddy
            set sentOK to true
        end try
    end if
    if sentOK is false then error "Could not resolve recipient in Messages."
end tell
'''
    try:
        result = _run_osascript(script, timeout=8)
    except Exception as e:
        return f"Could not send iMessage: {e}"
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        return f"Could not send iMessage to {receiver}: {err or 'Messages rejected the recipient.'}"
    _record_successful_send("iMessage", handle, message)
    return f"Message sent to {receiver} via iMessage."


def _focus_browser_message_composer(url_markers: tuple[str, ...]) -> str:
    _set_browser_focus_error("")
    if _get_os() != "mac":
        return ""

    markers_js = json.dumps([m.lower() for m in url_markers])
    dom_js = f"""
(() => {{
  const markers = {markers_js};
  const url = String(location.href || '').toLowerCase();
  if (!markers.some(marker => url.includes(marker))) return JSON.stringify({{ok:false, reason:'wrong_url', url}});
  const visible = (el) => {{
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 20 && r.height > 10 && s.display !== 'none' && s.visibility !== 'hidden';
  }};
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
  const composer = candidates.filter(el => {{
    const label = labelOf(el);
    const r = el.getBoundingClientRect();
    return label.includes('message') || label.includes('reply') || label.includes('chat') || r.bottom > innerHeight * 0.55;
  }}).sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom)[0] || null;
  if (!composer) return JSON.stringify({{ok:false, reason:'composer_not_found', url}});
  composer.focus();
  return JSON.stringify({{ok:true, url, label: labelOf(composer).slice(0, 80)}});
}})()
"""
    script = f"""
function chromeLike(name) {{
  try {{
    const app = Application(name);
    if (!app.running()) return '';
    const windows = app.windows();
    for (let i = 0; i < windows.length; i++) {{
      const tabs = windows[i].tabs ? windows[i].tabs() : [];
      for (let j = 0; j < tabs.length; j++) {{
        const tab = tabs[j];
        const url = String(tab.url() || '').toLowerCase();
        if ({markers_js}.some(marker => url.includes(marker))) {{
          windows[i].activeTabIndex = j + 1;
          app.activate();
          const raw = tab.execute({{javascript: {json.dumps(dom_js)}}});
          return JSON.stringify({{browser:name, raw}});
        }}
      }}
    }}
  }} catch (e) {{
    return JSON.stringify({{browser:name, error:String(e)}});
  }}
  return '';
}}
function safari() {{
  try {{
    const app = Application('Safari');
    if (!app.running()) return '';
    const windows = app.windows();
    for (let i = 0; i < windows.length; i++) {{
      const tabs = windows[i].tabs();
      for (let j = 0; j < tabs.length; j++) {{
        const tab = tabs[j];
        const url = String(tab.url() || '').toLowerCase();
        if ({markers_js}.some(marker => url.includes(marker))) {{
          windows[i].currentTab = tab;
          app.activate();
          const raw = app.doJavaScript({json.dumps(dom_js)}, {{in: tab}});
          return JSON.stringify({{browser:'Safari', raw}});
        }}
      }}
    }}
  }} catch (e) {{
    return JSON.stringify({{browser:'Safari', error:String(e)}});
  }}
  return '';
}}
(() => {{
  const browsers = ['Google Chrome', 'Brave Browser', 'Microsoft Edge', 'Arc'];
  for (let i = 0; i < browsers.length; i++) {{
    const result = chromeLike(browsers[i]);
    if (result) return result;
  }}
  return safari() || '';
}})();
"""
    try:
        result = _run_osascript(script, javascript=True, timeout=5)
    except Exception as e:
        _set_browser_focus_error(str(e))
        print(f"[SendMessage] ⚠️ Browser composer focus failed: {e}")
        return ""
    if result.returncode != 0:
        err = (result.stderr or result.stdout).strip()
        _set_browser_focus_error(err)
        print(f"[SendMessage] ⚠️ Browser composer focus error: {err}")
        return ""
    text = result.stdout.strip()
    try:
        outer = json.loads(text or "{}")
        if isinstance(outer, dict) and outer.get("error"):
            _set_browser_focus_error(str(outer.get("error", "")))
        raw = outer.get("raw", "") if isinstance(outer, dict) else ""
        inner = json.loads(raw or "{}") if raw else outer
        if isinstance(inner, dict) and inner.get("ok"):
            return text
        if isinstance(inner, dict) and inner.get("error"):
            _set_browser_focus_error(str(inner.get("error", "")))
        elif isinstance(inner, dict) and inner.get("reason"):
            _set_browser_focus_error(str(inner.get("reason", "")))
        print(f"[SendMessage] ⚠️ Browser composer not focused: {inner}")
        return ""
    except Exception as e:
        _set_browser_focus_error(f"{e}: {text[:200]}")
        print(f"[SendMessage] ⚠️ Browser composer focus parse failed: {e}: {text[:200]}")
        return ""


def _send_open_browser_chat(platform_name: str, message: str, url_markers: tuple[str, ...]) -> str:
    result = _send_browser_message_via_js(platform_name, message, url_markers)
    if result:
        return result
    focus_error = _browser_focus_error()
    if focus_error:
        if platform_name.lower() == "instagram":
            return focus_error
        return f"Could not send in the open {platform_name} message composer: {focus_error}"
    return f"Could not find an open {platform_name} message composer. Open the desired chat in your browser and try again."


def _fill_open_browser_chat(platform_name: str, message: str, url_markers: tuple[str, ...]) -> str:
    result = _fill_browser_message_via_js(platform_name, message, url_markers)
    if result:
        return result
    focus_error = _browser_focus_error()
    if focus_error:
        return f"Could not type in the open {platform_name} message composer: {focus_error}"
    return f"Could not find an open {platform_name} message composer. Open the desired chat in your browser and try again."


def _send_open_browser_draft(platform_name: str, url_markers: tuple[str, ...]) -> str:
    result = _send_browser_draft_via_js(platform_name, url_markers)
    if result:
        return result
    focus_error = _browser_focus_error()
    if focus_error:
        return f"Could not send the open {platform_name} draft: {focus_error}"
    return f"Could not find a sendable {platform_name} draft. Leave the draft visible and try again."


def _browser_jxa_for_matching_tab(url_markers: tuple[str, ...], dom_js: str) -> str:
    markers_js = json.dumps([m.lower() for m in url_markers])
    return f"""
function chromeLike(name) {{
  try {{
    const app = Application(name);
    if (!app.running()) return '';
    const windows = app.windows();
    for (let i = 0; i < windows.length; i++) {{
      const tabs = windows[i].tabs ? windows[i].tabs() : [];
      for (let j = 0; j < tabs.length; j++) {{
        const tab = tabs[j];
        const url = String(tab.url() || '').toLowerCase();
        if ({markers_js}.some(marker => url.includes(marker))) {{
          windows[i].activeTabIndex = j + 1;
          app.activate();
          const raw = tab.execute({{javascript: {json.dumps(dom_js)}}});
          return raw || '';
        }}
      }}
    }}
  }} catch (e) {{
    return JSON.stringify({{ok:false,error:String(e),browser:name}});
  }}
  return '';
}}
function safari() {{
  try {{
    const app = Application('Safari');
    if (!app.running()) return '';
    const windows = app.windows();
    for (let i = 0; i < windows.length; i++) {{
      const tabs = windows[i].tabs();
      for (let j = 0; j < tabs.length; j++) {{
        const tab = tabs[j];
        const url = String(tab.url() || '').toLowerCase();
        if ({markers_js}.some(marker => url.includes(marker))) {{
          windows[i].currentTab = tab;
          app.activate();
          const raw = app.doJavaScript({json.dumps(dom_js)}, {{in: tab}});
          return raw || '';
        }}
      }}
    }}
  }} catch (e) {{
    return JSON.stringify({{ok:false,error:String(e),browser:'Safari'}});
  }}
  return '';
}}
(() => {{
  const browsers = ['Google Chrome', 'Brave Browser', 'Microsoft Edge', 'Arc'];
  for (let i = 0; i < browsers.length; i++) {{
    const result = chromeLike(browsers[i]);
    if (result) return result;
  }}
  return safari() || JSON.stringify({{ok:false,error:'No Instagram DM tab found'}});
}})();
"""


def _send_browser_message_via_js(platform_name: str, message: str, url_markers: tuple[str, ...]) -> str:
    _set_browser_focus_error("")
    dom_js = f"""
(() => {{
  const text = {json.dumps(str(message or ""))};
  const visible = (el) => {{
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 20 && r.height > 10 && s.display !== 'none' && s.visibility !== 'hidden';
  }};
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
  const composer = candidates.filter(el => {{
    const label = labelOf(el);
    const r = el.getBoundingClientRect();
    return label.includes('message') || label.includes('reply') || label.includes('chat') || r.bottom > innerHeight * 0.55;
  }}).sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom)[0] || null;
  if (!composer) return JSON.stringify({{ok:false, reason:'composer_not_found', url:location.href}});

  const inputEvent = () => new InputEvent('input', {{
    bubbles: true,
    cancelable: true,
    inputType: 'insertText',
    data: text
  }});
  composer.focus();
  if (composer.tagName && /^(textarea|input)$/i.test(composer.tagName)) {{
    const proto = composer.tagName.toLowerCase() === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (setter) setter.call(composer, text);
    else composer.value = text;
    composer.dispatchEvent(inputEvent());
    composer.dispatchEvent(new Event('change', {{bubbles:true}}));
  }} else {{
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(composer);
    sel.removeAllRanges();
    sel.addRange(range);
    document.execCommand('insertText', false, text);
    composer.dispatchEvent(inputEvent());
  }}

  const buttonLabel = (el) => [
    el.getAttribute && el.getAttribute('aria-label'),
    el.getAttribute && el.getAttribute('title'),
    el.innerText,
    el.textContent
  ].filter(Boolean).join(' ').trim().toLowerCase();
  const sendButtons = Array.from(document.querySelectorAll('button, div[role="button"], [aria-label]'))
    .filter(visible)
    .filter(el => /^(send|send message)$/i.test(buttonLabel(el)) || buttonLabel(el).includes('send'));
  const sendButton = sendButtons[sendButtons.length - 1] || null;
  if (sendButton) {{
    sendButton.click();
    return JSON.stringify({{ok:true, method:'button', url:location.href}});
  }}

  for (const type of ['keydown', 'keypress', 'keyup']) {{
    composer.dispatchEvent(new KeyboardEvent(type, {{
      bubbles: true,
      cancelable: true,
      key: 'Enter',
      code: 'Enter',
      keyCode: 13,
      which: 13
    }}));
  }}
  return JSON.stringify({{ok:true, method:'enter', url:location.href}});
}})()
"""
    try:
        result = _run_osascript(
            _browser_jxa_for_matching_tab(url_markers, dom_js),
            javascript=True,
            timeout=6,
        )
    except Exception as e:
        _set_browser_focus_error(str(e))
        print(f"[SendMessage] ⚠️ Browser JS send failed: {e}")
        return ""
    if result.returncode != 0:
        err = (result.stderr or result.stdout).strip()
        _set_browser_focus_error(err)
        print(f"[SendMessage] ⚠️ Browser JS send error: {err}")
        return ""
    try:
        data = json.loads(result.stdout.strip() or "{}")
    except Exception as e:
        _set_browser_focus_error(f"{e}: {result.stdout[:200]}")
        print(f"[SendMessage] ⚠️ Browser JS send parse failed: {e}: {result.stdout[:200]}")
        return ""
    if isinstance(data, dict) and data.get("ok"):
        return f"Message sent in the open {platform_name} chat."
    if isinstance(data, dict):
        _set_browser_focus_error(str(data.get("error") or data.get("reason") or ""))
    return ""


def _fill_browser_message_via_js(platform_name: str, message: str, url_markers: tuple[str, ...]) -> str:
    """Type the message into the verified open chat composer WITHOUT sending.

    Mirrors the composer detection in ``_send_browser_message_via_js`` but
    stops before clicking any Send button or firing an Enter keypress.
    Returns a friendly status string on success and an empty string on
    failure (with ``_browser_focus_error`` populated).
    """
    _set_browser_focus_error("")
    dom_js = f"""
(() => {{
  const text = {json.dumps(str(message or ""))};
  const visible = (el) => {{
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 20 && r.height > 10 && s.display !== 'none' && s.visibility !== 'hidden';
  }};
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
  const composer = candidates.filter(el => {{
    const label = labelOf(el);
    const r = el.getBoundingClientRect();
    return label.includes('message') || label.includes('reply') || label.includes('chat') || r.bottom > innerHeight * 0.55;
  }}).sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom)[0] || null;
  if (!composer) return JSON.stringify({{ok:false, reason:'composer_not_found', url:location.href}});

  const inputEvent = () => new InputEvent('input', {{
    bubbles: true,
    cancelable: true,
    inputType: 'insertText',
    data: text
  }});
  composer.focus();
  if (composer.tagName && /^(textarea|input)$/i.test(composer.tagName)) {{
    const proto = composer.tagName.toLowerCase() === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (setter) setter.call(composer, text);
    else composer.value = text;
    composer.dispatchEvent(inputEvent());
    composer.dispatchEvent(new Event('change', {{bubbles:true}}));
  }} else {{
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(composer);
    sel.removeAllRanges();
    sel.addRange(range);
    document.execCommand('insertText', false, text);
    composer.dispatchEvent(inputEvent());
  }}
  return JSON.stringify({{ok:true, url:location.href, draftLen: text.length}});
}})()
"""
    try:
        result = _run_osascript(
            _browser_jxa_for_matching_tab(url_markers, dom_js),
            javascript=True,
            timeout=6,
        )
    except Exception as e:
        _set_browser_focus_error(str(e))
        print(f"[SendMessage] ⚠️ Browser JS fill failed: {e}")
        return ""
    if result.returncode != 0:
        err = (result.stderr or result.stdout).strip()
        _set_browser_focus_error(err)
        print(f"[SendMessage] ⚠️ Browser JS fill error: {err}")
        return ""
    try:
        data = json.loads(result.stdout.strip() or "{}")
    except Exception as e:
        _set_browser_focus_error(f"{e}: {result.stdout[:200]}")
        print(f"[SendMessage] ⚠️ Browser JS fill parse failed: {e}: {result.stdout[:200]}")
        return ""
    if isinstance(data, dict) and data.get("ok"):
        return f"Draft typed in the open {platform_name} chat. Awaiting your approval to send."
    if isinstance(data, dict):
        _set_browser_focus_error(str(data.get("error") or data.get("reason") or ""))
    return ""


def _send_browser_draft_via_js(platform_name: str, url_markers: tuple[str, ...]) -> str:
    """Press Send for a draft that is already typed in the verified open chat.

    Does not re-type anything — it just looks for a visible Send button or
    fires an Enter keypress on the focused composer. Returns a friendly
    status string on success and an empty string on failure (with
    ``_browser_focus_error`` populated).
    """
    _set_browser_focus_error("")
    dom_js = """
(() => {
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
  const composer = Array.from(document.querySelectorAll(
    'div[contenteditable="true"][role="textbox"], div[contenteditable="true"], textarea, input[type="text"]'
  )).filter(visible).sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom)[0] || null;
  if (!composer) return JSON.stringify({ok:false, reason:'composer_not_found', url:location.href});
  composer.focus();

  const buttonLabel = (el) => [
    el.getAttribute && el.getAttribute('aria-label'),
    el.getAttribute && el.getAttribute('title'),
    el.innerText,
    el.textContent
  ].filter(Boolean).join(' ').trim().toLowerCase();
  const sendButtons = Array.from(document.querySelectorAll('button, div[role="button"], [aria-label]'))
    .filter(visible)
    .filter(el => /^(send|send message)$/i.test(buttonLabel(el)) || buttonLabel(el).includes('send'));
  const sendButton = sendButtons[sendButtons.length - 1] || null;
  if (sendButton) {
    sendButton.click();
    return JSON.stringify({ok:true, method:'button', url:location.href});
  }

  for (const type of ['keydown', 'keypress', 'keyup']) {
    composer.dispatchEvent(new KeyboardEvent(type, {
      bubbles: true,
      cancelable: true,
      key: 'Enter',
      code: 'Enter',
      keyCode: 13,
      which: 13
    }));
  }
  return JSON.stringify({ok:true, method:'enter', url:location.href});
})()
"""
    try:
        result = _run_osascript(
            _browser_jxa_for_matching_tab(url_markers, dom_js),
            javascript=True,
            timeout=5,
        )
    except Exception as e:
        _set_browser_focus_error(str(e))
        print(f"[SendMessage] ⚠️ Browser JS draft send failed: {e}")
        return ""
    if result.returncode != 0:
        err = (result.stderr or result.stdout).strip()
        _set_browser_focus_error(err)
        print(f"[SendMessage] ⚠️ Browser JS draft send error: {err}")
        return ""
    try:
        data = json.loads(result.stdout.strip() or "{}")
    except Exception as e:
        _set_browser_focus_error(f"{e}: {result.stdout[:200]}")
        print(f"[SendMessage] ⚠️ Browser JS draft send parse failed: {e}: {result.stdout[:200]}")
        return ""
    if isinstance(data, dict) and data.get("ok"):
        return f"Message sent in the open {platform_name} chat."
    if isinstance(data, dict):
        _set_browser_focus_error(str(data.get("error") or data.get("reason") or ""))
    return ""


def _clear_browser_draft_via_js(url_markers: tuple[str, ...]) -> bool:
    """Best-effort clear of a typed-but-unsent draft in the active composer."""
    _set_browser_focus_error("")
    dom_js = """
(() => {
  const visible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 20 && r.height > 10 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const composer = Array.from(document.querySelectorAll(
    'div[contenteditable="true"][role="textbox"], div[contenteditable="true"], textarea, input[type="text"]'
  )).filter(visible).sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom)[0] || null;
  if (!composer) return JSON.stringify({ok:false, reason:'composer_not_found'});
  composer.focus();
  if (composer.tagName && /^(textarea|input)$/i.test(composer.tagName)) {
    const proto = composer.tagName.toLowerCase() === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (setter) setter.call(composer, '');
    else composer.value = '';
    composer.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'deleteContentBackward'}));
    composer.dispatchEvent(new Event('change', {bubbles:true}));
  } else {
    composer.innerHTML = '';
    composer.textContent = '';
    composer.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'deleteContentBackward'}));
  }
  return JSON.stringify({ok:true});
})()
"""
    try:
        result = _run_osascript(
            _browser_jxa_for_matching_tab(url_markers, dom_js),
            javascript=True,
            timeout=4,
        )
    except Exception as e:
        _set_browser_focus_error(str(e))
        print(f"[SendMessage] ⚠️ Browser JS draft clear failed: {e}")
        return False
    if result.returncode != 0:
        _set_browser_focus_error((result.stderr or result.stdout or "").strip())
        return False
    try:
        data = json.loads(result.stdout.strip() or "{}")
    except Exception:
        return False
    return bool(isinstance(data, dict) and data.get("ok"))


def send_open_browser_draft(platform_name: str, url_markers: tuple[str, ...]) -> str:
    """Public helper used by the approval flow to press Send on a typed draft.

    Thin wrapper around ``_send_open_browser_draft`` so ``main.py`` does not
    need to import a private helper. Returns a friendly status string.
    """
    if str(platform_name or "").lower() == "instagram":
        return _controlled_instagram_send_draft()
    return _send_open_browser_draft(platform_name, url_markers)


def clear_open_browser_draft(url_markers: tuple[str, ...]) -> bool:
    """Public helper used by the approval flow to discard a typed draft."""
    if any("instagram.com/direct" in str(marker or "").lower() for marker in url_markers):
        return _controlled_instagram_clear_draft()
    return _clear_browser_draft_via_js(url_markers)


def prepare_instagram_draft(receiver: str, message: str) -> str:
    """Find an Instagram DM, type the draft, and wait for approval.

    This intentionally does not press Send. ``main.py`` uses it for the
    reply-approval flow so approval can send the already visible draft instead
    of retyping into whatever field happens to be focused later.
    """
    return _send_instagram(receiver, message)


def _instagram_recent_chats() -> list[dict]:
    dom_js = r"""
(() => {
  const clean = (text) => String(text || '').replace(/\s+/g, ' ').trim();
  const ignoredLine = (line) => /^(active|online|seen|sent|you sent|replied|typing|now|today|yesterday|\d+[smhdw]\b|.* ago$)$/i.test(line);
  const rows = [];
  const seen = new Set();
  const selectors = [
    'a[href*="/direct/t/"]',
    'a[href*="/direct/"]'
  ];
  for (const el of Array.from(document.querySelectorAll(selectors.join(',')))) {
    const rect = el.getBoundingClientRect && el.getBoundingClientRect();
    if (!rect || rect.width < 40 || rect.height < 24) continue;
    if (rect.left > window.innerWidth * 0.55) continue;
    const raw = String(el.innerText || el.textContent || '');
    const lines = raw.split(/\n+/).map(clean).filter(Boolean);
    if (!lines.length) continue;
    let name = lines.find(line => !ignoredLine(line));
    if (!name) continue;
    name = name.replace(/^@/, '').trim();
    if (!name || /^(messages|search|notes|requests|home|reels|explore)$/i.test(name)) continue;
    const href = el.href || '';
    const key = name.toLowerCase() + '|' + href;
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push({name, handle: href || name, aliases: [name], text: lines.slice(0, 4).join(' | ').slice(0, 160)});
    if (rows.length >= 30) break;
  }
  return JSON.stringify({ok:true, rows});
})()
"""
    try:
        result = _run_osascript(
            _browser_jxa_for_matching_tab(("instagram.com/direct",), dom_js),
            javascript=True,
            timeout=6,
        )
    except Exception as e:
        print(f"[SendMessage] ⚠️ Instagram chat scan failed: {e}")
        return []
    if result.returncode != 0:
        print(f"[SendMessage] ⚠️ Instagram chat scan error: {(result.stderr or result.stdout).strip()}")
        return []
    try:
        data = json.loads(result.stdout.strip() or "{}")
    except Exception as e:
        print(f"[SendMessage] ⚠️ Instagram chat scan parse failed: {e}: {result.stdout[:200]}")
        return []
    if isinstance(data, dict) and data.get("error"):
        _set_browser_focus_error(str(data.get("error", "")))
        print(f"[SendMessage] ⚠️ Instagram chat scan browser error: {data.get('error')}")
        return []
    rows = data.get("rows", []) if isinstance(data, dict) else []
    return [row for row in rows if isinstance(row, dict) and row.get("name")]


def _open_instagram_chat(chat_name: str) -> bool:
    dom_js = f"""
(() => {{
  const target = {json.dumps(_name_norm(chat_name))};
  const norm = (s) => String(s || '').normalize('NFKD')
    .replace(/[\\u0300-\\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '');
  const clean = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
  const candidates = Array.from(document.querySelectorAll(
    'a[href*="/direct/t/"], a[href*="/direct/"]'
  ));
  for (const el of candidates) {{
    const rect = el.getBoundingClientRect && el.getBoundingClientRect();
    if (!rect || rect.width < 40 || rect.height < 24) continue;
    if (rect.left > window.innerWidth * 0.55) continue;
    const text = clean(el.innerText || el.textContent || '');
    if (!text) continue;
    const first = clean(text.split(/(?:\\n| · |•)/)[0] || text);
    if (norm(first) === target || norm(first).includes(target) || target.includes(norm(first))) {{
      el.scrollIntoView({{block:'center'}});
      el.click();
      return JSON.stringify({{ok:true, clicked:first}});
    }}
  }}
  return JSON.stringify({{ok:false}});
}})()
"""
    try:
        result = _run_osascript(
            _browser_jxa_for_matching_tab(("instagram.com/direct",), dom_js),
            javascript=True,
            timeout=6,
        )
    except Exception as e:
        print(f"[SendMessage] ⚠️ Instagram chat click failed: {e}")
        return False
    if result.returncode != 0:
        print(f"[SendMessage] ⚠️ Instagram chat click error: {(result.stderr or result.stdout).strip()}")
        return False
    try:
        data = json.loads(result.stdout.strip() or "{}")
        if isinstance(data, dict) and data.get("error"):
            _set_browser_focus_error(str(data.get("error", "")))
            return False
        return bool(data.get("ok"))
    except Exception:
        return "ok" in (result.stdout or "").lower()


def _resolve_instagram_chat(receiver: str, message: str) -> tuple[str | None, str | None]:
    """Resolve ``receiver`` to a visible Instagram chat, scrolling the DM list if needed."""
    return _find_instagram_chat_by_name(receiver, message=message)


_INSTAGRAM_DM_SCROLL_MAX_STEPS = 8
_INSTAGRAM_DM_SCROLL_STEP_PX = 600
_instagram_dm_last_scroll_signature: tuple = ()


def _reset_instagram_dm_scroll() -> bool:
    """Scroll the Instagram DM sidebar back to the top."""
    global _instagram_dm_last_scroll_signature
    dom_js = """
(() => {
  const findScrollable = (root) => {
    let el = root;
    while (el && el !== document.body) {
      const s = getComputedStyle(el);
      const sh = el.scrollHeight;
      if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && sh > el.clientHeight + 8) return el;
      el = el.parentElement;
    }
    return document.scrollingElement || document.documentElement;
  };
  const root = document.querySelector('a[href*="/direct/t/"]')?.closest('div') || document.body;
  const scrollable = findScrollable(root);
  if (!scrollable) return JSON.stringify({ok:false, reason:'no_scrollable'});
  scrollable.scrollTop = 0;
  return JSON.stringify({ok:true, scrollTop: scrollable.scrollTop, scrollHeight: scrollable.scrollHeight});
})()
"""
    try:
        result = _run_osascript(
            _browser_jxa_for_matching_tab(("instagram.com/direct",), dom_js),
            javascript=True,
            timeout=4,
        )
    except Exception as e:
        print(f"[SendMessage] ⚠️ Instagram DM scroll reset failed: {e}")
        return False
    if result.returncode != 0:
        print(f"[SendMessage] ⚠️ Instagram DM scroll reset error: {(result.stderr or result.stdout).strip()}")
        return False
    _instagram_dm_last_scroll_signature = ()
    try:
        data = json.loads(result.stdout.strip() or "{}")
        if isinstance(data, dict) and data.get("error"):
            _set_browser_focus_error(str(data.get("error", "")))
        return bool(isinstance(data, dict) and data.get("ok"))
    except Exception:
        return False


def _scroll_instagram_dm_list(step_px: int = _INSTAGRAM_DM_SCROLL_STEP_PX) -> dict:
    """Scroll the DM sidebar one step and report whether the end was reached."""
    dom_js = f"""
(() => {{
  const findScrollable = (root) => {{
    let el = root;
    while (el && el !== document.body) {{
      const s = getComputedStyle(el);
      const sh = el.scrollHeight;
      if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && sh > el.clientHeight + 8) return el;
      el = el.parentElement;
    }}
    return document.scrollingElement || document.documentElement;
  }};
  const root = document.querySelector('a[href*="/direct/t/"]')?.closest('div') || document.body;
  const scrollable = findScrollable(root);
  if (!scrollable) return JSON.stringify({{ok:false, reason:'no_scrollable'}});
  const before = scrollable.scrollTop;
  scrollable.scrollTop = before + {int(step_px)};
  const reachedEnd = (scrollable.scrollTop + scrollable.clientHeight) >= (scrollable.scrollHeight - 4);
  return JSON.stringify({{
    ok: true,
    scrollTop: scrollable.scrollTop,
    scrollHeight: scrollable.scrollHeight,
    clientHeight: scrollable.clientHeight,
    reachedEnd,
    moved: scrollable.scrollTop !== before
  }});
}})()
"""
    try:
        result = _run_osascript(
            _browser_jxa_for_matching_tab(("instagram.com/direct",), dom_js),
            javascript=True,
            timeout=4,
        )
    except Exception as e:
        print(f"[SendMessage] ⚠️ Instagram DM scroll failed: {e}")
        return {"ok": False, "reachedEnd": True}
    if result.returncode != 0:
        print(f"[SendMessage] ⚠️ Instagram DM scroll error: {(result.stderr or result.stdout).strip()}")
        return {"ok": False, "reachedEnd": True}
    try:
        data = json.loads(result.stdout.strip() or "{}")
        if isinstance(data, dict) and data.get("error"):
            _set_browser_focus_error(str(data.get("error", "")))
        return data if isinstance(data, dict) else {"ok": False, "reachedEnd": True}
    except Exception:
        return {"ok": False, "reachedEnd": True}


def _find_instagram_chat_by_name(
    receiver: str,
    *,
    message: str = "",
) -> tuple[str | None, str | None]:
    """Find an Instagram DM by recipient name, scrolling the list if needed.

    Matching uses only the chat row's primary name (and any aliases). It
    never consults online status, timestamps, or the recent message
    preview that Instagram puts below each row.
    """
    receiver = str(receiver or "").strip()
    if not receiver:
        return "", None

    # Always reset to top so repeated calls during a session behave predictably.
    _reset_instagram_dm_scroll()
    rows: list[dict] = []
    last_error = ""
    for step in range(_INSTAGRAM_DM_SCROLL_MAX_STEPS + 1):
        rows = _instagram_recent_chats()
        if not rows:
            focus_error = _browser_focus_error()
            if focus_error:
                return None, focus_error
            last_error = (
                "I could not read your Instagram DM list. Open Instagram Direct Messages in Chrome/Safari "
                "with the recent chats visible, then try again."
            )
            break

        # Strip rows so matching only considers the primary name and the URL handle.
        cleaned = []
        for row in rows:
            name = str(row.get("name", "") or "").strip()
            handle = str(row.get("handle", "") or "").strip()
            aliases = [str(a or "").strip() for a in row.get("aliases", []) if str(a or "").strip()]
            if handle and handle not in aliases:
                aliases.append(handle)
            cleaned.append({"name": name, "handle": handle, "aliases": aliases})

        matches, ambiguous = _best_name_matches(receiver, cleaned)
        if matches and not ambiguous:
            return str(matches[0].get("name", "") or receiver), None
        if matches and ambiguous:
            # If we haven't scrolled yet, fall through and try to scroll in
            # case a tighter match is further down. If we have scrolled,
            # the ambiguity is real — ask the user.
            if step >= _INSTAGRAM_DM_SCROLL_MAX_STEPS:
                return None, _ambiguous_result("Instagram", receiver, message, matches)
        if step >= _INSTAGRAM_DM_SCROLL_MAX_STEPS:
            break
        scroll = _scroll_instagram_dm_list()
        if not scroll.get("ok") or scroll.get("reachedEnd"):
            break
        time.sleep(0.25)

    if last_error:
        return None, last_error
    if not rows:
        return None, (
            "I could not read your Instagram DM list. Open Instagram Direct Messages in Chrome/Safari "
            "with the recent chats visible, then try again."
        )
    sample = ", ".join(row.get("name", "") for row in rows[:8])
    return None, (
        f"{NO_MATCH_PREFIX}No recent Instagram chat sounded like '{receiver}'. "
        f"Visible chats: {sample}"
    )


def _verify_instagram_active_chat(expected_name: str) -> bool:
    """Confirm the chat currently shown in the right pane belongs to ``expected_name``.

    Reads only the active chat header — never the composer label or sidebar
    text. Returns False on any uncertainty so the caller can refuse to type.
    """
    expected = _name_norm(expected_name)
    if not expected:
        return False
    dom_js = r"""
(() => {
  const norm = (s) => String(s || '').normalize('NFKD')
    .replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '');
  const clean = (text) => String(text || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 20 && r.height > 10 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  // Right pane is everything in the viewport whose left edge is past the sidebar.
  const sidebarRight = (document.querySelector('a[href*="/direct/t/"]')?.getBoundingClientRect()?.right) || 0;
  const headerCandidates = Array.from(document.querySelectorAll('header, [role="banner"], div'))
    .filter(visible)
    .filter(el => {
      const r = el.getBoundingClientRect();
      return sidebarRight && r.left > sidebarRight + 40 && r.height < 80 && r.width > 100;
    })
    .sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
  const headerTexts = headerCandidates.slice(0, 4).map(el => clean(el.innerText || el.textContent || ''));
  return JSON.stringify({ok:true, headers: headerTexts, url: location.href});
})()
"""
    try:
        result = _run_osascript(
            _browser_jxa_for_matching_tab(("instagram.com/direct",), dom_js),
            javascript=True,
            timeout=5,
        )
    except Exception as e:
        print(f"[SendMessage] ⚠️ Instagram chat verify failed: {e}")
        return False
    if result.returncode != 0:
        print(f"[SendMessage] ⚠️ Instagram chat verify error: {(result.stderr or result.stdout).strip()}")
        return False
    try:
        data = json.loads(result.stdout.strip() or "{}")
    except Exception as e:
        print(f"[SendMessage] ⚠️ Instagram chat verify parse failed: {e}: {result.stdout[:200]}")
        return False
    if not isinstance(data, dict) or not data.get("ok"):
        if isinstance(data, dict) and data.get("error"):
            _set_browser_focus_error(str(data.get("error", "")))
        return False
    for header in data.get("headers", []) or []:
        if expected in _name_norm(header):
            return True
    return False


def _screen_find(description: str, retries: int = 2, delay: float = 0.6) -> tuple[int, int] | None:
    api_key = _get_api_key()
    if not api_key:
        print("[SendMessage] ⚠️ No Gemini key for screen vision.")
        return None

    for attempt in range(max(1, retries)):
        try:
            from google import genai
            from google.genai import types as gtypes

            _require_pyautogui()
            w, h = pyautogui.size()
            img = pyautogui.screenshot()
            buf = io.BytesIO()
            img.save(buf, format="PNG")

            prompt = (
                f"You are controlling a {w}x{h} screen for JARVIS messaging. "
                f"Find this exact UI target: {description}. "
                "Prefer visible text fields, buttons, or list results in the active browser/app. "
                "Return ONLY the center coordinate as x,y. If not visible, return NOT_FOUND."
            )
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=[
                    gtypes.Part.from_bytes(data=buf.getvalue(), mime_type="image/png"),
                    prompt,
                ],
            )
            text = (response.text or "").strip()
            if "NOT_FOUND" not in text.upper():
                match = re.search(r"(\d+)\s*,\s*(\d+)", text)
                if match:
                    return int(match.group(1)), int(match.group(2))
        except Exception as e:
            print(f"[SendMessage] ⚠️ screen_find failed: {e}")
        time.sleep(delay * (attempt + 1))
    return None


def _vision_click(description: str, retries: int = 2, delay: float = 0.6) -> bool:
    coords = _screen_find(description, retries=retries, delay=delay)
    if not coords:
        return False
    pyautogui.click(coords[0], coords[1])
    time.sleep(0.5)
    return True


def _with_persona_footer(text: str, persona: str = "JARVIS") -> str:
    message = normalize_outgoing_message_text(text)
    persona_name = str(persona or "JARVIS").strip().upper()
    footer = PERSONA_TEXT_FOOTERS.get(persona_name, JARVIS_TEXT_FOOTER)
    if _PERSONA_FOOTER_RE.search(message):
        return _PERSONA_FOOTER_RE.sub(footer, message).strip()
    return f"{message}\n\n{footer}"


def _with_jarvis_footer(text: str) -> str:
    """Compatibility wrapper for integrations that do not pass a persona."""
    return _with_persona_footer(text, "JARVIS")


def _clear_and_paste(text: str) -> None:
    _require_pyautogui()
    os_name = _get_os()
    select_all = ("command", "a") if os_name == "mac" else ("ctrl", "a")
    pyautogui.hotkey(*select_all)
    time.sleep(0.1)
    pyautogui.press("delete")
    time.sleep(0.1)
    _paste_text(text)

def _open_app(app_name: str) -> bool:
    _require_pyautogui()
    os_name = _get_os()

    try:
        if os_name == "windows":
            pyautogui.press("win")
            time.sleep(0.5)
            _paste_text(app_name)
            time.sleep(0.6)
            pyautogui.press("enter")
            time.sleep(2.5)
            return True

        elif os_name == "mac":
            result = subprocess.run(
                ["open", "-a", app_name],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                result = subprocess.run(
                    ["open", "-a", f"{app_name}.app"],
                    capture_output=True, text=True, timeout=10,
                )
            time.sleep(2.5)
            return result.returncode == 0

        else:
            launched = False
            for launcher in [
                ["gtk-launch", app_name.lower()],
                [app_name.lower()],
            ]:
                try:
                    subprocess.Popen(
                        launcher,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    launched = True
                    break
                except FileNotFoundError:
                    continue
            time.sleep(2.5)
            return launched

    except Exception as e:
        print(f"[SendMessage] ⚠️ Could not open {app_name}: {e}")
        return False


def _open_browser_url(url: str) -> bool:
    import webbrowser
    try:
        webbrowser.open(url)
        time.sleep(4.0)
        return True
    except Exception as e:
        print(f"[SendMessage] ⚠️ Could not open browser: {e}")
        return False

def _search_in_app(query: str) -> None:
    _require_pyautogui()
    os_name = _get_os()
    search_hotkey = ("command", "f") if os_name == "mac" else ("ctrl", "f")

    pyautogui.hotkey(*search_hotkey)
    time.sleep(0.5)
    _clear_and_paste(query)
    time.sleep(1.0)

def _desktop_send(app_name: str, receiver: str, message: str) -> str:
    if not receiver:
        return f"Please specify a recipient for {app_name}, or open the chat first and use current/focused."
    if not _open_app(app_name):
        return f"Could not open {app_name}."

    time.sleep(1.0)
    _search_in_app(receiver)
    pyautogui.press("enter")
    time.sleep(0.8)

    typed = safe_type_then_enter(message, purpose="message", allow_pointer_fallback=True)
    if not typed.ok:
        return typed.message
    return f"Message sent to {receiver} via {app_name}."


def _send_current_app(receiver: str, message: str) -> str:
    typed = safe_type_then_enter(message, purpose="message", allow_pointer_fallback=False)
    if not typed.ok:
        return typed.message
    target = f" to {receiver}" if receiver else ""
    return f"Message sent{target} in the current app."

def _send_whatsapp(receiver: str, message: str) -> str:
    if not receiver:
        return _send_open_browser_chat("WhatsApp", message, ("web.whatsapp.com",))
    result = _send_open_browser_chat("WhatsApp", message, ("web.whatsapp.com",))
    if "Message sent" in result:
        return result
    return _desktop_send("WhatsApp", receiver, message)

def _send_telegram(receiver: str, message: str) -> str:
    if not receiver:
        return _send_open_browser_chat("Telegram", message, ("web.telegram.org",))
    result = _send_open_browser_chat("Telegram", message, ("web.telegram.org",))
    if "Message sent" in result:
        return result
    return _desktop_send("Telegram", receiver, message)

def _send_signal(receiver: str, message: str) -> str:
    return _desktop_send("Signal", receiver, message)


def _send_discord(receiver: str, message: str) -> str:
    if not receiver:
        return _send_open_browser_chat("Discord", message, ("discord.com/channels", "discord.com/app"))
    result = _send_open_browser_chat("Discord", message, ("discord.com/channels", "discord.com/app"))
    if "Message sent" in result:
        return result
    return _desktop_send("Discord", receiver, message)


def _send_instagram(receiver: str, message: str) -> str:
    duplicate_target = receiver or "current chat"
    duplicate = _check_duplicate_send("Instagram", duplicate_target, message)
    if duplicate:
        return duplicate

    return _controlled_instagram_prepare_draft(receiver, message)


def _send_messenger(receiver: str, message: str) -> str:
    if not receiver:
        return _send_open_browser_chat("Messenger", message, ("messenger.com",))
    result = _send_open_browser_chat("Messenger", message, ("messenger.com",))
    if "Message sent" in result:
        return result
    return (
        "Messenger browser sending is supported for the currently open chat. "
        "Open the desired Messenger chat in your browser, leave recipient blank, and try again."
    )

_PLATFORM_MAP = [
    ({"current", "active", "focused", "frontmost", "any", "generic"}, _send_current_app),
    ({"imessage", "i-message", "messages", "apple messages", "sms"}, _send_imessage),
    ({"whatsapp", "wp", "wapp"},              _send_whatsapp),
    ({"telegram", "tg"},                      _send_telegram),
    ({"instagram", "ig", "insta"},            _send_instagram),
    ({"signal"},                               _send_signal),
    ({"discord"},                              _send_discord),
    ({"messenger", "facebook", "fb"},         _send_messenger),
]


def _resolve_platform(platform_str: str):
    key = re.sub(r"\s+", " ", str(platform_str or "").lower()).strip()
    # Resolve canonical names and short aliases exactly. Substring matching
    # made aliases such as ``ig`` capture unrelated platforms like ``Signal``.
    for keywords, handler in _PLATFORM_MAP:
        if key in keywords:
            return handler
    for keywords, handler in _PLATFORM_MAP:
        if any(
            len(keyword) >= 4
            and re.search(
                rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])",
                key,
            )
            for keyword in keywords
        ):
            return handler
    return lambda r, m: _desktop_send(platform_str.strip().title(), r, m)


def send_message(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params       = parameters or {}
    action       = str(params.get("action", "send") or "send").lower().strip()
    receiver     = str(params.get("receiver", "") or "").strip()
    message_text = str(params.get("message_text", "") or "").strip()
    platform     = str(params.get("platform", "whatsapp") or "").strip()
    platform_key = platform.lower().strip()

    if action in {"approve", "confirm"}:
        return prepare_message_reply({"action": "approve"}, player=player)
    if action in {"cancel", "discard", "deny"}:
        return prepare_message_reply({"action": "cancel"}, player=player)
    no_recipient_keywords = {
        "current", "active", "focused", "frontmost", "any", "generic",
        "instagram", "ig", "insta",
        "whatsapp", "wp", "wapp",
        "telegram", "tg",
        "discord",
        "messenger", "facebook", "fb",
    }
    recipient_optional = any(keyword in platform_key for keyword in no_recipient_keywords)

    if not receiver and not recipient_optional:
        return "Please specify a recipient."
    if not message_text:
        return "Please specify the message content."

    message_text = _with_persona_footer(
        message_text,
        str(params.get("_persona_name", "JARVIS")),
    )
    duplicate = _check_duplicate_send(platform, receiver, message_text)
    if duplicate:
        print(f"[SendMessage] ⏭️ {duplicate}")
        if player:
            player.write_log(f"[msg] {duplicate}")
        return duplicate

    preview = message_text[:50] + ("…" if len(message_text) > 50 else "")
    print(f"[SendMessage] 📨 {platform} → {receiver}: {preview}")
    if player:
        player.write_log(f"[msg] {platform} → {receiver}")

    try:
        handler = _resolve_platform(platform)
        result  = handler(receiver, message_text)
    except Exception as e:
        result = f"Could not send message: {e}"

    if _message_send_succeeded(result):
        _record_successful_send(platform, receiver, message_text)
        _clear_pending_message()
    elif _is_instagram_platform(platform_key) and "draft typed" in (result or "").lower():
        _set_pending_message(platform, receiver, message_text)

    lowered = (result or "").lower()
    if "draft typed" in lowered:
        status_icon = "📝"
    elif "sent" in lowered:
        status_icon = "✅"
    else:
        status_icon = "❌"
    print(f"[SendMessage] {status_icon} {result}")
    if player:
        player.write_log(f"[msg] {result}")

    return result


def prepare_message_reply(
    parameters: dict | None = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Prepare, approve, or cancel a message without losing recipient context."""
    params = parameters or {}
    action = str(params.get("action", "prepare") or "prepare").lower().strip()

    if action in {"approve", "confirm", "send"}:
        pending = _get_pending_message()
        if not pending:
            return "There is no pending message awaiting approval."
        platform = str(pending.get("platform", "") or "")
        platform_key = platform.lower()
        if _is_instagram_platform(platform_key):
            result = send_open_browser_draft("Instagram", ("instagram.com/direct",))
        else:
            result = send_message({
                "action": "send",
                "platform": platform,
                "receiver": pending.get("receiver", ""),
                "message_text": pending.get("message_text", ""),
            }, player=player)
        if _message_send_succeeded(result):
            _record_successful_send(
                platform,
                str(pending.get("receiver", "") or ""),
                str(pending.get("message_text", "") or ""),
            )
            _clear_pending_message()
        return result

    if action in {"cancel", "discard", "deny"}:
        pending = _get_pending_message()
        platform_key = str(pending.get("platform", "") or "").lower()
        cleared = True
        if _is_instagram_platform(platform_key):
            cleared = clear_open_browser_draft(("instagram.com/direct",))
        _clear_pending_message()
        return "Pending message cancelled." if cleared else "Pending message cancelled, but the visible draft could not be cleared."

    receiver = str(params.get("receiver", "") or "").strip()
    message_text = str(params.get("message_text", "") or params.get("draft", "") or "").strip()
    platform = str(params.get("platform", "iMessage") or "iMessage").strip()
    if not message_text:
        return "Please provide the reply text to prepare."

    platform_key = platform.lower()
    prepared_text = _with_persona_footer(
        message_text,
        str(params.get("_persona_name", "JARVIS")),
    )
    if _is_instagram_platform(platform_key):
        result = prepare_instagram_draft(receiver, prepared_text)
        if "draft typed" not in result.lower():
            return result
        _set_pending_message(platform, receiver, prepared_text)
    else:
        _set_pending_message(platform, receiver, prepared_text)

    payload = {
        "platform": platform,
        "receiver": receiver or "current chat",
        "message_text": prepared_text,
    }
    return (
        "MESSAGE_APPROVAL_REQUIRED|"
        + json.dumps(payload, separators=(",", ":"))
        + "\nDraft prepared. Ask the user to approve, revise, or cancel it."
    )
