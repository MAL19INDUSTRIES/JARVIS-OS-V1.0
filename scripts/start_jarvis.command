#!/usr/bin/env bash
# macOS / Linux launcher for JARVIS.
# Double-clickable on macOS; from a terminal: ./scripts/start_jarvis.command

set -e

# Move into the project root (the directory above scripts/).
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

# Prefer python3 from PATH.
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Create the venv on first run.
if [ ! -d ".venv" ]; then
  echo "[start_jarvis] Creating virtual environment in .venv (one-time)..."
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# Install / upgrade deps only if marker file is missing or requirements changed.
MARKER=".venv/.jarvis_requirements.sha256"
NEEDS_INSTALL=0
if [ ! -f "$MARKER" ]; then
  NEEDS_INSTALL=1
elif command -v sha256sum >/dev/null 2>&1; then
  CURRENT="$(sha256sum requirements.txt | awk '{print $1}')"
  STORED="$(cat "$MARKER" 2>/dev/null || true)"
  if [ "$CURRENT" != "$STORED" ]; then
    NEEDS_INSTALL=1
  fi
fi

if [ "$NEEDS_INSTALL" = "1" ]; then
  echo "[start_jarvis] Installing dependencies (one-time or requirements changed)..."
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum requirements.txt | awk '{print $1}' > "$MARKER"
  else
    touch "$MARKER"
  fi
fi

# Make sure .env exists.
if [ ! -f ".env" ]; then
  echo "[start_jarvis] No .env found — copying .env.example to .env."
  cp .env.example .env
  echo "[start_jarvis] Edit .env and set GEMINI_API_KEY, then run this script again."
  if [ "$(uname)" = "Darwin" ]; then
    open -e .env || open .env || true
  fi
  exit 0
fi

# Check that the key actually looks filled.
if grep -qE 'GEMINI_API_KEY\s*=\s*"?YOUR_GEMINI_API_KEY"?\s*$' .env; then
  echo "[start_jarvis] GEMINI_API_KEY still has the placeholder value."
  echo "[start_jarvis] Edit .env and replace YOUR_GEMINI_API_KEY with your real key."
  if [ "$(uname)" = "Darwin" ]; then
    open -e .env || open .env || true
  fi
  exit 0
fi

echo "[start_jarvis] Starting JARVIS through the canonical CLI..."
exec "$PROJECT_ROOT/scripts/jarvis" "$@"
