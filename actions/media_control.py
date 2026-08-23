"""Cross-platform music and media playback control, with Spotify first-class support."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from urllib.parse import quote, urlparse


_SYSTEM = platform.system()

_ACTION_ALIASES = {
    "resume": "play",
    "continue": "play",
    "play_pause": "toggle",
    "playpause": "toggle",
    "toggle_playback": "toggle",
    "skip": "next",
    "next_track": "next",
    "prev": "previous",
    "previous_track": "previous",
}

_PLATFORM_ALIASES = {
    "": "spotify",
    "music": "spotify",
    "spotify app": "spotify",
    "apple": "apple_music",
    "apple music": "apple_music",
    "itunes": "apple_music",
    "youtube": "youtube_music",
    "youtube music": "youtube_music",
    "yt music": "youtube_music",
    "default": "system",
}


def _run(command: list[str], timeout: int = 12) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _run_osascript(script: str, *arguments: str) -> subprocess.CompletedProcess:
    return _run(["osascript", "-e", script, *arguments])


def _open_uri(uri: str) -> tuple[bool, str]:
    try:
        if _SYSTEM == "Windows":
            os.startfile(uri)  # type: ignore[attr-defined]
            return True, ""
        command = ["open", uri] if _SYSTEM == "Darwin" else ["xdg-open", uri]
        result = _run(command)
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout or "request rejected").strip()
    except Exception as exc:
        return False, str(exc)


def _spotify_uri(value: str) -> str:
    """Convert Spotify links to app URIs; return an empty string for plain search text."""
    value = str(value or "").strip()
    if value.lower().startswith("spotify:"):
        return value
    try:
        parsed = urlparse(value)
        if parsed.netloc.lower() not in {"open.spotify.com", "play.spotify.com"}:
            return ""
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"track", "album", "playlist", "artist", "episode", "show"}:
            return f"spotify:{parts[0]}:{parts[1]}"
    except Exception:
        pass
    return ""


def _spotify_macos(action: str, query: str) -> str:
    if action == "play_query":
        uri = _spotify_uri(query)
        if uri:
            script = (
                'on run argv\n'
                'tell application "Spotify"\n'
                'activate\n'
                'play track (item 1 of argv)\n'
                'end tell\n'
                'end run'
            )
            result = _run_osascript(script, uri)
            if result.returncode == 0:
                return "Playing the requested item on Spotify."
            return f"Spotify could not play that link: {(result.stderr or result.stdout).strip()}"

        ok, detail = _open_uri(f"spotify:search:{quote(query)}")
        if ok:
            return f"Opened Spotify results for {query}. Select a result to begin playback."
        return f"Could not open Spotify search: {detail}"

    scripts = {
        "play": 'tell application "Spotify" to play',
        "pause": 'tell application "Spotify" to pause',
        "stop": (
            'tell application "Spotify"\n'
            'pause\n'
            'try\nset player position to 0\nend try\n'
            'end tell'
        ),
        "toggle": (
            'tell application "Spotify"\n'
            'if player state is playing then\n'
            'pause\nelse\nplay\nend if\n'
            'end tell'
        ),
        "next": 'tell application "Spotify" to next track',
        "previous": 'tell application "Spotify" to previous track',
    }
    result = _run_osascript(scripts[action])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Spotify did not respond").strip()
        return f"Spotify control failed: {detail}"
    labels = {
        "play": "Playing Spotify.",
        "pause": "Spotify paused.",
        "stop": "Spotify stopped.",
        "toggle": "Spotify playback toggled.",
        "next": "Skipped to the next Spotify track.",
        "previous": "Returned to the previous Spotify track.",
    }
    return labels[action]


def _apple_music_macos(action: str, query: str) -> str:
    if action == "play_query":
        script = (
            'on run argv\n'
            'set searchText to item 1 of argv\n'
            'tell application "Music"\n'
            'activate\n'
            'set matches to every file track of library playlist 1 whose name contains searchText\n'
            'if (count of matches) is 0 then return "NOT_FOUND"\n'
            'play item 1 of matches\n'
            'end tell\n'
            'return "PLAYING"\n'
            'end run'
        )
        result = _run_osascript(script, query)
        if result.returncode == 0 and "PLAYING" in result.stdout:
            return f"Playing {query} in Apple Music."
        if result.returncode == 0:
            return f"I could not find {query} in your Apple Music library."
        return f"Apple Music search failed: {(result.stderr or result.stdout).strip()}"

    command = {
        "toggle": "playpause",
        "next": "next track",
        "previous": "previous track",
    }.get(action, action)
    script = f'tell application "Music" to {command}'
    result = _run_osascript(script)
    if result.returncode != 0:
        return f"Apple Music control failed: {(result.stderr or result.stdout).strip()}"
    return f"Apple Music: {action} completed."


def _linux_playerctl(action: str, platform_name: str) -> str:
    if not shutil.which("playerctl"):
        return "Media control requires playerctl on Linux, but it is not installed."
    command = "play-pause" if action == "toggle" else action
    args = ["playerctl"]
    if platform_name == "spotify":
        args.extend(["--player", "spotify"])
    args.append(command)
    result = _run(args)
    if result.returncode != 0:
        return f"Media control failed: {(result.stderr or result.stdout or 'no active player').strip()}"
    return f"Media {action} completed."


def _generic_media_key(action: str) -> str:
    key_map = {
        "play": "playpause",
        "pause": "playpause",
        "toggle": "playpause",
        "stop": "stop",
        "next": "nexttrack",
        "previous": "prevtrack",
    }
    try:
        import pyautogui

        pyautogui.press(key_map[action])
        return f"System media {action} command sent."
    except Exception as exc:
        return f"System media control is unavailable: {exc}"


def media_control(parameters: dict | None = None, response=None, player=None, session_memory=None) -> str:
    """Control Spotify, Apple Music, YouTube Music, or the active system player."""
    params = parameters or {}
    action = str(params.get("action", "toggle")).lower().strip().replace("-", "_").replace(" ", "_")
    action = _ACTION_ALIASES.get(action, action)
    platform_name = str(params.get("platform", "spotify")).lower().strip().replace("-", "_")
    platform_name = _PLATFORM_ALIASES.get(platform_name.replace("_", " "), platform_name)
    query = str(params.get("query", "")).strip()

    if action == "play" and query:
        action = "play_query"
    allowed = {"play", "pause", "stop", "toggle", "next", "previous", "play_query"}
    if action not in allowed:
        return f"Unknown media action: '{action}'. Available: play, pause, stop, toggle, next, previous, play_query."
    if platform_name not in {"spotify", "apple_music", "youtube_music", "system"}:
        return f"Unknown music platform: '{platform_name}'. Available: Spotify, Apple Music, YouTube Music, or system."
    if action == "play_query" and not query:
        return "Tell me which song, artist, album, playlist, or Spotify link to play."

    if player:
        player.write_log(f"[Media] {platform_name} // {action}" + (f" // {query}" if query else ""))

    if platform_name == "youtube_music" and action == "play_query":
        from actions.youtube_video import youtube_video

        return youtube_video({"action": "play", "query": query}, player=player)

    if action == "play_query" and platform_name not in {"spotify", "apple_music", "youtube_music"}:
        return "Choose Spotify, Apple Music, or YouTube Music when asking me to find a specific song."

    if platform_name == "spotify" and action == "play_query" and _SYSTEM != "Darwin":
        uri = _spotify_uri(query)
        ok, detail = _open_uri(uri or f"spotify:search:{quote(query)}")
        if ok:
            if uri:
                return "Opened the requested item in Spotify."
            return f"Opened Spotify results for {query}. Select a result to begin playback."
        return f"Could not open Spotify: {detail}"

    if _SYSTEM == "Darwin" and platform_name == "spotify":
        return _spotify_macos(action, query)
    if _SYSTEM == "Darwin" and platform_name == "apple_music":
        return _apple_music_macos(action, query)
    if _SYSTEM == "Linux":
        return _linux_playerctl(action, platform_name)
    return _generic_media_key(action)
