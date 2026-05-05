#!/bin/bash
# paste-image.sh - take whatever image is on the clipboard, ship it to a
# claudefarm server via SCP, then type the resulting remote path into the
# focused window. Linux + macOS equivalent of paste-image.ps1.
#
# Workflow:
#   1. Take a screenshot (PrtSc / Cmd+Shift+4 / Spectacle / Flameshot - any
#      tool that puts the image on the clipboard).
#   2. Press the hotkey you bound to this script.
#   3. ~2 seconds later, "/data/dev/_paste/<timestamp>.png" appears in the
#      focused window (your Claude Code SSH session in tmux).
#   4. Hit Enter, ask Claude to look at it.
#
# Path is also copied to your clipboard as a fallback.
#
# Bind to a hotkey via your desktop environment's keyboard shortcuts:
#   GNOME: Settings -> Keyboard -> Custom Shortcuts
#   KDE:   System Settings -> Shortcuts -> Custom Shortcuts
#   i3:    bindsym Ctrl+Mod1+v exec ~/github/claudefarm/client/paste-image.sh
#
# Auto-detects X11 vs Wayland vs macOS and uses the appropriate clipboard /
# auto-type tool. Install requirements (one-time):
#   X11:     sudo apt install xclip xdotool      (or pacman / dnf equivalents)
#   Wayland: sudo apt install wl-clipboard wtype
#   macOS:   pbpaste + AppleScript ship with the OS, no install needed
#
# Override defaults via env vars:
#   PASTE_SERVER_HOST   default 192.168.50.62
#   PASTE_SERVER_USER   default root
#   PASTE_REMOTE_DIR    default /data/dev/_paste

set -u

SERVER_HOST="${PASTE_SERVER_HOST:-192.168.50.62}"
SERVER_USER="${PASTE_SERVER_USER:-root}"
REMOTE_DIR="${PASTE_REMOTE_DIR:-/data/dev/_paste}"

# ---- 1. detect platform + clipboard reader ---------------------------------

notify() {
    # Best-effort desktop notification, fall back to stderr
    if command -v notify-send >/dev/null 2>&1; then
        notify-send -a "claudefarm" "paste-image" "$1"
    elif command -v osascript >/dev/null 2>&1; then
        osascript -e "display notification \"$1\" with title \"claudefarm: paste-image\""
    fi
    printf "%s\n" "$1" >&2
}

uname_s="$(uname -s)"
case "$uname_s" in
    Darwin)
        PLATFORM=macos
        ;;
    Linux)
        if [ -n "${WAYLAND_DISPLAY:-}" ]; then
            PLATFORM=wayland
        elif [ -n "${DISPLAY:-}" ]; then
            PLATFORM=x11
        else
            notify "no DISPLAY or WAYLAND_DISPLAY - run from a graphical session"
            exit 1
        fi
        ;;
    *)
        notify "unsupported platform: $uname_s"
        exit 1
        ;;
esac

# ---- 2. pull image from clipboard to a temp file ---------------------------

TS="$(date +%Y%m%d-%H%M%S)-$RANDOM"
LOCAL_PATH="$(mktemp -d)/claude-paste-${TS}.png"

case "$PLATFORM" in
    x11)
        command -v xclip >/dev/null 2>&1 || { notify "xclip not installed (sudo apt install xclip)"; exit 1; }
        if ! xclip -selection clipboard -t image/png -o > "$LOCAL_PATH" 2>/dev/null; then
            notify "no image on the clipboard. Take a screenshot first."
            rm -f "$LOCAL_PATH"; exit 1
        fi
        ;;
    wayland)
        command -v wl-paste >/dev/null 2>&1 || { notify "wl-paste not installed (sudo apt install wl-clipboard)"; exit 1; }
        if ! wl-paste --type image/png > "$LOCAL_PATH" 2>/dev/null; then
            notify "no image on the clipboard. Take a screenshot first."
            rm -f "$LOCAL_PATH"; exit 1
        fi
        ;;
    macos)
        # macOS pbpaste doesn't natively support binary - use AppleScript
        # to dump clipboard image to file via NSPasteboard.
        if ! osascript - "$LOCAL_PATH" >/dev/null 2>&1 <<'OSA'
on run argv
    set outFile to POSIX file (item 1 of argv)
    try
        set imgData to the clipboard as «class PNGf»
        set f to open for access outFile with write permission
        set eof of f to 0
        write imgData to f
        close access f
    on error
        return 0
    end try
end run
OSA
        then
            :
        fi
        if [ ! -s "$LOCAL_PATH" ]; then
            notify "no image on the clipboard. Take a screenshot first (Cmd+Shift+4 + Ctrl)."
            rm -f "$LOCAL_PATH"; exit 1
        fi
        ;;
esac

# ---- 3. SCP to remote ------------------------------------------------------

REMOTE_PATH="$REMOTE_DIR/${TS}.png"

ssh -o BatchMode=yes "${SERVER_USER}@${SERVER_HOST}" "mkdir -p '$REMOTE_DIR'" >/dev/null 2>&1 || true

if ! scp -q -o BatchMode=yes "$LOCAL_PATH" "${SERVER_USER}@${SERVER_HOST}:$REMOTE_PATH" 2>/dev/null; then
    notify "SCP to ${SERVER_USER}@${SERVER_HOST} failed (key not authorised? host unreachable?)"
    rm -f "$LOCAL_PATH"
    exit 1
fi

rm -f "$LOCAL_PATH"
rmdir "$(dirname "$LOCAL_PATH")" 2>/dev/null || true

# ---- 4. hand the path back to the user ------------------------------------

# Clipboard fallback
case "$PLATFORM" in
    x11)
        printf "%s" "$REMOTE_PATH" | xclip -selection clipboard 2>/dev/null
        ;;
    wayland)
        printf "%s" "$REMOTE_PATH" | wl-copy 2>/dev/null
        ;;
    macos)
        printf "%s" "$REMOTE_PATH" | pbcopy 2>/dev/null
        ;;
esac

# Type into focused window
case "$PLATFORM" in
    x11)
        if command -v xdotool >/dev/null 2>&1; then
            xdotool type --delay 1 -- "$REMOTE_PATH"
        else
            notify "Install xdotool to auto-type. Path is on your clipboard - Ctrl+V to paste."
        fi
        ;;
    wayland)
        if command -v wtype >/dev/null 2>&1; then
            wtype -- "$REMOTE_PATH"
        elif command -v ydotool >/dev/null 2>&1; then
            ydotool type -- "$REMOTE_PATH"
        else
            notify "Install wtype or ydotool to auto-type. Path is on your clipboard - Ctrl+V to paste."
        fi
        ;;
    macos)
        # AppleScript can simulate keystrokes via System Events. Needs
        # Accessibility permission for whatever process is calling osascript.
        osascript -e "tell application \"System Events\" to keystroke \"$REMOTE_PATH\"" 2>/dev/null || \
            notify "auto-type failed (grant Accessibility to your terminal in System Settings). Path is on your clipboard."
        ;;
esac
