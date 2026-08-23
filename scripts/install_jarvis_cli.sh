#!/usr/bin/env bash
# Install the `jarvis` command for the current macOS/Linux user.
set -e

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
PROJECT_ROOT="$(cd -P "$(dirname "$SOURCE")/.." >/dev/null 2>&1 && pwd)"
INSTALL_DIR="${JARVIS_INSTALL_DIR:-$HOME/.local/bin}"
mkdir -p "$INSTALL_DIR"
ln -sfn "$PROJECT_ROOT/scripts/jarvis" "$INSTALL_DIR/jarvis"

PROFILE=""
if [ "$(basename "${SHELL:-}")" = "zsh" ]; then
  PROFILE="$HOME/.zprofile"
elif [ "$(basename "${SHELL:-}")" = "bash" ]; then
  PROFILE="$HOME/.bash_profile"
fi
if [ -n "$PROFILE" ] && ! grep -Fq 'JARVIS_INSTALL_DIR' "$PROFILE" 2>/dev/null; then
  if ! printf '\n# JARVIS CLI\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$PROFILE" 2>/dev/null; then
    echo "Could not update $PROFILE automatically; add $INSTALL_DIR to PATH manually."
  fi
fi

echo "Installed: $INSTALL_DIR/jarvis"
if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
  echo "Open a new terminal, or run: export PATH=\"$INSTALL_DIR:\$PATH\""
fi
echo "Then launch JARVIS with: jarvis"
