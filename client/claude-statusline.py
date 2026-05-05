#!/usr/bin/env python3
"""
Claude Code statusline for the local Windows desktop.

Mirrors the K12 statusline (Catppuccin Mocha + Nerd Font icons - same
fields, same icons) but adds the "Remote: On/Off" badge that the
@hoangvu12/claude-remote npm package's statusline.js shows. The badge
tells you whether the local Discord daemon is currently relaying THIS
session.

Wired in via C:\\Users\\cmoss\\.claude\\settings.json:
    "statusLine": {
      "type": "command",
      "command": "python \"C:\\Users\\cmoss\\github\\claudefarm\\client\\claude-statusline.py\""
    }

Receives session JSON on stdin from Claude Code, prints one line to stdout.

Catppuccin Mocha palette + Nerd Font icons. Without a Nerd Font in your
local terminal the icons render as boxes; the colours and layout still
work. Recommended on Windows:
    winget install Microsoft.CascadiaCode
then set Windows Terminal font to "Cascadia Code NF".
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Force UTF-8 stdout so the box-drawing chars and Nerd Font icons render
# regardless of locale. No-op when stdout is already UTF-8 (Linux default).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- Catppuccin Mocha (24-bit ANSI) ----------------------------------------

def fg(r: int, g: int, b: int) -> str:
    return f"\x1b[38;2;{r};{g};{b}m"

RESET     = "\x1b[0m"
BOLD      = "\x1b[1m"
DIM       = "\x1b[2m"

MAUVE     = fg(203, 166, 247)   # instance
SAPPHIRE  = fg(116, 199, 236)   # model
SKY       = fg(137, 220, 235)
TEAL      = fg(148, 226, 213)   # worktree
GREEN     = fg(166, 227, 161)
YELLOW    = fg(249, 226, 175)   # ctx warn / 5h warn
PEACH     = fg(250, 179, 135)   # cost
RED       = fg(243, 139, 168)   # ctx exceeds 200k
PINK      = fg(245, 194, 231)   # vim mode
SUBTEXT   = fg(166, 173, 200)   # default ctx
OVERLAY   = fg(108, 112, 134)   # separators / output style
SEP       = f"{OVERLAY}│{RESET}"   # │  vertical bar separator


def colour(text: str, *codes: str) -> str:
    return "".join(codes) + text + RESET


def remote_status() -> str | None:
    """
    Replicate @hoangvu12/claude-remote's "Remote: On/Off" badge.

    The package writes the daemon PID to ~/.claude-remote/active when its rc
    daemon starts. CLAUDE_REMOTE_PIPE is only set when running inside a
    session bound to that daemon - its name has the daemon's PID. If the
    env-var PID matches the file PID and that process is still alive, this
    session is being relayed.

    Returns None when not running under claude-remote at all.
    """
    pipe = os.environ.get("CLAUDE_REMOTE_PIPE")
    if not pipe:
        return None

    flag = Path.home() / ".claude-remote" / "active"
    rc_match = re.search(r"claude-remote-(\d+)$", pipe)
    rc_pid = int(rc_match.group(1)) if rc_match else None

    is_active = False
    try:
        flag_pid = int(flag.read_text().strip())
        if flag_pid and rc_pid and flag_pid == rc_pid:
            os.kill(flag_pid, 0)
            is_active = True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError, OSError):
        try:
            flag.unlink()
        except OSError:
            pass

    if is_active:
        return colour("● On", GREEN, BOLD)
    return colour("○ Off", OVERLAY)


def main() -> int:
    raw = sys.stdin.read()
    try:
        s = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        s = {}

    model       = (s.get("model") or {}).get("display_name") or "Claude"
    context     = (s.get("context_window") or {}).get("used_percentage") or 0
    cost        = (s.get("cost") or {}).get("total_cost_usd")
    exceeds200k = s.get("exceeds_200k_tokens") is True
    rate_5h     = (s.get("rate_limits") or {}).get("five_hour", {}).get("used_percentage")
    worktree    = (s.get("worktree") or {}).get("name")
    vim_mode    = (s.get("vim") or {}).get("mode")
    out_style   = (s.get("output_style") or {}).get("name")

    parts: list[str] = []

    # Model:  Sonnet 4.6
    parts.append(colour(f" {model}", SAPPHIRE, BOLD))

    # Context %:  45%
    ctx_pct = round(context)
    if exceeds200k:
        ctx_str = colour(f" {ctx_pct}% ctx!", RED, BOLD)
    elif ctx_pct >= 80:
        ctx_str = colour(f" {ctx_pct}% ctx", YELLOW)
    else:
        ctx_str = colour(f" {ctx_pct}%", SUBTEXT)
    parts.append(ctx_str)

    # Cost: $0.234
    if cost is not None:
        parts.append(colour(f" {cost:.3f}", PEACH))

    # 5-hour rate-limit warning (only when high)
    if rate_5h is not None and rate_5h >= 80:
        parts.append(colour(f" {round(rate_5h)}% 5h", YELLOW, BOLD))

    # Worktree (git):  branch
    if worktree:
        parts.append(colour(f" {worktree}", TEAL))

    # Vim mode (only when active)
    if vim_mode:
        parts.append(colour(vim_mode.upper(), PINK, BOLD))

    # Non-default output style (dim, parenthesised)
    if out_style and out_style != "default":
        parts.append(colour(f"({out_style})", OVERLAY))

    # Remote: On/Off (claude-remote daemon status, local-only)
    rs = remote_status()
    if rs is not None:
        parts.append(f"Remote: {rs}")

    sys.stdout.write(f" {SEP} ".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
