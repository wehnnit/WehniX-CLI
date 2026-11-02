#!/usr/bin/env bash
#
# WehniX CLI uninstaller.
#
#   scripts/uninstall.sh                 remove the CLI, keep your bottles
#   scripts/uninstall.sh --all-data      remove the CLI and all WehniX data
#   scripts/uninstall.sh --pip           also run pip uninstall wehnix-cli
#   scripts/uninstall.sh --clean-path    drop the installer's PATH line
#   scripts/uninstall.sh --yes           do not ask for confirmation
#
# Every path is printed before it is removed, and the result is verified at the
# end. Running it twice is harmless: a missing path is reported as "absent".
set -uo pipefail

ALL_DATA=0
PIP_CLEAN=0
CLEAN_PATH=0
ASSUME_YES=0

usage() {
  cat <<'USAGE'
Remove WehniX CLI from this Mac.

  scripts/uninstall.sh              remove the CLI, keep bottles and settings
  scripts/uninstall.sh --all-data   also delete the shared WehniX data folder
  scripts/uninstall.sh --pip        also run: python3 -m pip uninstall -y wehnix-cli
  scripts/uninstall.sh --clean-path remove the installer's PATH line from your shell rc
  scripts/uninstall.sh --yes        do not ask for confirmation

Without --all-data, ~/Library/Application Support/WehniX is left untouched.
USAGE
}

for argument in "$@"; do
  case "$argument" in
    --all-data) ALL_DATA=1 ;;
    --pip) PIP_CLEAN=1 ;;
    --clean-path) CLEAN_PATH=1 ;;
    -y|--yes) ASSUME_YES=1 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $argument" >&2
      usage >&2
      exit 64
      ;;
  esac
done

if [ -z "${HOME:-}" ]; then
  echo "HOME is not set; nothing was changed." >&2
  exit 64
fi

HOME_DIR="$HOME"
DATA_DIR="${HOME_DIR}/Library/Application Support/WehniX"
CLI_DIR="${DATA_DIR}/cli"
SHARE_DIR="${HOME_DIR}/.local/share/wehniX-cli"
BIN_DIR="${HOME_DIR}/.local/bin"
DEMO_DIR="${HOME_DIR}/.cache/wehniX-cli-demo"
LAUNCHERS="wehniX-cli wehniX WehniX wehnix Wehnix"

case "$DATA_DIR" in
  "/"|"${HOME_DIR}"|"")
    echo "Refusing to touch an unsafe path: ${DATA_DIR}" >&2
    exit 1
    ;;
esac

FAILED=0

remove() {
  target="$1"
  if [ -e "$target" ] || [ -L "$target" ]; then
    rm -rf "$target"
    if [ -e "$target" ] || [ -L "$target" ]; then
      printf '  FAILED   %s\n' "$target" >&2
      FAILED=1
    else
      printf '  removed  %s\n' "$target"
    fi
  else
    printf '  absent   %s\n' "$target"
  fi
}

echo "WehniX CLI uninstall"
printf '  home  %s\n' "$HOME_DIR"
if [ "$ALL_DATA" -eq 1 ]; then
  echo "  mode  remove the CLI and all WehniX data"
else
  echo "  mode  remove the CLI, keep your bottles"
fi

if [ "$ALL_DATA" -eq 1 ] && [ "$ASSUME_YES" -eq 0 ]; then
  if [ -t 0 ]; then
    echo
    echo "This deletes ${DATA_DIR}:"
    echo "every bottle, engine archive, game inside a bottle, setting and log."
    printf 'Type delete to continue: '
    read -r answer
    if [ "$answer" != "delete" ]; then
      echo "Nothing was changed."
      exit 1
    fi
  else
    echo "Refusing to delete the app data without --yes in a non-interactive shell." >&2
    exit 1
  fi
fi

if command -v pgrep >/dev/null 2>&1 && pgrep -x WehniX >/dev/null 2>&1; then
  echo
  echo "Note: WehniX is running. Quit it before opening a new terminal."
fi

echo
echo "Package"
if [ "$PIP_CLEAN" -eq 1 ]; then
  if command -v python3 >/dev/null 2>&1; then
    python3 -m pip uninstall -y wehnix-cli >/dev/null 2>&1
    echo "  checked  python3 -m pip uninstall -y wehnix-cli"
  else
    echo "  skipped  python3 is not available"
  fi
else
  echo "  skipped  pip installs stay; add --pip to remove one"
fi

echo
echo "Launchers"
for name in $LAUNCHERS; do
  remove "${BIN_DIR}/${name}"
done

echo
echo "Runtime"
remove "$SHARE_DIR"
remove "$DEMO_DIR"

echo
if [ "$ALL_DATA" -eq 1 ]; then
  echo "Application data"
  remove "$DATA_DIR"
else
  echo "CLI files inside the application data"
  remove "$CLI_DIR"
  if [ -e "$DATA_DIR" ]; then
    printf '  kept     %s\n' "$DATA_DIR"
  else
    printf '  absent   %s\n' "$DATA_DIR"
  fi
fi

if [ "$CLEAN_PATH" -eq 1 ]; then
  echo
  echo "PATH"
  for rc in "${HOME_DIR}/.zshrc" "${HOME_DIR}/.bashrc"; do
    if [ ! -f "$rc" ]; then
      printf '  absent   %s\n' "$rc"
      continue
    fi
    if grep -q 'export PATH="\$HOME/\.local/bin:\$PATH"' "$rc" 2>/dev/null; then
      cp "$rc" "${rc}.bak"
      sed '/export PATH="\$HOME\/\.local\/bin:\$PATH"/d' "${rc}.bak" > "$rc"
      rm -f "${rc}.bak"
      printf '  removed  PATH line from %s\n' "$rc"
    else
      printf '  absent   PATH line in %s\n' "$rc"
    fi
  done
fi

echo
echo "Check"
LEFTOVER=0
for path in "$SHARE_DIR" "$CLI_DIR" "$DEMO_DIR"; do
  if [ -e "$path" ] || [ -L "$path" ]; then
    printf '  still present  %s\n' "$path" >&2
    LEFTOVER=1
  fi
done
for name in $LAUNCHERS; do
  if [ -e "${BIN_DIR}/${name}" ] || [ -L "${BIN_DIR}/${name}" ]; then
    printf '  still present  %s\n' "${BIN_DIR}/${name}" >&2
    LEFTOVER=1
  fi
done
if [ "$ALL_DATA" -eq 1 ]; then
  if [ -e "$DATA_DIR" ]; then
    printf '  still present  %s\n' "$DATA_DIR" >&2
    LEFTOVER=1
  fi
elif [ -e "$DATA_DIR" ]; then
  printf '  kept           %s\n' "$DATA_DIR"
fi

echo
if [ "$FAILED" -eq 1 ] || [ "$LEFTOVER" -eq 1 ]; then
  echo "Some paths could not be removed. Nothing else was touched." >&2
  exit 1
fi
echo "Done. Open a new terminal so the old one forgets the launcher."
exit 0
