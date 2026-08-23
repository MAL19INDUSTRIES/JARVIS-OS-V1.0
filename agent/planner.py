import json
import os
import re
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


PLANNER_PROMPT = """You are the planning module of MARK XXV, a personal AI assistant.
Your job: break any user goal into a sequence of steps using ONLY the tools listed below.

ABSOLUTE RULES:
- NEVER use generated_code or write Python scripts. It does not exist.
- NEVER reference previous step results in parameters. Every step is independent.
- Use web_search for ordinary information retrieval or a single current-data lookup.
- Use deep_research directly when the user explicitly asks for deep, thorough, comprehensive, or source-backed research.
- Use file_controller to save final gathered content to disk.
- NEVER create placeholder files like "results will be added later".
- If the goal says research and save, first gather the research, then write the actual research content into the file.
- For file_controller write/create_file after web_search steps, content may be left empty or brief; the executor will inject prior search results automatically.

- SPEED RULE: For normal research-and-save tasks, use ONE strong web_search query, not 2-3 separate searches.
- Never imitate deep research with repeated web_search steps; deep_research owns planning, evidence gathering, citations, and report output.
- Prefer fewer steps. A good research-save task should usually be: web_search -> file_controller.
- Do not waste steps creating empty files before writing. Write the final report directly.
- Use create_presentation directly for every request to make a PowerPoint, presentation, slide deck, pitch deck, or slideshow.
- Never route presentation creation through code_helper, file_controller, or generated code.

- Max 5 steps. Use the minimum steps needed.

AVAILABLE TOOLS AND THEIR PARAMETERS:

open_app
  app_name: string (required)

web_search
  query: string (required) — write a clear, focused search query
  mode: "search" or "compare" (optional, default: search)
  items: list of strings (optional, for compare mode)
  aspect: string (optional, for compare mode)

deep_research
  question: string (required)
  execution_mode: "ask" | "background" | "visible" (required; background=status bar, visible=controlled browser)
  depth: "quick" | "standard" | "deep" (optional, default: standard)
  focus_areas: list of strings (optional)
  max_sources: integer 5-50 (optional)
  output_path: string (optional; only for a later explicit save action)

game_updater
  action: "update" | "install" | "list" | "download_status" | "schedule" (required)
  platform: "steam" | "epic" | "both" (optional, default: both)
  game_name: string (optional)
  app_id: string (optional)
  shutdown_when_done: boolean (optional)

browser_control
  action: "go_to" | "search" | "click" | "type" | "scroll" | "get_text" | "press" | "close" (required)
  url: string (for go_to)
  query: string (for search)
  text: string (for click/type)
  direction: "up" | "down" (for scroll)

file_controller
  action: "open" | "write" | "create_file" | "read" | "list" | "delete" | "move" | "copy" | "find" | "disk_usage" (required)
  path: string — use "desktop" for Desktop folder
  name: string — filename
  content: string — file content (for write/create_file)

media_control
  action: "play" | "pause" | "stop" | "toggle" | "next" | "previous" | "play_query" (required)
  platform: "spotify" | "apple_music" | "youtube_music" | "system" (optional, default: spotify)
  query: string (optional; song, artist, album, playlist, or Spotify link)

computer_settings
  action: string (required)
  description: string — natural language description
  value: string (optional)

computer_control
  action: "type" | "click" | "hotkey" | "press" | "scroll" | "screenshot" | "screen_find" | "screen_click" (required)
  text: string (for type)
  x, y: int (for click)
  keys: string (for hotkey, e.g. "ctrl+c")
  key: string (for press)
  direction: "up" | "down" (for scroll)
  description: string (for screen_find/screen_click)

screen_process
  text: string (required) — what to analyze or ask about the screen
  angle: "screen" | "camera" (optional)

send_message
  receiver: string (required)
  message_text: string (required)
  platform: string (required)

email_control
  action: "connect" | "status" | "disconnect" | "inbox" | "unread" | "search" | "read" | "prepare" | "approve" | "cancel" (required)
  provider: "gmail" | "apple_mail" | "default" (optional, default: gmail)
  browser: string (optional; default: chrome for visible Gmail compose)
  credentials_path: string (for connect; Google Desktop OAuth client JSON)
  limit: integer 1-30 (optional)
  query: string (for search)
  message_id: string (for read)
  to: string (for prepare)
  cc: string (optional)
  bcc: string (optional)
  subject: string (for prepare)
  body: string (for prepare)

reminder
  date: string YYYY-MM-DD (required)
  time: string HH:MM (required)
  message: string (required)

desktop_control
  action: "wallpaper" | "organize" | "clean" | "list" | "task" (required)
  path: string (optional)
  task: string (optional)

youtube_video
  action: "play" | "summarize" | "trending" (required)
  query: string (for play)

weather_report
  city: string (required)

flight_finder
  origin: string (required)
  destination: string (required)
  date: string (required)

jarvis_ui_control
  action: "open_command_center" | "close_command_center" | "change_theme" | "open_settings" | "compact_mode" | "fullscreen" | "show_shortcuts" (required)
  theme: "arc_reactor" | "stealth_red" | "vibranium_purple" | "nanotech_gold" | "platinum" (required for change_theme)

create_presentation
  topic: string (required)
  execution_mode: "ask" | "background" | "visible" (required; always ask on the initial call)
  mode: "auto" | "create" | "edit" | "redesign" | "extend" (optional)
  title: string (optional)
  audience: string (optional)
  slide_count: integer 3-50 (optional, default: 8)
  tone: string (optional)
  theme: "jarvis_minimal" | "editorial" | "arc_reactor" | "executive" | "platinum" (optional, default: jarvis_minimal)
  appearance: "auto" | "light" | "dark" (optional, default: auto)
  transition: "morph" | "fade" | "none" (optional, default: morph)
  source_file: string (optional)
  source_files: list of strings (optional)
  source_urls: list of strings (optional)
  template_file: string (optional)
  model_source_file: string (optional; PPTX used only to borrow embedded native 3D models)
  use_native_3d: boolean (optional; set true when the user asks to use PowerPoint 3D models)
  three_d_mode: "ask" | "yes" | "no" (optional; omit or ask initially so JARVIS can request the user's preference)
  quality: "fast" | "quality" | "premium" (optional)
  allow_web_research: boolean (optional, default: false)
  export_pdf: boolean (optional, default: true)
  include_speaker_notes: boolean (optional, default: false)
  output_path: string (optional)
  open_after_create: boolean (optional, default: false)

code_helper
  action: "write" | "edit" | "run" | "explain" (required)
  description: string (required)
  language: string (optional)
  output_path: string (optional)
  file_path: string (optional)

dev_agent
  description: string (required)
  language: string (optional)
EXAMPLES:

Goal: "research mechanical engineering and save it to a notepad file"
Steps:

web_search | query: "mechanical engineering overview definition history"
web_search | query: "mechanical engineering applications and future trends"
file_controller | action: write, path: desktop, name: mechanical_engineering.txt, content: ""

Goal: "What is the price of Bitcoin"
Steps:

web_search | query: "Bitcoin price today USD"

Goal: "List the files on the desktop and find the largest 5 files"
Steps:

file_controller | action: list, path: desktop
file_controller | action: largest, path: desktop, count: 5

Goal: "Install PUBG from Steam"
Steps:

game_updater | action: install, platform: steam, game_name: "PUBG"

Goal: "Update all my Steam games"
Steps:

game_updater | action: update, platform: steam

Goal: "Create an eight-slide PowerPoint about renewable energy for students"
Steps:

create_presentation | topic: "renewable energy", audience: "students", slide_count: 8

Goal: "Send John a message on WhatsApp saying there is a meeting tomorrow"
Steps:

send_message | receiver: John, message_text: "There is a meeting tomorrow", platform: WhatsApp

Goal: "Open the clock and set a reminder for 30 minutes later"
Steps:

reminder | date: [today], time: [now+30min], message: "Reminder"

OUTPUT — return ONLY valid JSON, no markdown, no explanation, no code blocks:
{
  "goal": "...",
  "steps": [
    {
      "step": 1,
      "tool": "tool_name",
      "description": "what this step does",
      "parameters": {},
      "critical": true
    }
  ]
}
"""


def _get_api_key() -> str:
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key

    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            key = data.get("gemini_api_key") or data.get("GEMINI_API_KEY")
            if key:
                return key
    except Exception:
        pass

    raise ValueError("Gemini API key not found. Set GEMINI_API_KEY or config/api_keys.json['gemini_api_key'].")


def create_plan(goal: str, context: str = "") -> dict:
    import google.generativeai as genai

    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        system_instruction=PLANNER_PROMPT
    )

    user_input = f"Goal: {goal}"
    if context:
        user_input += f"\n\nContext: {context}"

    try:
        response = model.generate_content(user_input)
        text     = response.text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

        plan = json.loads(text)

        if "steps" not in plan or not isinstance(plan["steps"], list):
            raise ValueError("Invalid plan structure")

        for step in plan["steps"]:
            if step.get("tool") in ("generated_code",):
                print(f"[Planner] ⚠️ generated_code detected in step {step.get('step')} — replacing with web_search")
                desc = step.get("description", goal)
                step["tool"] = "web_search"
                step["parameters"] = {"query": desc[:200]}

        print(f"[Planner] ✅ Plan: {len(plan['steps'])} steps")
        for s in plan["steps"]:
            print(f"  Step {s['step']}: [{s['tool']}] {s['description']}")

        return plan

    except json.JSONDecodeError as e:
        print(f"[Planner] ⚠️ JSON parse failed: {e}")
        return _fallback_plan(goal)
    except Exception as e:
        print(f"[Planner] ⚠️ Planning failed: {e}")
        return _fallback_plan(goal)


def _fallback_plan(goal: str) -> dict:
    print("[Planner] 🔄 Fallback plan")
    if re.search(r"\b(email|emails|e-mail|inbox)\b", goal, re.I):
        action = "inbox"
        parameters = {"action": action, "limit": 10}
        if re.search(r"\b(send|compose|write)\b", goal, re.I):
            parameters = {"action": "prepare", "provider": "gmail", "browser": "chrome"}
            address = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", goal)
            subject = re.search(r"(?i)\bsubject\s+(.+?)(?=\s+\b(?:saying|body)\b|$)", goal)
            body = re.search(r"(?i)\b(?:saying|body)\s+(.+)$", goal)
            if address:
                parameters["to"] = address.group(0)
            if subject:
                parameters["subject"] = subject.group(1).strip(" .\"'")
            if body:
                parameters["body"] = body.group(1).strip(" .\"'")
        elif re.search(r"\bunread\b", goal, re.I):
            parameters["action"] = "unread"
        search_match = re.search(r"(?i)\b(?:search|find)\s+(?:my\s+)?(?:email|emails|inbox)\s+(?:for|from)\s+(.+)$", goal)
        if search_match and parameters["action"] != "prepare":
            parameters = {"action": "search", "query": search_match.group(1).strip(" .")}
        return {
            "goal": goal,
            "steps": [{
                "step": 1,
                "tool": "email_control",
                "description": "Access the requested email information.",
                "parameters": parameters,
                "critical": True,
            }],
        }
    media_match = re.search(
        r"\b(spotify|apple\s+music|youtube\s+music|music|song|track|playback)\b",
        goal,
        re.I,
    )
    media_command = re.search(
        r"\b(play|resume|pause|stop|toggle|skip|next|previous|back)\b",
        goal,
        re.I,
    )
    if media_match and media_command:
        spoken_action = media_command.group(1).lower()
        action = {
            "resume": "play",
            "skip": "next",
            "back": "previous",
        }.get(spoken_action, spoken_action)
        platform_name = "spotify"
        if re.search(r"\bapple\s+music\b", goal, re.I):
            platform_name = "apple_music"
        elif re.search(r"\byoutube\s+music\b", goal, re.I):
            platform_name = "youtube_music"
        parameters = {"action": action, "platform": platform_name}
        if action == "play":
            query = re.sub(
                r"(?i)^.*?\bplay\b|\b(?:on|in|using)\s+(?:spotify|apple\s+music|youtube\s+music)\b.*$",
                "",
                goal,
            )
            query = re.sub(r"(?i)\bplease\b", "", query).strip(" .,")
            if query and query.lower() not in {"music", "song", "a song", "spotify"}:
                parameters["action"] = "play_query"
                parameters["query"] = query
        return {
            "goal": goal,
            "steps": [{
                "step": 1,
                "tool": "media_control",
                "description": "Control the requested music playback.",
                "parameters": parameters,
                "critical": True,
            }],
        }
    if re.search(r"\b(power\s*point|powerpoint|presentation|slide\s+deck|pitch\s+deck|slideshow)\b", goal, re.I):
        count_match = re.search(r"\b(\d{1,2})[ -]slide\b", goal, re.I)
        parameters = {"topic": goal, "execution_mode": "ask"}
        if re.search(r"\b(?:dark|black background|midnight)\b", goal, re.I):
            parameters["appearance"] = "dark"
        elif re.search(r"\b(?:light|white background|bright|airy)\b", goal, re.I):
            parameters["appearance"] = "light"
        if re.search(r"\b(?:3d|three[- ]dimensional)\b.*\bmodel|\bmodel.*\b(?:3d|powerpoint)\b", goal, re.I):
            parameters["use_native_3d"] = True
        if count_match:
            parameters["slide_count"] = max(3, min(50, int(count_match.group(1))))
        return {
            "goal": goal,
            "steps": [
                {
                    "step": 1,
                    "tool": "create_presentation",
                    "description": "Create the requested editable PowerPoint presentation.",
                    "parameters": parameters,
                    "critical": True,
                }
            ],
        }
    if re.search(r"\b(deep|thorough|comprehensive|source[- ]backed)\s+(?:web\s+)?research\b", goal, re.I):
        depth = "deep" if re.search(r"\b(deep|comprehensive)\b", goal, re.I) else "standard"
        return {
            "goal": goal,
            "steps": [
                {
                    "step": 1,
                    "tool": "deep_research",
                    "description": "Ask how the source-grounded deep research should be displayed.",
                    "parameters": {"question": goal, "depth": depth, "execution_mode": "ask"},
                    "critical": True,
                }
            ],
        }
    return {
        "goal": goal,
        "steps": [
            {
                "step": 1,
                "tool": "web_search",
                "description": f"Search for: {goal}",
                "parameters": {"query": goal},
                "critical": True
            }
        ]
    }


def replan(goal: str, completed_steps: list, failed_step: dict, error: str) -> dict:
    import google.generativeai as genai

    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=PLANNER_PROMPT
    )

    completed_summary = "\n".join(
        f"  - Step {s['step']} ({s['tool']}): DONE" for s in completed_steps
    )

    prompt = f"""Goal: {goal}

Already completed:
{completed_summary if completed_summary else '  (none)'}

Failed step: [{failed_step.get('tool')}] {failed_step.get('description')}
Error: {error}

Create a REVISED plan for the remaining work only. Do not repeat completed steps."""

    try:
        response = model.generate_content(prompt)
        text     = response.text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        plan     = json.loads(text)

        for step in plan.get("steps", []):
            if step.get("tool") == "generated_code":
                step["tool"] = "web_search"
                step["parameters"] = {"query": step.get("description", goal)[:200]}

        print(f"[Planner] 🔄 Revised plan: {len(plan['steps'])} steps")
        return plan
    except Exception as e:
        print(f"[Planner] ⚠️ Replan failed: {e}")
        return _fallback_plan(goal)
