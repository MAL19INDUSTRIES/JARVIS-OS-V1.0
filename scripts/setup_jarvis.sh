#!/usr/bin/env bash
# Guided one-command setup for JARVIS on macOS/Linux.
set -e

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
PROJECT_ROOT="$(cd -P "$(dirname "$SOURCE")/.." >/dev/null 2>&1 && pwd)"
cd "$PROJECT_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
echo "JARVIS setup"
echo "────────────"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3 is required. Install it from https://www.python.org/downloads/"
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating the JARVIS virtual environment..."
  "$PYTHON_BIN" -m venv .venv
fi

echo "Installing dependencies..."
".venv/bin/python" -m pip install --upgrade pip >/dev/null
".venv/bin/python" -m pip install -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from the safe template."
else
  echo "Keeping your existing .env."
fi

./scripts/install_jarvis_cli.sh

echo
echo "Setup complete. Add your Gemini key to .env, then run:"
echo "  source \"$HOME/.zprofile\"  # macOS zsh, if needed"
echo "  jarvis"
