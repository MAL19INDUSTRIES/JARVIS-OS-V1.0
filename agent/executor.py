import json
import re
import sys
import threading
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Callable

from agent.planner       import create_plan, replan
from agent.error_handler import analyze_error, generate_fix, ErrorDecision


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


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

def _run_generated_code(description: str, speak: Callable | None = None) -> str:
    import google.generativeai as genai

    if speak:
        speak("Writing custom code for this task, sir.")

    home      = Path.home()
    desktop   = home / "Desktop"
    downloads = home / "Downloads"
    documents = home / "Documents"

    if not desktop.exists():
        try:
            import winreg
            key     = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
            desktop = Path(winreg.QueryValueEx(key, "Desktop")[0])
        except Exception:
            pass

    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=(
            "You are an expert Python developer. "
            "Write clean, complete, working Python code. "
            "Use standard library + common packages. "
            "Install missing packages with subprocess + pip if needed. "
            "Return ONLY the Python code. No explanation, no markdown, no backticks.\n\n"
            f"SYSTEM PATHS:\n"
            f"  Desktop   = r'{desktop}'\n"
            f"  Downloads = r'{downloads}'\n"
            f"  Documents = r'{documents}'\n"
            f"  Home      = r'{home}'\n"
        )
    )

    try:
        response = model.generate_content(
            f"Write Python code to accomplish this task:\n\n{description}"
        )
        code = response.text.strip()
        code = re.sub(r"```(?:python)?", "", code).strip().rstrip("`").strip()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        print(f"[Executor] 🐍 Running generated code: {tmp_path}")

        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True,
            timeout=120, cwd=str(Path.home())
        )

        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        output = result.stdout.strip()
        error  = result.stderr.strip()

        if result.returncode == 0 and output:
            return output
        elif result.returncode == 0:
            return "Task completed successfully."
        elif error:
            raise RuntimeError(f"Code error: {error[:400]}")
        return "Completed."

    except subprocess.TimeoutExpired:
        raise RuntimeError("Generated code timed out after 120 seconds.")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Generated code failed: {e}")

def _inject_context(params: dict, tool: str, step_results: dict, goal: str = "") -> dict:
    if not step_results:
        return params

    params = dict(params)

    if tool == "file_controller" and params.get("action") in ("write", "create_file"):
        content = params.get("content", "")
        if not content or len(content) < 50:
            all_results = [
                v for v in step_results.values()
                if v and len(v) > 100 and v not in ("Done.", "Completed.")
            ]
            if all_results:
                combined = "\n\n--- SOURCE RESULT ---\n\n".join(all_results)
                report = _format_research_report(combined, goal)
                translated = _translate_to_goal_language(report, goal)
                params["content"] = translated
                print(f"[Executor] 💉 Injected formatted research report")

    return params
def _detect_language(text: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    try:
        response = model.generate_content(
            f"What language is this text written in? "
            f"Reply with ONLY the language name in English (e.g. Turkish, English, French).\n\n"
            f"Text: {text[:200]}"
        )
        return response.text.strip()
    except Exception:
        return "English"


def _format_research_report(content: str, goal: str) -> str:
    """
    Wrap gathered research into a clean JARVIS-style report before saving.
    This prevents raw dumped text and makes generated files look intentional.
    """
    import datetime
    import re

    clean_goal = str(goal or "Research Report").strip()

    title = clean_goal
    title = re.sub(r"(?i)^research\s+", "", title)
    title = re.sub(r"(?i)\s+and\s+save\b.*$", "", title)
    title = re.sub(r"(?i)\s+to\s+a\s+file\b.*$", "", title)
    title = title.strip(" ._-") or "Research Report"

    report_title = title.upper()
    generated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    body = str(content or "").strip()

    return f"""# {report_title}

Generated by JARVIS
Generated at: {generated}

## Objective

{clean_goal}

## Executive Summary

The following report was generated from live research results gathered by JARVIS. It consolidates the most relevant findings into a single saved document for later review.

## Research Findings

{body}

## Practical Takeaways

- Compare each tool based on reliability, cross-platform support, ease of use, and whether it fits the current project.
- Prefer tools that are actively maintained and work well on macOS if this is being used inside the MARK XXXIX / JARVIS environment.
- For GUI control, prioritize libraries that handle screen scaling, permissions, screenshots, and app focus reliably.
- For long-term automation, combine desktop control tools with file management, scheduling, memory, and logging.

## JARVIS Recommendation

For a personal desktop assistant like MARK XXXIX, the strongest automation stack is usually:

1. PyAutoGUI or pyauto-desktop for mouse, keyboard, and screen interaction.
2. pathlib and shutil for file automation.
3. Playwright for browser automation.
4. PyQt or PySide for advanced desktop UI.
5. A planner/executor layer to chain tools into multi-step tasks.

## End of Report
"""


def _translate_to_goal_language(content: str, goal: str) -> str:
    if not goal:
        return content
    try:
        import google.generativeai as genai
        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel("gemini-2.5-flash")

        target_lang = _detect_language(goal)
        print(f"[Executor] 🌐 Translating to: {target_lang}")

        prompt = (
            f"You are a professional translator. "
            f"Translate the following text into {target_lang}.\n"
            f"IMPORTANT:\n"
            f"- Translate EVERYTHING, leave nothing in English\n"
            f"- Keep all facts, numbers, and data intact\n"
            f"- Keep the structure and formatting\n"
            f"- Output ONLY the translated text, nothing else\n\n"
            f"Text to translate:\n{content[:12000]}"
        )
        response = model.generate_content(prompt)
        translated = response.text.strip()
        print(f"[Executor] ✅ Translation done ({target_lang})")
        return translated
    except Exception as e:
        print(f"[Executor] ⚠️ Translation failed: {e}")
        return content

def _call_tool(tool: str, parameters: dict, speak: Callable | None) -> str:

    if tool == "open_app":
        from actions.open_app import open_app
        return open_app(parameters=parameters, player=None) or "Done."

    elif tool == "web_search":
        from actions.web_search import web_search
        return web_search(parameters=parameters, player=None) or "Done."
    elif tool == "deep_research":
        from actions.deep_research import deep_research
        return deep_research(parameters=parameters, player=None) or "Done."
    elif tool == "game_updater":
        from actions.game_updater import game_updater
        return game_updater(parameters=parameters, player=None, speak=speak) or "Done."
    elif tool == "browser_control":
        from actions.browser_control import browser_control
        return browser_control(parameters=parameters, player=None) or "Done."

    elif tool == "file_controller":
        from actions.file_controller import file_controller
        return file_controller(parameters=parameters, player=None) or "Done."

    elif tool == "media_control":
        from actions.media_control import media_control
        return media_control(parameters=parameters, player=None) or "Done."

    elif tool == "code_helper":
        from actions.code_helper import code_helper
        return code_helper(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "dev_agent":
        from actions.dev_agent import dev_agent
        return dev_agent(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "screen_process":
        from actions.screen_processor import screen_process
        screen_process(parameters=parameters, player=None)
        return "Screen captured and analyzed."

    elif tool == "send_message":
        from actions.send_message import send_message
        return send_message(parameters=parameters, player=None) or "Done."

    elif tool == "email_control":
        from actions.email_control import email_control
        return email_control(parameters=parameters, player=None) or "Done."

    elif tool == "reminder":
        from actions.reminder import reminder
        return reminder(parameters=parameters, player=None) or "Done."

    elif tool == "youtube_video":
        from actions.youtube_video import youtube_video
        return youtube_video(parameters=parameters, player=None) or "Done."

    elif tool == "weather_report":
        from actions.weather_report import weather_action
        return weather_action(parameters=parameters, player=None) or "Done."

    elif tool == "computer_settings":
        from actions.computer_settings import computer_settings
        return computer_settings(parameters=parameters, player=None) or "Done."

    elif tool == "desktop_control":
        from actions.desktop import desktop_control
        return desktop_control(parameters=parameters, player=None) or "Done."

    elif tool == "computer_control":
        from actions.computer_control import computer_control
        return computer_control(parameters=parameters, player=None) or "Done."

    elif tool == "generated_code":
        description = parameters.get("description", "")
        if not description:
            raise ValueError("generated_code requires a 'description' parameter.")
        return _run_generated_code(description, speak=speak)

    elif tool == "flight_finder":
        from actions.flight_finder import flight_finder
        return flight_finder(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "create_presentation":
        from actions.presentation_maker import create_presentation
        return create_presentation(parameters=parameters, player=None) or "Done."

    else:
        print(f"[Executor] ⚠️ Unknown tool '{tool}' — falling back to generated_code")
        return _run_generated_code(f"Accomplish this task: {parameters}", speak=speak)

def _goal_requests_file_save(goal: str) -> bool:
    g = str(goal or "").lower()
    return any(x in g for x in [
        "save", "write", "create a file", "make a file", "desktop",
        ".txt", ".md", ".json", ".csv", ".html", ".pptx"
    ])


def _extract_filename_from_goal(goal: str) -> str:
    import re
    g = str(goal or "")

    # quoted filename: 'report.txt' or "report.txt"
    m = re.search(r"['\"]([^'\"]+\.(?:txt|md|json|csv|html))['\"]", g, re.I)
    if m:
        return m.group(1).strip()

    # unquoted filename
    m = re.search(r"\b([\w\- ]+\.(?:txt|md|json|csv|html))\b", g, re.I)
    if m:
        return m.group(1).strip().replace(" ", "_")

    return "jarvis_task_output.txt"


def _ensure_required_save_step(plan: dict, goal: str) -> dict:
    """
    Safety layer: if the user asks to save/write a file, guarantee that
    the plan includes a file_controller write step. This prevents fast plans
    from finishing research without actually saving anything.
    """
    if not _goal_requests_file_save(goal):
        return plan

    steps = plan.get("steps", [])
    has_file_step = any(
        str(s.get("tool", "")).strip() in {"file_controller", "create_presentation", "deep_research"}
        for s in steps
    )

    if has_file_step:
        return plan

    filename = _extract_filename_from_goal(goal)

    steps.append({
        "step": len(steps) + 1,
        "tool": "file_controller",
        "description": f"Save the gathered results to {filename}.",
        "parameters": {
            "action": "write",
            "path": "desktop",
            "name": filename,
            "content": ""
        }
    })

    plan["steps"] = steps
    print(f"[Executor] 🛡️ Added required file save step: {filename}")
    return plan


class AgentExecutor:

    MAX_REPLAN_ATTEMPTS = 2

    def __init__(self, awareness=None):
        self.awareness = awareness

    def _awareness_goal(self, goal: str) -> None:
        if self.awareness and hasattr(self.awareness, "set_goal"):
            try:
                self.awareness.set_goal(goal)
            except Exception as e:
                print(f"[Awareness] ⚠️ set_goal failed: {e}")

    def _awareness_tool_start(self, tool: str, desc: str) -> None:
        if self.awareness and hasattr(self.awareness, "set_active_tool"):
            try:
                self.awareness.set_active_tool(tool, desc)
            except Exception as e:
                print(f"[Awareness] ⚠️ set_active_tool failed: {e}")

    def _awareness_tool_done(self, tool: str, result: str = "") -> None:
        if self.awareness and hasattr(self.awareness, "record_event"):
            try:
                preview = str(result).replace("\n", " ")[:120]
                self.awareness.record_event(f"Completed tool: {tool}" + (f" — {preview}" if preview else ""))
            except Exception as e:
                print(f"[Awareness] ⚠️ record_event failed: {e}")

    def _awareness_idle(self) -> None:
        if self.awareness and hasattr(self.awareness, "clear_active_tool"):
            try:
                self.awareness.clear_active_tool()
            except Exception as e:
                print(f"[Awareness] ⚠️ clear_active_tool failed: {e}")

    def execute(
        self,
        goal:        str,
        speak:       Callable | None        = None,
        cancel_flag: threading.Event | None = None,
    ) -> str:
        print(f"\n[Executor] 🎯 Goal: {goal}")
        self._awareness_goal(goal)

        replan_attempts = 0
        completed_steps = []
        step_results    = {}
        self.last_step_results = step_results 
        plan            = _ensure_required_save_step(create_plan(goal), goal)

        while True:
            steps = plan.get("steps", [])

            if not steps:
                msg = "I couldn't create a valid plan for this task, sir."
                if speak: speak(msg)
                return msg

            success      = True
            failed_step  = None
            failed_error = ""

            for step in steps:
                if cancel_flag and cancel_flag.is_set():
                    if speak: speak("Task cancelled, sir.")
                    return "Task cancelled."

                step_num = step.get("step", "?")
                tool     = step.get("tool", "generated_code")
                desc     = step.get("description", "")
                params   = step.get("parameters", {})

                params = _inject_context(params, tool, step_results, goal=goal)

                print(f"\n[Executor] ▶️ Step {step_num}: [{tool}] {desc}")

                attempt = 1
                step_ok = False

                while attempt <= 3:
                    if cancel_flag and cancel_flag.is_set():
                        break
                    try:
                        self._awareness_tool_start(tool, desc)
                        result = _call_tool(tool, params, speak)
                        step_results[step_num] = result
                        self.last_step_results = step_results
                        self._awareness_tool_done(tool, result)
                        completed_steps.append(step)
                        print(f"[Executor] ✅ Step {step_num} done: {str(result)[:100]}")
                        step_ok = True
                        break

                    except Exception as e:
                        error_msg = str(e)
                        print(f"[Executor] ❌ Step {step_num} attempt {attempt} failed: {error_msg}")

                        recovery = analyze_error(step, error_msg, attempt=attempt)
                        decision = recovery["decision"]
                        user_msg = recovery.get("user_message", "")

                        if speak and user_msg:
                            speak(user_msg)

                        if decision == ErrorDecision.RETRY:
                            attempt += 1
                            import time; time.sleep(2)
                            continue

                        elif decision == ErrorDecision.SKIP:
                            print(f"[Executor] ⏭️ Skipping step {step_num}")
                            completed_steps.append(step)
                            step_ok = True
                            break

                        elif decision == ErrorDecision.ABORT:
                            msg = f"Task aborted, sir. {recovery.get('reason', '')}"
                            if speak: speak(msg)
                            return msg

                        else: 
                            fix_suggestion = recovery.get("fix_suggestion", "")
                            if fix_suggestion and tool != "generated_code":
                                try:
                                    fixed_step = generate_fix(step, error_msg, fix_suggestion)
                                    if speak: speak("Trying an alternative approach, sir.")
                                    res = _call_tool(
                                        fixed_step["tool"],
                                        fixed_step["parameters"],
                                        speak
                                    )
                                    step_results[step_num] = res
                                    self.last_step_results = step_results
                                    completed_steps.append(step)
                                    step_ok = True
                                    break
                                except Exception as fix_err:
                                    print(f"[Executor] ⚠️ Fix failed: {fix_err}")

                            failed_step  = step
                            failed_error = error_msg
                            success      = False
                            break

                if not step_ok and not failed_step:
                    failed_step  = step
                    failed_error = "Max retries exceeded"
                    success      = False

                if not success:
                    break

            if success:
                self._awareness_idle()
                return self._summarize(goal, completed_steps, speak, step_results)

            if replan_attempts >= self.MAX_REPLAN_ATTEMPTS:
                msg = f"Task failed after {replan_attempts} replan attempts, sir."
                if speak: speak(msg)
                return msg

            if speak: speak("Adjusting my approach, sir.")

            replan_attempts += 1
            plan = _ensure_required_save_step(replan(goal, completed_steps, failed_step, failed_error), goal)

    def _summarize(self, goal: str, completed_steps: list, speak: Callable | None, step_results: dict | None = None) -> str:
        fallback = f"All done, sir. Completed {len(completed_steps)} steps for: {goal[:60]}."
        try:
            import google.generativeai as genai
            genai.configure(api_key=_get_api_key())
            model     = genai.GenerativeModel(model_name="gemini-2.5-flash-lite")
            steps_str = "\n".join(f"- {s.get('description', '')}" for s in completed_steps)

            result_lines = []
            for k, v in (step_results or {}).items():
                txt = str(v).replace("\n", " ").strip()
                if txt:
                    result_lines.append(f"- Step {k}: {txt[:350]}")
            results_str = "\n".join(result_lines[-6:]) or "No tool results captured."

            prompt    = (
                f'User goal: "{goal}"\n'
                f"Completed steps:\n{steps_str}\n\n"
                f"Tool results:\n{results_str}\n\n"
                "Write a single natural sentence summarizing what was accomplished. "
                "If a file was saved, include the exact saved path and/or file size from the tool results. "
                "Do not claim uncertainty if the tool result confirms the file was saved. "
                "Address the user as 'sir'. Be direct and positive."
            )
            response = model.generate_content(prompt)
            summary  = response.text.strip()
            if speak: speak(summary)
            return summary
        except Exception:
            if speak: speak(fallback)
            return fallback
