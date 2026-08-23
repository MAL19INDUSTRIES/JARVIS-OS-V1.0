from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ApiKeyValidationResult:
    valid: bool
    message: str


def describe_api_key_for_log(api_key: str) -> str:
    key = normalize_gemini_api_key(api_key)
    if not key:
        return "empty"
    prefix = key[:4] if len(key) >= 4 else key
    if key.startswith("AIza"):
        kind = "google-api-key"
    elif re.fullmatch(r"[0-9A-Za-z_\-\.]{20,}", key):
        kind = "token-shaped"
    else:
        kind = "not-token-shaped"
    return f"{kind}, len={len(key)}, starts={prefix!r}"


def normalize_gemini_api_key(api_key: str) -> str:
    key = str(api_key or "").strip()
    key = (
        key.replace("\u200b", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
        .replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )

    embedded = re.search(r"AIza[0-9A-Za-z_\-]{20,}", key)
    if embedded:
        return embedded.group(0).strip()

    token = _extract_plausible_token(key)
    if token:
        return token

    if key.lower().startswith("export "):
        key = key[7:].strip()

    assignment = re.match(
        r"(?is)^(?:export\s+)?(?:GEMINI_API_KEY|GOOGLE_API_KEY|API_KEY)\s*=\s*([\"'`]?)(.+?)\1\s*;?\s*$",
        key,
    )
    if assignment:
        key = assignment.group(2).strip()

    if len(key) >= 2 and key[0] == key[-1] and key[0] in {"'", '"', "`"}:
        key = key[1:-1].strip()
    key = key.strip().strip(",;")

    embedded = re.search(r"AIza[0-9A-Za-z_\-]{20,}", key)
    if embedded:
        return embedded.group(0).strip()

    token = _extract_plausible_token(key)
    if token:
        return token

    return key


def _extract_plausible_token(text: str) -> str:
    ignored_words = {
        "gemini_api_key",
        "google_api_key",
        "api_key",
        "apikey",
        "export",
        "const",
        "let",
        "var",
    }
    candidates = re.findall(r"[0-9A-Za-z_\-\.]{20,}", str(text or ""))
    for candidate in candidates:
        if candidate.lower() not in ignored_words:
            return candidate.strip().strip(",;")
    return ""


def _basic_key_check(api_key: str) -> ApiKeyValidationResult | None:
    key = normalize_gemini_api_key(api_key)
    if not key:
        return ApiKeyValidationResult(False, "API key is empty.")
    if any(ch.isspace() for ch in key):
        return ApiKeyValidationResult(False, "Paste the raw Gemini API key value, not surrounding text.")
    if key.startswith("sk-ant-"):
        return ApiKeyValidationResult(False, "That is an Anthropic key. JARVIS requires a Gemini API key.")
    if key.startswith(("sk-", "sess-", "proj-")):
        return ApiKeyValidationResult(False, "That is not a Gemini key. Use a key created in Google AI Studio.")
    # Gemini now supports more than one API-key type. Do not require the
    # legacy Google "AIza" prefix; provider identity is established by the
    # authenticated Gemini models request below.
    if len(key) < 20 or not re.fullmatch(r"[0-9A-Za-z_\-\.]+", key):
        return ApiKeyValidationResult(
            False,
            "This does not look like an API key. Paste the raw key created in Google AI Studio.",
        )
    return None


def _validate_with_gemini(api_key: str, timeout_seconds: float) -> ApiKeyValidationResult:
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=max(1000, int(timeout_seconds * 1000))),
        )
        models = list(client.models.list())
        if not models:
            return ApiKeyValidationResult(
                False,
                "Gemini accepted the request but returned no accessible models for this key.",
            )
        has_live_model = any(
            "bidigeneratecontent" in {
                str(action).lower()
                for action in (
                    getattr(model, "supported_actions", None)
                    or getattr(model, "supportedActions", None)
                    or []
                )
            }
            for model in models
        )
        if not has_live_model:
            return ApiKeyValidationResult(
                False,
                "The key is valid for Gemini, but this project has no Gemini Live model access. Enable Gemini Live/billing for the project or create an authorization key in Google AI Studio.",
            )
        return ApiKeyValidationResult(True, "Gemini API key verified.")
    except Exception as e:
        text = str(e).strip() or e.__class__.__name__
        lowered = text.lower()
        if "api key not valid" in lowered or "invalid api key" in lowered:
            return ApiKeyValidationResult(False, "API key is not valid.")
        if "api_key_invalid" in lowered or "api key invalid" in lowered:
            return ApiKeyValidationResult(False, "API key is not valid.")
        if "unauthenticated" in lowered or "401" in lowered:
            return ApiKeyValidationResult(False, "API key was rejected by Gemini.")
        if "permission" in lowered or "403" in lowered:
            return ApiKeyValidationResult(
                False,
                "Gemini rejected this key's permissions. Create an authorization key in Google AI Studio or restrict the key to the Generative Language API.",
            )
        return ApiKeyValidationResult(
            False,
            f"Gemini could not verify this key. Check your connection and try again. ({text[:120]})",
        )


def validate_gemini_api_key(api_key: str, timeout_seconds: float = 8.0) -> ApiKeyValidationResult:
    key = normalize_gemini_api_key(api_key)
    basic = _basic_key_check(key)
    if basic is not None:
        return basic

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_validate_with_gemini, key, timeout_seconds)
    try:
        return future.result(timeout=timeout_seconds)
    except TimeoutError:
        future.cancel()
        return ApiKeyValidationResult(
            False,
            "Gemini validation timed out. Check your connection and try again; the key was not saved.",
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
