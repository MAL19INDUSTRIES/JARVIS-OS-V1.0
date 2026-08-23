import json
import re
import subprocess
from pathlib import Path

from actions.instagram_browser import read_instagram_open_chat
from actions.send_message import _best_name_matches, _load_contacts_candidates


def _base_dir() -> Path:
    if getattr(__import__("sys"), "frozen", False):
        return Path(__import__("sys").executable).parent
    return Path(__file__).resolve().parent.parent


def _get_os() -> str:
    try:
        cfg = json.loads(
            (_base_dir() / "config" / "api_keys.json").read_text(encoding="utf-8")
        )
        return cfg.get("os_system", "windows").lower()
    except Exception:
        return "windows"


def _run_osascript(script: str, *, javascript: bool = False, timeout: float = 5.0) -> subprocess.CompletedProcess:
    cmd = ["osascript"]
    if javascript:
        cmd.extend(["-l", "JavaScript"])
    cmd.extend(["-e", script])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _clean_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _is_noise_line(text: str) -> bool:
    value = _clean_line(text).lower()
    if not value:
        return True
    if value in {
        "messages", "search", "notes", "requests", "message...", "message",
        "imessage", "to:", "new message", "details", "info",
    }:
        return True
    if re.match(r"^(active|online|seen|sent|delivered|read|typing|now)$", value):
        return True
    if re.match(r"^(active|seen|sent|delivered|read).*(ago|now)$", value):
        return True
    if re.match(r"^\d+[smhdw]\b", value) or value.endswith(" ago"):
        return True
    return False


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
          return tab.execute({{javascript: {json.dumps(dom_js)}}}) || '';
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
          return app.doJavaScript({json.dumps(dom_js)}, {{in: tab}}) || '';
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
  return safari() || JSON.stringify({{ok:false,error:'No supported browser tab found'}});
}})();
"""


def _read_instagram_open_chat() -> dict:
    dom_js = r"""
(() => {
  const clean = (text) => String(text || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 20 && r.height > 10 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const noise = (line) => /^(active|online|seen|sent|delivered|read|typing|now|message|message\.\.\.|details|info)$/i.test(line)
    || /^(active|seen|sent|delivered|read).*(ago|now)$/i.test(line)
    || /^\d+[smhdw]\b/i.test(line)
    || / ago$/i.test(line);
  const main = document.querySelector('main') || document.body;
  const headerCandidates = Array.from(main.querySelectorAll('header h1, header h2, header a, header span, h1, h2, a[href^="/"]'))
    .filter(visible)
    .filter(el => {
      const r = el.getBoundingClientRect();
      return r.left > innerWidth * 0.32 && r.top < Math.max(180, innerHeight * 0.24);
    })
    .map(el => clean(el.innerText || el.textContent))
    .filter(Boolean)
    .map(line => line.split(/\n+/).map(clean).filter(Boolean)[0] || line)
    .filter(line => !noise(line) && !/^(messages|search|notes|requests|home|explore|reels|create|profile|more)$/i.test(line));
  const recipient = headerCandidates[0] || '';
  const rightSide = Array.from(main.querySelectorAll('div, span, p'))
    .filter(visible)
    .filter(el => {
      const r = el.getBoundingClientRect();
      return r.left > innerWidth * 0.32 && r.top > 80 && r.bottom < innerHeight - 45;
    })
    .map(el => clean(el.innerText || el.textContent))
    .filter(Boolean)
    .filter(text => text.length <= 500);
  const lines = [];
  const seen = new Set();
  for (const block of rightSide) {
    for (const line of block.split(/\n+/).map(clean).filter(Boolean)) {
      if (noise(line)) continue;
      if (recipient && line === recipient) continue;
      if (/^(account|your note)$/i.test(line)) continue;
      const key = line.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      lines.push(line);
    }
  }
  return JSON.stringify({
    ok: !!recipient || lines.length > 0,
    platform: 'Instagram',
    recipient,
    latest_message: lines[lines.length - 1] || '',
    visible_messages: lines.slice(-6),
    can_reply: !!recipient && lines.length > 0,
    source: location.href
  });
})()
"""
    try:
        result = _run_osascript(
            _browser_jxa_for_matching_tab(("instagram.com/direct",), dom_js),
            javascript=True,
            timeout=6,
        )
    except Exception as e:
        return {"ok": False, "platform": "Instagram", "error": str(e)}
    if result.returncode != 0:
        return {"ok": False, "platform": "Instagram", "error": (result.stderr or result.stdout).strip()}
    try:
        data = json.loads(result.stdout.strip() or "{}")
    except Exception as e:
        return {"ok": False, "platform": "Instagram", "error": f"{e}: {result.stdout[:160]}"}
    return data if isinstance(data, dict) else {"ok": False, "platform": "Instagram", "error": "Invalid browser response."}


def _read_contacts_summary(query: str = "", *, limit: int = 25) -> dict:
    contacts = _load_contacts_candidates()
    if not contacts:
        return {
            "ok": False,
            "kind": "contacts",
            "error": "Could not read Contacts. Grant Terminal or VS Code Contacts/Automation permission in macOS System Settings.",
        }
    query = str(query or "").strip()
    if query:
        matches, _ = _best_name_matches(query, contacts, limit=limit)
        selected = matches
    else:
        selected = contacts[:limit]
    safe_contacts = []
    for contact in selected[:limit]:
        aliases = []
        for alias in contact.get("aliases", []):
            alias = str(alias or "").strip()
            if alias and alias not in aliases and alias != str(contact.get("name", "")):
                aliases.append(alias)
        safe_contacts.append({
            "name": str(contact.get("name", "") or "").strip(),
            "aliases": aliases[:6],
        })
    return {
        "ok": bool(safe_contacts),
        "kind": "contacts",
        "query": query,
        "count": len(safe_contacts),
        "contacts": safe_contacts,
    }


def _read_imessage_open_chat(max_messages: int = 30) -> dict:
    script = r'''
tell application "System Events"
    if not (exists process "Messages") then return "ERR:Messages is not open"
    tell process "Messages"
        set frontmost to true
        delay 0.1
        if (count of windows) is 0 then return "ERR:Messages has no open window"
        set outputLines to {}
        set containers to {window 1}
        try
            set containers to containers & (groups of window 1)
        end try
        try
            set containers to containers & (scroll areas of window 1)
        end try
        try
            set containers to containers & (groups of scroll areas of window 1)
        end try
        repeat with containerRef in containers
            try
                repeat with itemRef in static texts of containerRef
                    try
                        set valueValue to value of itemRef as text
                        if valueValue is not "" then set end of outputLines to valueValue
                    end try
                    if (count of outputLines) ≥ 160 then exit repeat
                end repeat
            end try
            try
                repeat with itemRef in text areas of containerRef
                    try
                        set valueValue to value of itemRef as text
                        if valueValue is not "" then set end of outputLines to valueValue
                    end try
                    if (count of outputLines) ≥ 160 then exit repeat
                end repeat
            end try
            if (count of outputLines) ≥ 160 then exit repeat
        end repeat
    end tell
end tell
if (count of outputLines) is 0 then return "ERR:No readable Messages text found. Open a conversation and grant Accessibility permission."
set AppleScript's text item delimiters to linefeed
return outputLines as text
'''
    try:
        result = _run_osascript(script, timeout=2.5)
    except Exception as e:
        return {
            "ok": False,
            "platform": "iMessage",
            "error": "Timed out reading Messages. Open the chat, keep Messages visible, and grant Accessibility permission.",
        }
    if result.returncode != 0:
        return {"ok": False, "platform": "iMessage", "error": (result.stderr or result.stdout).strip()}
    raw = result.stdout.strip()
    if raw.startswith("ERR:"):
        return {"ok": False, "platform": "iMessage", "error": raw[4:]}
    lines = []
    seen = set()
    for line in raw.splitlines():
        cleaned = _clean_line(line)
        if _is_noise_line(cleaned):
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(cleaned)
    recipient = lines[0] if lines else ""
    messages = lines[1:] if len(lines) > 1 else lines
    max_messages = max(6, min(int(max_messages or 30), 80))
    conversation = messages[-max_messages:]
    return {
        "ok": bool(lines),
        "platform": "iMessage",
        "recipient": recipient,
        "latest_message": messages[-1] if messages else "",
        "visible_messages": conversation[-10:],
        "conversation_context": conversation,
        "message_count": len(conversation),
        "can_reply": bool(recipient and messages),
        "source": "Messages window 1",
    }


def _format_update(update: dict) -> str:
    if not update.get("ok"):
        platform = update.get("platform", "Messaging")
        return f"{platform}: could not read open chat. {update.get('error', 'Open a supported chat and try again.')}"
    platform = update.get("platform", "Messaging")
    recipient = update.get("recipient") or "unknown recipient"
    latest = update.get("latest_message") or "No readable message found."
    can_reply = "yes" if update.get("can_reply") else "no"
    count = update.get("message_count") or len(update.get("conversation_context") or update.get("visible_messages") or [])
    return f"{platform}: {recipient} latest message: \"{latest}\". Read {count} current-chat lines. Can reply: {can_reply}."


def check_messages(parameters: dict | None = None, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    platform = str(params.get("platform", "all") or "all").lower().strip()
    include_contacts = bool(params.get("include_contacts")) or platform in {"contacts", "contact", "address book"}
    contact_query = str(params.get("contact_query", "") or params.get("receiver", "") or "").strip()
    try:
        max_messages = int(params.get("max_messages", 30) or 30)
    except Exception:
        max_messages = 30
    updates = []
    contacts = None
    if platform in {"all", "instagram", "ig", "insta"}:
        updates.append(read_instagram_open_chat())
    if platform in {"all", "imessage", "messages", "apple messages", "sms"}:
        updates.append(_read_imessage_open_chat(max_messages=max_messages))
    if include_contacts:
        contacts = _read_contacts_summary(contact_query)
    readable = [u for u in updates if u.get("ok")]
    summary = "\n".join(_format_update(update) for update in updates)
    if contacts:
        contact_line = (
            f"Contacts: read {contacts.get('count', 0)} matching names."
            if contacts.get("ok")
            else f"Contacts: {contacts.get('error', 'could not read contacts.')}"
        )
        summary = "\n".join(part for part in (summary, contact_line) if part)
    payload = {"updates": updates, "readable_count": len(readable)}
    if contacts:
        payload["contacts"] = contacts
    return "MESSAGES_CHECKED|" + json.dumps(payload, separators=(",", ":")) + "\n" + summary
