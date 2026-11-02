#!/usr/bin/env bash
#
# WehniX CLI installer.
#
# Drops a `WehniX` command into ~/.local/bin (no sudo needed) and keeps the
# package inside its own virtualenv, so it never touches your system Python or
# the WehniX desktop app's data.
#
#   curl -fsSL https://raw.githubusercontent.com/wehnnit/WehniX-CLI/main/scripts/install.sh | bash
#
set -euo pipefail

REPO_URL="https://github.com/wehnnit/WehniX-CLI.git"
BIN_DIR="${HOME}/.local/bin"
VENV_DIR="${HOME}/.local/share/wehniX-cli"

if ! command -v python3 >/dev/null 2>&1; then
  echo "WehniX CLI needs python3 (3.9+). Install it from python.org or Homebrew." >&2
  exit 1
fi

mkdir -p "$BIN_DIR" "$VENV_DIR"

# Create / refresh the isolated environment.
if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "Creating an isolated environment in $VENV_DIR …"
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install -q --upgrade pip >/dev/null
echo "Installing WehniX CLI …"
"$VENV_DIR/bin/python" -m pip install -q --upgrade "$REPO_URL" >/dev/null

# The launcher is a tiny wrapper that runs the module inside the venv. Naming it
# once per spelling keeps `WehniX`, `wehniX`, `wehnix` and `Wehnix` all working.
LAUNCHER="$BIN_DIR/wehniX-cli"
cat > "$LAUNCHER" <<'EOF'
#!/bin/sh
exec "$HOME/.local/share/wehniX-cli/bin/python" -m wehnix_cli "$@"
EOF
chmod +x "$LAUNCHER"

# How many spellings can this filesystem actually tell apart?
case_sensitive=0
if printf 'x' > "$BIN_DIR/.wehniX-case-A" 2>/dev/null && printf 'x' > "$BIN_DIR/.wehniX-case-a" 2>/dev/null; then
  case_sensitive=1
fi
rm -f "$BIN_DIR/.wehniX-case-A" "$BIN_DIR/.wehniX-case-a" 2>/dev/null || true

if [ "$case_sensitive" -eq 1 ]; then
  for name in WehniX wehniX wehnix Wehnix; do
    ln -sf "$LAUNCHER" "$BIN_DIR/$name"
  done
else
  # Case-insensitive volume: one name resolves every spelling.
  ln -sf "$LAUNCHER" "$BIN_DIR/WehniX"
fi

# Make sure ~/.local/bin is on PATH for the common macOS shells.
shell_rc=""
case "${SHELL:-}" in
  */zsh)  shell_rc="${HOME}/.zshrc" ;;
  */bash) shell_rc="${HOME}/.bashrc" ;;
esac
if [ -n "$shell_rc" ] && [ -f "$shell_rc" ] && ! grep -q '\.local/bin' "$shell_rc" 2>/dev/null; then
  printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$shell_rc"
  echo "Added ~/.local/bin to PATH in $shell_rc (restart your terminal)."
fi

if command -v WehniX >/dev/null 2>&1; then
  echo "WehniX CLI is installed. Start it with:  WehniX"
else
  echo "Installed into $BIN_DIR. Make sure it is on your PATH, then run:  WehniX"
fi
