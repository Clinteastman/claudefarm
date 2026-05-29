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

# ---- 2. detect what's on the clipboard + collect local files to upload -----

TS="$(date +%Y%m%d-%H%M%S)-$RANDOM"
TMPDIR_LOCAL="$(mktemp -d)"
LOCAL_FILES=()      # array of (local_path, remote_basename) pairs, flat

# Returns 0 if files on clipboard, fills LOCAL_FILES with originals.
collect_clipboard_files() {
    local uris
    case "$PLATFORM" in
        x11)
            uris="$(xclip -selection clipboard -t text/uri-list -o 2>/dev/null)" || return 1
            ;;
        wayland)
            uris="$(wl-paste --type text/uri-list 2>/dev/null)" || return 1
            ;;
        macos)
            uris="$(osascript -e 'try
                set theFiles to the clipboard as «class furl»
                if class of theFiles is list then
                    set out to ""
                    repeat with f in theFiles
                        set out to out & POSIX path of f & linefeed
                    end repeat
                    return out
                else
                    return POSIX path of theFiles
                end if
            on error
                return ""
            end try' 2>/dev/null)" || return 1
            ;;
    esac
    [ -z "$uris" ] && return 1
    local i=0
    while IFS= read -r line; do
        line="${line%$'\r'}"
        [ -z "$line" ] && continue
        local p="$line"
        # X11/Wayland give file:// URIs - strip the prefix + percent-decode
        # (the old code only handled %20, silently dropping %C3%A9, %2C, ...).
        case "$p" in
            file://*)
                p="${p#file://}"
                if command -v python3 >/dev/null 2>&1; then
                    p="$(printf '%s' "$p" | python3 -c 'import sys,urllib.parse as u; sys.stdout.write(u.unquote(sys.stdin.read()))')"
                else
                    p="$(printf '%s' "$p" | sed 's/%20/ /g')"
                fi
                ;;
        esac
        [ -f "$p" ] || continue   # skip directories
        i=$((i + 1))
        # Strip anything outside a safe charset from the remote basename so it
        # can't inject into the scp remote path (legacy-rcp CVE-2020-15778 class).
        LOCAL_FILES+=("$p" "${TS}-${i}-$(basename "$p" | tr -dc 'A-Za-z0-9._-')")
    done <<<"$uris"
    [ "${#LOCAL_FILES[@]}" -gt 0 ]
}

# Returns 0 if image collected, queues a temp PNG in LOCAL_FILES.
collect_clipboard_image() {
    local png="$TMPDIR_LOCAL/claude-paste-${TS}.png"
    case "$PLATFORM" in
        x11)
            xclip -selection clipboard -t image/png -o > "$png" 2>/dev/null && [ -s "$png" ] || return 1
            ;;
        wayland)
            wl-paste --type image/png > "$png" 2>/dev/null && [ -s "$png" ] || return 1
            ;;
        macos)
            osascript - "$png" <<'OSA' >/dev/null 2>&1
on run argv
    set outFile to POSIX file (item 1 of argv)
    try
        set imgData to the clipboard as «class PNGf»
        set f to open for access outFile with write permission
        set eof of f to 0
        write imgData to f
        close access f
    end try
end run
OSA
            [ -s "$png" ] || return 1
            ;;
    esac
    LOCAL_FILES+=("$png" "${TS}.png")
}

if ! collect_clipboard_files; then
    if ! collect_clipboard_image; then
        notify "Nothing on the clipboard. Take a screenshot OR copy a file in your file manager first."
        rm -rf "$TMPDIR_LOCAL"
        exit 1
    fi
fi

# ---- 3. SCP each to remote -------------------------------------------------

ssh -o BatchMode=yes "${SERVER_USER}@${SERVER_HOST}" "mkdir -p '$REMOTE_DIR'" >/dev/null 2>&1 || true

REMOTE_PATHS=()
i=0
while [ "$i" -lt "${#LOCAL_FILES[@]}" ]; do
    src="${LOCAL_FILES[$i]}"
    name="${LOCAL_FILES[$((i + 1))]}"
    dst="$REMOTE_DIR/$name"
    if ! scp -q -o BatchMode=yes "$src" "${SERVER_USER}@${SERVER_HOST}:$dst" 2>/dev/null; then
        notify "SCP failed for $src to ${SERVER_USER}@${SERVER_HOST} (key not authorised? host unreachable?)"
        rm -rf "$TMPDIR_LOCAL"
        exit 1
    fi
    REMOTE_PATHS+=("$dst")
    i=$((i + 2))
done

rm -rf "$TMPDIR_LOCAL"

# Single string for typing / clipboard - space-joined
REMOTE_PATH="${REMOTE_PATHS[*]}"

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
