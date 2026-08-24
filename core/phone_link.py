"""Local, opt-in iPhone chat bridge for the desktop JARVIS process.

The first release deliberately stays small: a single-use QR exchanges for a
remembered device credential, then the phone can send chat turns while it is
on the same network and this desktop process is running.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, urlparse


DEFAULT_PORT = 8765
PAIRING_LIFETIME_SECONDS = 120
MAX_BODY_BYTES = 16_384
MAX_MESSAGE_CHARS = 2_000


@dataclass(frozen=True)
class PairingInfo:
    url: str
    token: str
    expires_at: float


class PhoneLinkError(RuntimeError):
    pass


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _lan_host() -> str:
    """Return a LAN-reachable address without contacting an internet service."""
    hostname = socket.gethostname().strip()
    if hostname:
        local_name = hostname if hostname.endswith(".local") else f"{hostname}.local"
        try:
            socket.getaddrinfo(local_name, None, socket.AF_INET)
            return local_name
        except OSError:
            pass
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        value = sock.getsockname()[0]
        if value and not value.startswith("127."):
            return value
    except OSError:
        pass
    finally:
        sock.close()
    return "127.0.0.1"


def _is_local_client(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
        return address.is_private or address.is_loopback or address.is_link_local
    except ValueError:
        return False


class PhoneLinkService:
    """Thread-safe local HTTP service backing the Phone Link workspace."""

    def __init__(
        self,
        *,
        state_path: Path | None = None,
        asset_dir: Path | None = None,
        host: str = "0.0.0.0",
        port: int = DEFAULT_PORT,
        dispatch: Callable[[str], None] | None = None,
        persona: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        root = Path(__file__).resolve().parents[1]
        self.state_path = state_path or Path.home() / ".jarvis" / "config" / "phone_link.json"
        self.asset_dir = asset_dir or root / "assets" / "phone_link"
        self.host = host
        self.port = int(port)
        self._dispatch = dispatch
        self._persona = persona or (lambda: "JARVIS")
        self._clock = clock
        self._lock = threading.RLock()
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._pairings: dict[str, float] = {}
        self._messages: deque[dict] = deque(maxlen=250)
        self._sequence = 0
        self._state = self._read_state()
        self._rate: dict[tuple[str, str], deque[float]] = {}

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def bound_port(self) -> int:
        server = self._server
        return int(server.server_address[1]) if server else self.port

    def set_dispatch(self, callback: Callable[[str], None] | None) -> None:
        self._dispatch = callback

    def _read_state(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("devices", []), list):
                return {"version": 1, "devices": data.get("devices", [])}
        except (OSError, ValueError, TypeError):
            pass
        return {"version": 1, "devices": []}

    def _write_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)
        try:
            os.chmod(self.state_path, 0o600)
        except OSError:
            pass

    def start(self) -> None:
        with self._lock:
            if self._server is not None:
                return
            service = self

            class Handler(_PhoneLinkHandler):
                phone_link = service

            try:
                self._server = ThreadingHTTPServer((self.host, self.port), Handler)
            except OSError as exc:
                raise PhoneLinkError(f"Could not open the local Phone Link service: {exc}") from exc
            self._server.daemon_threads = True
            self._server_thread = threading.Thread(
                target=self._server.serve_forever,
                name="jarvis-phone-link",
                daemon=True,
            )
            self._server_thread.start()

    def stop(self) -> None:
        with self._lock:
            server = self._server
            thread = self._server_thread
            self._server = None
            self._server_thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def create_pairing(self) -> PairingInfo:
        self.start()
        now = self._clock()
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._pairings = {
                item: expiry for item, expiry in self._pairings.items() if expiry > now
            }
            self._pairings[_token_hash(token)] = now + PAIRING_LIFETIME_SECONDS
        host = _lan_host()
        port = self.bound_port
        suffix = "" if port == 80 else f":{port}"
        return PairingInfo(
            url=f"http://{host}{suffix}/phone/#pair={token}",
            token=token,
            expires_at=now + PAIRING_LIFETIME_SECONDS,
        )

    def devices(self) -> list[dict]:
        with self._lock:
            return [
                {key: value for key, value in device.items() if key != "token_hash"}
                for device in self._state["devices"]
            ]

    def revoke_device(self, device_id: str) -> bool:
        with self._lock:
            before = len(self._state["devices"])
            self._state["devices"] = [
                device for device in self._state["devices"]
                if device.get("id") != str(device_id)
            ]
            changed = len(self._state["devices"]) != before
            if changed:
                self._write_state()
            return changed

    def exchange_pairing(
        self,
        token: str,
        device_name: str,
        client_kind: str = "web",
    ) -> dict:
        now = self._clock()
        digest = _token_hash(str(token or ""))
        with self._lock:
            expiry = self._pairings.pop(digest, None)
            if expiry is None or expiry <= now:
                raise PhoneLinkError("This QR code is invalid or has expired.")
            raw_device_token = secrets.token_urlsafe(48)
            normalized_client = (
                "ios-native" if str(client_kind).strip().casefold() == "ios-native" else "web"
            )
            device = {
                "id": uuid.uuid4().hex,
                "name": str(device_name or "iPhone").strip()[:80] or "iPhone",
                "client_kind": normalized_client,
                "token_hash": _token_hash(raw_device_token),
                "paired_at": now,
                "last_seen": now,
            }
            self._state["devices"].append(device)
            self._write_state()
        self.publish_message("assistant", "iPhone linked. You can talk to me here whenever JARVIS is running on this network.")
        return {
            "device_token": raw_device_token,
            "device": {key: value for key, value in device.items() if key != "token_hash"},
        }

    def authenticate(self, token: str) -> dict | None:
        digest = _token_hash(str(token or ""))
        now = self._clock()
        with self._lock:
            for device in self._state["devices"]:
                if hmac.compare_digest(str(device.get("token_hash", "")), digest):
                    device["last_seen"] = now
                    return device
        return None

    def session(self, device: dict, after: int = 0) -> dict:
        with self._lock:
            messages = [item.copy() for item in self._messages if item["seq"] > after]
        return {
            "connected": True,
            "persona": str(self._persona() or "JARVIS").upper(),
            "device": {key: value for key, value in device.items() if key != "token_hash"},
            "messages": messages,
        }

    def publish_message(self, role: str, content: str, *, source: str = "desktop") -> dict | None:
        clean = " ".join(str(content or "").split()).strip()
        if not clean:
            return None
        with self._lock:
            self._sequence += 1
            message = {
                "seq": self._sequence,
                "role": "user" if role == "user" else "assistant",
                "content": clean[:MAX_MESSAGE_CHARS],
                "source": source,
                "time": self._clock(),
            }
            self._messages.append(message)
            return message.copy()

    def publish_log(self, text: str) -> dict | None:
        value = str(text or "").strip()
        if ":" not in value:
            return None
        speaker, content = value.split(":", 1)
        normalized = speaker.strip().lower()
        if normalized == "you":
            return self.publish_message("user", content, source="desktop")
        if normalized in {"jarvis", "ultron", "atlas"}:
            return self.publish_message("assistant", content, source="desktop")
        return None

    def receive_chat(self, device: dict, text: str) -> dict:
        clean = " ".join(str(text or "").split()).strip()[:MAX_MESSAGE_CHARS]
        if not clean:
            raise PhoneLinkError("Message cannot be empty.")
        self.publish_message("user", clean, source=device.get("name", "iPhone"))
        native_client = device.get("client_kind") == "ios-native"
        capability_reply = _phone_capability_reply(clean, native=native_client)
        if capability_reply:
            self.publish_message("assistant", capability_reply, source="phone")
            return {"accepted": True, "handled": "capabilities"}
        handoff = _phone_handoff(clean, native=native_client)
        if handoff:
            self.publish_message("assistant", handoff["message"], source="phone")
            return {"accepted": True, "handoff": handoff}
        limitation = _phone_handoff_limitation(clean, native=native_client)
        if limitation:
            self.publish_message("assistant", limitation, source="phone")
            return {"accepted": True, "handled": "phone-action-limitation"}
        callback = self._dispatch
        if callback is None:
            raise PhoneLinkError("JARVIS is not ready for messages yet.")
        callback(clean)
        return {"accepted": True}

    def rate_allowed(self, address: str, action: str, *, limit: int, seconds: float) -> bool:
        now = self._clock()
        key = (address, action)
        with self._lock:
            samples = self._rate.setdefault(key, deque())
            while samples and samples[0] <= now - seconds:
                samples.popleft()
            if len(samples) >= limit:
                return False
            samples.append(now)
            return True


def _phone_handoff(message: str, *, native: bool = False) -> dict | None:
    """Build an explicit, user-tapped iOS handoff for narrow safe actions."""
    lowered = " ".join(message.casefold().split())
    lowered = re.sub(r"^(?:please\s+|can you\s+|could you\s+|would you\s+)", "", lowered)
    lowered = re.sub(r"\s+(?:on|from) my (?:iphone|phone)$", "", lowered)
    normalized_message = message.strip()
    normalized_message = re.sub(
        r"^(?:please\s+|can you\s+|could you\s+|would you\s+)",
        "",
        normalized_message,
        flags=re.IGNORECASE,
    )
    normalized_message = re.sub(
        r"\s+(?:on|from) my (?:iphone|phone)$",
        "",
        normalized_message,
        flags=re.IGNORECASE,
    )
    call_match = re.match(
        r"^(?:call|dial|phone)\s+(?:the\s+number\s+)?(.+)$",
        normalized_message,
        flags=re.IGNORECASE,
    )
    if call_match:
        target = call_match.group(1).strip()
        number = "".join(
            char for char in target
            if char.isdigit() or char in "+*#"
        )
        if len(number) >= 3:
            return {
                "kind": "call",
                "label": f"Call {number}",
                "recipient": number,
                "url": f"tel:{number}",
                "message": "I prepared the call. Tap below to confirm it on your iPhone.",
            }
        if native and target:
            return {
                "kind": "call-contact",
                "label": f"Call {target}",
                "contact": target,
                "message": "I found a contact request. Confirm it on your iPhone before I place the call.",
            }
    message_match = re.match(
        r"^(?:(?:send|write)\s+)?(?:a\s+)?(?:message|text|sms)(?:\s+to)?\s+(.+)$",
        normalized_message,
        flags=re.IGNORECASE,
    )
    if message_match:
            remainder = message_match.group(1).strip()
            target, separator, body = remainder.partition(":")
            if not separator:
                parts = re.split(
                    r"\s+(?:saying|that says)\s+", remainder,
                    maxsplit=1, flags=re.IGNORECASE,
                )
                if len(parts) == 2:
                    target, body = parts
                    separator = "saying"
            number = "".join(char for char in target if char.isdigit() or char in "+*#")
            if len(number) >= 3:
                draft = body.strip() if separator else ""
                url = f"sms:{number}"
                if draft:
                    url += f"&body={quote(draft, safe='')}"
                return {
                    "kind": "message",
                    "label": f"Open Messages to {number}",
                    "recipient": number,
                    "url": url,
                    "copy": draft,
                    "message": "I prepared the message. Tap below to review and send it yourself.",
                }
            if native and target:
                draft = body.strip() if separator else ""
                return {
                    "kind": "message-contact",
                    "label": f"Message {target}",
                    "contact": target.strip(),
                    "copy": draft,
                    "message": "I prepared the message. Confirm it, then review and send it in Messages.",
                }
    if native and re.search(
        r"\b(?:open|start|use)\s+(?:the\s+)?camera\b|\b(?:take|capture)\s+(?:a\s+)?(?:photo|picture)\b",
        lowered,
    ):
        return {
            "kind": "camera",
            "label": "Open Camera",
            "message": "Camera access is ready. Confirm to open the camera inside JARVIS.",
        }
    if native and re.search(
        r"\b(?:enable|allow|turn on)\s+(?:jarvis\s+)?notifications?\b",
        lowered,
    ):
        return {
            "kind": "notifications",
            "label": "Enable JARVIS Notifications",
            "message": "Confirm to let iOS show notifications sent by the JARVIS companion.",
        }
    links = {
        "instagram": "https://www.instagram.com/",
        "maps": "https://maps.apple.com/",
        "music": "https://music.apple.com/",
        "youtube": "https://www.youtube.com/",
    }
    for app, url in links.items():
        if re.search(
            rf"\b(?:open|launch|start|take me to)\s+(?:the\s+)?{app}(?:\s+app)?\b",
            lowered,
        ):
            return {
                "kind": "open",
                "label": f"Open {app.title()}",
                "url": url,
                "message": f"Tap below to open {app.title()} on your iPhone.",
            }
    return None


def _phone_handoff_limitation(message: str, *, native: bool = False) -> str | None:
    lowered = " ".join(str(message or "").casefold().split())
    if re.search(r"\b(?:read|show|check|summarize)\b.*\bnotifications?\b", lowered):
        return "iOS does not allow JARVIS to read notifications belonging to other apps."
    if re.search(r"\b(?:while|when)\s+(?:the\s+)?phone\s+is\s+locked\b|\bunlock\s+(?:my\s+)?phone\b", lowered):
        return "iOS does not allow a persistent JARVIS network-control session while the phone is locked."
    if not native and re.search(r"\bcamera\b|\b(?:take|capture)\s+(?:a\s+)?(?:photo|picture)\b", lowered):
        return "Camera actions require the installed JARVIS iPhone app; the Safari chat cannot access it."
    if re.search(r"\b(?:call|dial|phone|message|text|sms)\b", lowered):
        if not re.search(r"\d{3,}", lowered):
            return (
                "I can prepare that handoff, but this web link cannot read your iPhone "
                "contacts. Include the phone number and I will create the confirmation card."
            )
    return None


def _phone_capability_reply(message: str, *, native: bool = False) -> str | None:
    lowered = " ".join(str(message or "").casefold().split())
    asks_about_phone = any(term in lowered for term in (
        "what can you do", "what can jarvis do", "control my phone",
        "access my phone", "do anything on my phone", "phone capabilities",
    ))
    if not asks_about_phone:
        return None
    if native:
        return (
            "From the JARVIS iPhone app, I can prepare calls and message drafts using "
            "phone numbers or your contacts, open supported app links, open the JARVIS "
            "camera, and request JARVIS notification permission. Sensitive actions require "
            "your confirmation. iOS does not allow me to read other apps' notifications, "
            "silently send messages, automate arbitrary app screens, or keep a network "
            "control session running while the phone is locked."
        )
    return (
        "From this linked iPhone, you can chat with me and control JARVIS on your Mac. "
        "I can also prepare calls to phone numbers, message drafts to phone numbers, "
        "and links for Instagram, Maps, Music, or YouTube. Those phone actions appear "
        "as a confirmation card and only run when you tap it. Contacts, notifications, "
        "Contact lookup, the JARVIS camera, and JARVIS notifications require the installed "
        "native companion. Other apps' notifications and locked-screen control remain unavailable."
    )


class _PhoneLinkHandler(BaseHTTPRequestHandler):
    phone_link: PhoneLinkService
    server_version = "JARVISPhoneLink/1"

    def log_message(self, _format: str, *_args) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'",
        )
        super().end_headers()

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _asset(self, name: str, content_type: str) -> None:
        path = self.phone_link.asset_dir / name
        try:
            body = path.read_bytes()
        except OSError:
            self._json(HTTPStatus.NOT_FOUND, {"error": "Phone Link asset not found."})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise PhoneLinkError("Invalid request body.") from exc
        if size <= 0 or size > MAX_BODY_BYTES:
            raise PhoneLinkError("Invalid request body.")
        try:
            data = json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise PhoneLinkError("Invalid JSON request.") from exc
        if not isinstance(data, dict):
            raise PhoneLinkError("Invalid request body.")
        return data

    def _device(self) -> dict | None:
        header = self.headers.get("Authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        return self.phone_link.authenticate(token) if token else None

    def _local_or_reject(self) -> bool:
        if _is_local_client(self.client_address[0]):
            return True
        self._json(HTTPStatus.FORBIDDEN, {"error": "Phone Link only accepts local-network devices."})
        return False

    def do_GET(self) -> None:
        if not self._local_or_reject():
            return
        route = urlparse(self.path)
        if route.path in {"/phone", "/phone/"}:
            self._asset("index.html", "text/html; charset=utf-8")
            return
        if route.path == "/phone/phone.css":
            self._asset("phone.css", "text/css; charset=utf-8")
            return
        if route.path == "/phone/phone.js":
            self._asset("phone.js", "text/javascript; charset=utf-8")
            return
        if route.path == "/phone/space-grotesk.ttf":
            font_path = self.phone_link.asset_dir.parent / "fonts" / "SpaceGrotesk-Variable.ttf"
            try:
                body = font_path.read_bytes()
            except OSError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Font asset not found."})
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "font/ttf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route.path == "/api/phone/session":
            device = self._device()
            if device is None:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Pair this iPhone with JARVIS first."})
                return
            try:
                after = max(0, int(parse_qs(route.query).get("after", ["0"])[0]))
            except ValueError:
                after = 0
            self._json(HTTPStatus.OK, self.phone_link.session(device, after))
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

    def do_POST(self) -> None:
        if not self._local_or_reject():
            return
        route = urlparse(self.path).path
        try:
            if route == "/api/phone/pair":
                if not self.phone_link.rate_allowed(self.client_address[0], "pair", limit=8, seconds=60):
                    self._json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "Too many pairing attempts."})
                    return
                body = self._body()
                result = self.phone_link.exchange_pairing(
                    str(body.get("pair_token", "")),
                    str(body.get("device_name", "iPhone")),
                    str(body.get("client_kind", "web")),
                )
                self._json(HTTPStatus.CREATED, result)
                return
            if route == "/api/phone/chat":
                device = self._device()
                if device is None:
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "This iPhone link was revoked."})
                    return
                if not self.phone_link.rate_allowed(device["id"], "chat", limit=30, seconds=60):
                    self._json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "Please wait before sending more messages."})
                    return
                result = self.phone_link.receive_chat(device, str(self._body().get("message", "")))
                self._json(HTTPStatus.ACCEPTED, result)
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
        except PhoneLinkError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Phone Link could not complete the request."})
