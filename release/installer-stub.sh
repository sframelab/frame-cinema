#!/bin/sh
# Frame Cinema @VERSION@ installer for Steam Frame (SteamOS, ARM64).
#
# Double-click in Desktop Mode (Dolphin: "Execute"), or run in a terminal:
#   sh FrameCinema-@VERSION@-installer.sh
# Installs for your user under ~/.local/share/frame-cinema (no sudo), checks
# prerequisites, and adds "Frame Cinema" with artwork to your Steam library.
# Steam is closed briefly while its library entry is written.
# Uninstall: python3 ~/.local/share/frame-cinema/app/manage.py uninstall
set -eu
umask 077
EXPECTED_SHA256=@SHA256@

# Double-clicked from a file manager: show progress in a terminal window.
if [ ! -t 1 ] && [ "${FRAME_CINEMA_INSTALLER_TERMINAL:-}" != 1 ]; then
  export FRAME_CINEMA_INSTALLER_TERMINAL=1
  for terminal in konsole xterm; do
    if command -v "$terminal" >/dev/null 2>&1; then
      if [ "$terminal" = konsole ]; then exec konsole --hold -e sh "$0" "$@"; fi
      exec xterm -hold -e sh "$0" "$@"
    fi
  done
fi

say() { printf '%s\n' "$*"; }
fail() {
  say "Frame Cinema was not installed: $*" >&2
  if command -v kdialog >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    kdialog --title "Frame Cinema" --error "Frame Cinema was not installed:\n$*" >/dev/null 2>&1 || true
  fi
  exit 1
}

case "$(uname -s)/$(uname -m)" in
  Linux/aarch64|Linux/arm64) ;;
  *) fail "this installer is for Steam Frame (SteamOS ARM64)." ;;
esac
[ "$(id -u)" -ne 0 ] || fail "run it as your normal user, without sudo."
command -v python3 >/dev/null 2>&1 || fail "Python 3 is missing."

work="$(mktemp -d "${TMPDIR:-/tmp}/frame-cinema-install.XXXXXX")"
trap 'rm -rf "$work"' EXIT INT TERM
start="$(awk '/^__FRAME_CINEMA_ARCHIVE__$/ { print NR + 1; exit 0 }' "$0")"
[ -n "$start" ] || fail "the installer file is damaged. Download it again."
say "Frame Cinema @VERSION@"
# The terminal can open behind the file manager; say on top that work started.
if command -v kdialog >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  kdialog --title "Frame Cinema" --passivepopup "Installing Frame Cinema @VERSION@. This takes a few minutes; Steam restarts at the end." 12 >/dev/null 2>&1 &
fi
say "Unpacking..."
tail -n +"$start" "$0" > "$work/frame-cinema.tar.gz"
actual="$(sha256sum "$work/frame-cinema.tar.gz" | cut -d' ' -f1)"
[ "$actual" = "$EXPECTED_SHA256" ] || fail "the download is incomplete or damaged. Download it again."
tar -xzf "$work/frame-cinema.tar.gz" -C "$work" install.py || fail "the installer file is damaged."
say "Installing (this checks prerequisites and prepares resources; a few minutes)..."
status=0
python3 "$work/install.py" install "$work/frame-cinema.tar.gz" --steam || status=$?
if [ "$status" -eq 0 ]; then
  say ""
  say "Frame Cinema is installed. In Gaming Mode, find it in your Steam library under Non-Steam."
  if command -v kdialog >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    kdialog --title "Frame Cinema" --msgbox "Frame Cinema @VERSION@ is installed.\nIn Gaming Mode, find it in your Steam library under Non-Steam." >/dev/null 2>&1 || true
  fi
  exit 0
fi
if [ "$status" -eq 3 ]; then
  # Installed, but Steam's library could not be updated (install.py printed why).
  say ""
  say "Frame Cinema is installed, but it could not be added to your Steam library."
  say "Run Install Frame Cinema again to retry. See the message above for the reason."
  if command -v kdialog >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    kdialog --title "Frame Cinema" --sorry "Frame Cinema @VERSION@ is installed, but it could not be added to your Steam library.\n\nRun Install Frame Cinema again to retry. The terminal window shows the reason." >/dev/null 2>&1 || true
  fi
  exit 3
fi
fail "see the messages above, and GETTING-STARTED.md for prerequisites."
__FRAME_CINEMA_ARCHIVE__
