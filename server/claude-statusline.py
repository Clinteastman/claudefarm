#!/usr/bin/env python3
"""
Claude Code statusline for K12 instances.

Mirrors the @hoangvu12/claude-remote statusline used on the local desktop -
shows model, context %, cost, 5-hour rate-limit, worktree, vim mode, output
style - but replaces the "Remote: On/Off" badge (which is specific to that
npm package) with the K12 instance name from $CLAUDE_INSTANCE.

Wired in via /root/.claude/settings.json:
    "statusLine": {
      "type": "command",
      "command": "/usr/local/bin/claude-statusline"
    }

Receives session JSON on stdin from Claude Code, prints one line to stdout.

Catppuccin Mocha palette + Nerd Font icons. Without a Nerd Font the icons
render as boxes; the colours and layout still work.
"""
from __future__ import annotations

import json
import os
import platform
import sys

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


def host_badge() -> str:
    """Leftmost 'where am I?' anchor: OS icon + name, so the cloud farm (Linux)
    vs the Windows desktop is obvious at a glance. No network call."""
    system = platform.system()
    if system == "Windows":
        return colour(" Windows", SKY, BOLD)    # nf-fa-windows
    if system == "Darwin":
        return colour(" macOS", SUBTEXT, BOLD)  # nf-fa-apple
    return colour(" Linux", GREEN, BOLD)        # nf-fa-linux (Tux)


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
    instance    = os.environ.get("CLAUDE_INSTANCE") or os.environ.get("CLAUDE_NAME")

    parts: list[str] = []

    # Host (leftmost anchor): which machine am I on
    parts.append(host_badge())

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

    # Instance name (always last - "where am I?"):  cabin
    if instance:
        parts.append(colour(f" {instance}", MAUVE, BOLD))

    sys.stdout.write(f" {SEP} ".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
