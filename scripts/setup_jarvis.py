"""Cross-platform one-time JARVIS setup (Windows, macOS, Linux)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
PYTHON = VENV / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")


def run(*args: str) -> None:
    print("+", " ".join(args))
    subprocess.check_call(args, cwd=ROOT)


def main() -> int:
    print("JARVIS setup — Windows / macOS / Linux")
    if shutil.which("python3"):
        host_python = "python3"
    elif shutil.which("python"):
        host_python = "python"
    else:
        print("Python 3.11+ is required: https://www.python.org/downloads/")
        return 1

    if not PYTHON.exists():
        run(host_python, "-m", "venv", str(VENV))
    run(str(PYTHON), "-m", "pip", "install", "--upgrade", "pip")
    run(str(PYTHON), "-m", "pip", "install", "-r", "requirements.txt")
    run(str(PYTHON), "-m", "pip", "install", "-e", ".")

    env_file = ROOT / ".env"
    if not env_file.exists():
        shutil.copyfile(ROOT / ".env.example", env_file)
        print("Created .env. Add your GEMINI_API_KEY before launching.")
    else:
        print("Keeping existing .env.")

    command_dir = VENV / ("Scripts" if os.name == "nt" else "bin")
    print("\nSetup complete.")
    print(f"Activate the environment: {command_dir / ('activate.bat' if os.name == 'nt' else 'activate')}")
    print("Then launch with: jarvis")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
