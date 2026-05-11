#!/usr/bin/env python3
"""
claude-mgr: Catppuccin Mocha TUI + CLI to manage Claude Code instances.

Each instance is one `claude-remote@<name>.service` systemd unit, owning its
own tmux session (claude-<name>), its own claude.ai Remote Control URL via
Telegram, and optionally its own working directory via a CLAUDE_WORKDIR
drop-in.

Dependencies (auto-installed by bootstrap.sh):
    pip install rich questionary

USAGE:
  claude-mgr               # interactive TUI
  claude-mgr list          # plain text list of instances
  claude-mgr start <name>  # start an instance (creates if needed, defaults to /root)
  claude-mgr start <name> --workdir /path
  claude-mgr start <name> --clone https://github.com/user/repo.git
  claude-mgr stop <name>
  claude-mgr restart <name>
  claude-mgr attach <name>
  claude-mgr url <name>
  claude-mgr remove <name>
  claude-mgr remove <name> --purge-workdir
  claude-mgr sync-ssh

SSH ALIAS SYNC:
  start/stop/remove auto-update {repo}/client/claude-instances-<host>.cfg
  with the current set of instances. Clients Include that glob from their
  ~/.ssh/config to get auto-updated `ssh claude-<host>-<instance>` aliases.
  After the file changes, commit + push and have clients `git pull` to
  receive the new aliases.

  Set CLAUDEFARM_REPO env var to override the default repo path
  (default: /data/dev/claudefarm).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---- third-party (rich + questionary) ----------------------------------------
# Bail with a clear message if the deps aren't installed yet.
try:
    from rich.console import Console, Group
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.theme import Theme
    from rich.box import ROUNDED, HEAVY
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.align import Align
    from rich.padding import Padding
    from rich.rule import Rule
    import questionary
    from questionary import Style as QStyle
    from prompt_toolkit.formatted_text import HTML
except ImportError as e:
    sys.stderr.write(
        f"claude-mgr: missing dependency {e.name!r}.\n"
        "Install with:  pip3 install rich questionary  (or re-run bootstrap.sh)\n"
    )
    sys.exit(1)

# ---- config ------------------------------------------------------------------

DEV_ROOT = Path("/data/dev")
DROPIN_DIR = Path("/etc/systemd/system")
DEFAULT_WORKDIR = "/root"
FARM_REPO = Path(os.environ.get("CLAUDEFARM_REPO", "/data/dev/claudefarm"))
SSH_TARGET_HOST = os.environ.get("CLAUDE_MGR_LAN_IP", "192.168.50.62")
SSH_TARGET_USER = os.environ.get("CLAUDE_MGR_SSH_USER", "root")
RESTART_HOST = os.environ.get("CLAUDE_MGR_RESTART_HOST", "192.168.50.55")
RESTART_VIA = os.environ.get("CLAUDE_MGR_RESTART_VIA", "pct exec 105 --")
HOSTNAME_TAG = os.environ.get("CLAUDE_MGR_HOSTNAME", os.uname().nodename.split(".")[0])

# ---- Catppuccin Mocha palette ------------------------------------------------

C_BG       = "#1e1e2e"
C_FG       = "#cdd6f4"
C_SUBTEXT  = "#a6adc8"
C_OVERLAY  = "#6c7086"
C_SURFACE1 = "#45475a"
C_BLUE     = "#89b4fa"
C_LAVENDER = "#b4befe"
C_SAPPHIRE = "#74c7ec"
C_SKY      = "#89dceb"
C_TEAL     = "#94e2d5"
C_GREEN    = "#a6e3a1"
C_YELLOW   = "#f9e2af"
C_PEACH    = "#fab387"
C_RED      = "#f38ba8"
C_MAUVE    = "#cba6f7"
C_PINK     = "#f5c2e7"

CAT_THEME = Theme({
    "ok":         f"bold {C_GREEN}",
    "warn":       f"bold {C_YELLOW}",
    "err":        f"bold {C_RED}",
    "info":       f"{C_SAPPHIRE}",
    "muted":      f"{C_OVERLAY}",
    "name":       f"bold {C_MAUVE}",
    "value":      f"{C_FG}",
    "url":        f"{C_SAPPHIRE} underline",
    "host":       f"bold {C_LAVENDER}",
    "instance":   f"bold {C_MAUVE}",
    "title":      f"bold {C_PINK}",
    "panel.border": f"{C_MAUVE}",
})

console = Console(theme=CAT_THEME, highlight=False)

# Catppuccin theme for questionary prompts
QSTYLE = QStyle([
    ("qmark",        f"fg:{C_MAUVE} bold"),
    ("question",     f"fg:{C_FG} bold"),
    ("answer",       f"fg:{C_GREEN} bold"),
    ("pointer",      f"fg:{C_PINK} bold"),
    ("highlighted",  f"fg:{C_PINK} bold"),
    ("selected",     f"fg:{C_GREEN}"),
    ("separator",    f"fg:{C_OVERLAY}"),
    ("instruction",  f"fg:{C_OVERLAY} italic"),
    ("text",         f"fg:{C_FG}"),
    ("disabled",     f"fg:{C_OVERLAY} italic"),
])

# ---- Nerd Font icons (defined as chr() so source survives any wobble) -------

ICON_DOT_ON      = chr(0xF111)   # nf-fa-circle (filled)
ICON_DOT_OFF     = chr(0xF10C)   # nf-fa-circle_o (outline)
ICON_TMUX        = chr(0xF120)   # nf-fa-terminal
ICON_FOLDER      = chr(0xF07B)   # nf-fa-folder
ICON_LINK        = chr(0xF0C1)   # nf-fa-link
ICON_PLAY        = chr(0xF04B)   # nf-fa-play
ICON_STOP        = chr(0xF04D)   # nf-fa-stop
ICON_REFRESH     = chr(0xF021)   # nf-fa-refresh
ICON_TRASH       = chr(0xF1F8)   # nf-fa-trash
ICON_PLUS        = chr(0xF067)   # nf-fa-plus
ICON_BACK        = chr(0xF112)   # nf-fa-reply
ICON_CHECK       = chr(0xF00C)   # nf-fa-check
ICON_CROSS       = chr(0xF00D)   # nf-fa-times
ICON_SERVER      = chr(0xF233)   # nf-fa-server
ICON_CUBE        = chr(0xF1B2)   # nf-fa-cube
ICON_INFO        = chr(0xF05A)   # nf-fa-info_circle
ICON_WARN        = chr(0xF071)   # nf-fa-exclamation_triangle
ICON_GIT         = chr(0xE702)   # nf-dev-git

# ---- shell helpers -----------------------------------------------------------

def run(cmd: list[str], check: bool = False, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)

def systemctl(*args: str) -> subprocess.CompletedProcess:
    return run(["systemctl", *args])

def tmux(*args: str) -> subprocess.CompletedProcess:
    return run(["tmux", *args])

# ---- instance discovery ------------------------------------------------------

INSTANCE_RE = re.compile(r"^claude-remote@([a-zA-Z0-9_-]+)\.service$")

def list_instances() -> list[dict]:
    out = run(["systemctl", "list-unit-files", "claude-remote@*.service",
               "--no-pager", "--no-legend"]).stdout.strip().splitlines()
    enabled_units = {ln.split()[0]: ln.split()[1] for ln in out if ln.strip()}

    # systemctl list-units columns: UNIT  LOAD  ACTIVE  SUB  DESCRIPTION
    out2 = run(["systemctl", "list-units", "claude-remote@*.service",
                "--all", "--no-pager", "--no-legend"]).stdout.strip().splitlines()
    states = {}
    for ln in out2:
        parts = ln.split(None, 4)
        if len(parts) >= 4:
            states[parts[0]] = (parts[2], parts[3])  # (active_state, sub_state)

    seen = set(enabled_units.keys()) | set(states.keys())
    out3 = run(["tmux", "list-sessions", "-F", "#{session_name}"]).stdout.strip().splitlines()
    tmux_sessions = set(out3) if out3 else set()

    insts = []
    for unit in sorted(seen):
        m = INSTANCE_RE.match(unit)
        if not m:
            continue
        name = m.group(1)
        active, sub = states.get(unit, ("inactive", "dead"))
        enabled = enabled_units.get(unit, "disabled")
        tmux_alive = f"claude-{name}" in tmux_sessions
        workdir = read_workdir(name)
        url = last_url(name)
        mode = read_mode(name)
        insts.append({
            "name": name, "unit": unit, "active": active, "sub": sub,
            "enabled": enabled, "tmux_alive": tmux_alive,
            "workdir": workdir, "url": url, "mode": mode,
        })
    return insts


def read_workdir(name: str) -> str:
    dropin = DROPIN_DIR / f"claude-remote@{name}.service.d" / "workdir.conf"
    if dropin.exists():
        for ln in dropin.read_text().splitlines():
            if ln.startswith("Environment=CLAUDE_WORKDIR="):
                return ln.split("=", 2)[2].strip()
    return DEFAULT_WORKDIR


def read_mode(name: str) -> str:
    """Returns "code" (default) or "agents". Stored as the mode.conf
    drop-in alongside workdir.conf; absence = code mode."""
    dropin = DROPIN_DIR / f"claude-remote@{name}.service.d" / "mode.conf"
    if dropin.exists():
        for ln in dropin.read_text().splitlines():
            if ln.startswith("Environment=CLAUDE_MODE="):
                v = ln.split("=", 2)[2].strip().strip('"')
                if v in ("code", "agents"):
                    return v
    return "code"


def last_url(name: str) -> str | None:
    out = run(["journalctl", "-u", f"claude-remote@{name}.service",
               "--no-pager", "-n", "200"]).stdout
    m = list(re.finditer(r"https://claude\.ai[a-zA-Z0-9./_?=&%+-]+", out))
    return m[-1].group(0) if m else None

# ---- instance lifecycle ------------------------------------------------------

def write_workdir_dropin(name: str, workdir: str) -> None:
    d = DROPIN_DIR / f"claude-remote@{name}.service.d"
    d.mkdir(parents=True, exist_ok=True)
    (d / "workdir.conf").write_text(
        f"[Service]\nEnvironment=CLAUDE_WORKDIR={workdir}\n"
    )
    systemctl("daemon-reload")


def write_mode_dropin(name: str, mode: str) -> None:
    """Persists the per-instance mode (code | agents) via a systemd
    drop-in alongside workdir.conf. Default mode = code; we only write
    the drop-in for non-default values so the absence of a file means
    'code mode'."""
    d = DROPIN_DIR / f"claude-remote@{name}.service.d"
    f = d / "mode.conf"
    if mode == "code":
        if f.exists():
            f.unlink()
            # If the dropin dir is now empty, prune it too
            try:
                d.rmdir()
            except OSError:
                pass
    else:
        d.mkdir(parents=True, exist_ok=True)
        f.write_text(f'[Service]\nEnvironment="CLAUDE_MODE={mode}"\n')
    systemctl("daemon-reload")


def remove_dropin(name: str) -> None:
    d = DROPIN_DIR / f"claude-remote@{name}.service.d"
    if d.exists():
        for f in d.iterdir():
            f.unlink()
        d.rmdir()
    systemctl("daemon-reload")


def ensure_venv(workdir: str) -> str | None:
    """
    Create <workdir>/.venv if it doesn't exist (uv preferred, python3 -m venv
    fallback). Returns a status message, or None if venv creation was skipped
    (default workdir is /root which we leave alone).
    """
    if Path(workdir).resolve() == Path(DEFAULT_WORKDIR).resolve():
        return None
    venv = Path(workdir) / ".venv"
    if venv.is_dir():
        return f"venv exists at {venv}"
    Path(workdir).mkdir(parents=True, exist_ok=True)
    if shutil.which("uv"):
        r = run(["uv", "venv", "--quiet", str(venv)])
    else:
        r = run(["python3", "-m", "venv", str(venv)])
    if r.returncode != 0:
        return f"venv creation FAILED: {r.stderr.strip()}"
    return f"created venv at {venv}"


def start_instance(name: str, workdir: str = DEFAULT_WORKDIR,
                   clone_url: str | None = None,
                   create_venv: bool = True,
                   mode: str = "code") -> tuple[bool, str]:
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
        return False, f"invalid name '{name}': lowercase letters, digits, _, - only"

    if clone_url:
        if workdir == DEFAULT_WORKDIR:
            workdir = str(DEV_ROOT / name)
        if Path(workdir).exists() and any(Path(workdir).iterdir()):
            return False, f"target dir {workdir} exists and is not empty"
        Path(workdir).parent.mkdir(parents=True, exist_ok=True)
        r = run(["git", "clone", clone_url, workdir])
        if r.returncode != 0:
            return False, f"git clone failed: {r.stderr.strip()}"

    Path(workdir).mkdir(parents=True, exist_ok=True)

    venv_msg = ensure_venv(workdir) if create_venv else None

    if workdir != DEFAULT_WORKDIR:
        write_workdir_dropin(name, workdir)
    # Always write/clear mode dropin so toggling between code <-> agents works
    write_mode_dropin(name, mode)

    systemctl("enable", f"claude-remote@{name}.service")
    r = systemctl("restart", f"claude-remote@{name}.service")
    if r.returncode != 0:
        return False, f"systemctl restart failed: {r.stderr.strip()}"
    sync_ssh()
    msg = f"started claude-remote@{name} (mode={mode}, workdir={workdir})"
    if venv_msg:
        msg += f"\n  {venv_msg}"
    return True, msg


def has_venv(workdir: str) -> bool:
    return (Path(workdir) / ".venv" / "bin" / "activate").is_file()


def add_venv(name: str) -> tuple[bool, str]:
    """Create .venv in this instance's workdir if it doesn't already have one."""
    workdir = read_workdir(name)
    if Path(workdir).resolve() == Path(DEFAULT_WORKDIR).resolve():
        return False, f"instance '{name}' uses {DEFAULT_WORKDIR} - venv would clutter root, skipping"
    if has_venv(workdir):
        return False, f"instance '{name}' already has a venv at {workdir}/.venv"
    msg = ensure_venv(workdir)
    return msg is not None and "FAILED" not in (msg or ""), msg or "no venv created"


def clean_venv(name: str) -> tuple[bool, str]:
    """Nuke + recreate <workdir>/.venv for an instance (e.g. when deps got
    wedged). Doesn't restart the instance - shells launched after will pick up
    the fresh venv on their next activation."""
    workdir = read_workdir(name)
    if Path(workdir).resolve() == Path(DEFAULT_WORKDIR).resolve():
        return False, f"instance '{name}' uses {DEFAULT_WORKDIR} - no venv to clean"
    venv = Path(workdir) / ".venv"
    if venv.is_dir():
        shutil.rmtree(venv)
    msg = ensure_venv(workdir)
    return True, f"cleaned venv for {name}: {msg}"


def purge_venv(name: str) -> tuple[bool, str]:
    """Delete <workdir>/.venv with no replacement - the instance will fall
    back to system Python on next restart. Use when you want to opt this
    instance OUT of having its own venv."""
    workdir = read_workdir(name)
    venv = Path(workdir) / ".venv"
    if not venv.is_dir():
        return False, f"no venv at {venv} - nothing to purge"
    shutil.rmtree(venv)
    return True, f"purged {venv} (instance will use system Python on next restart)"


def stop_instance(name: str) -> tuple[bool, str]:
    r = systemctl("stop", f"claude-remote@{name}.service")
    return r.returncode == 0, r.stderr.strip() or "stopped"


def restart_instance(name: str) -> tuple[bool, str]:
    r = systemctl("restart", f"claude-remote@{name}.service")
    return r.returncode == 0, r.stderr.strip() or "restarted"


def remove_instance(name: str, purge_workdir: bool = False) -> tuple[bool, str]:
    workdir = read_workdir(name)
    systemctl("stop", f"claude-remote@{name}.service")
    systemctl("disable", f"claude-remote@{name}.service")
    remove_dropin(name)
    msg = f"removed claude-remote@{name} (drop-in cleaned)"
    if purge_workdir and workdir != DEFAULT_WORKDIR and Path(workdir).is_dir():
        shutil.rmtree(workdir)
        msg += f" + purged {workdir}"
    sync_ssh()
    return True, msg

# ---- SSH alias sync ---------------------------------------------------------

def sync_ssh() -> tuple[bool, str]:
    if not FARM_REPO.is_dir():
        return False, f"homelab repo not found at {FARM_REPO} (set CLAUDEFARM_REPO env var)"
    out = FARM_REPO / "client" / f"claude-instances-{HOSTNAME_TAG}.cfg"
    out.parent.mkdir(parents=True, exist_ok=True)

    insts = list_instances()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"# AUTO-GENERATED by `claude-mgr sync-ssh` on {HOSTNAME_TAG} at {timestamp}",
        "# DO NOT edit manually - changes will be overwritten on the next instance create/remove.",
        "#",
        "# Desktop ~/.ssh/config Include line (set once):",
        f"#   Include {out.parent}/claude-instances-*.cfg",
        "",
    ]

    if not insts:
        lines.append(f"# (no Claude instances currently exist on {HOSTNAME_TAG})")
    else:
        lines.append(f"# === attach aliases for {HOSTNAME_TAG} ===")
        lines.append("")
        for i in insts:
            name = i["name"]
            lines += [
                f"Host claude-{HOSTNAME_TAG}-{name}",
                f"  HostName {SSH_TARGET_HOST}",
                f"  User {SSH_TARGET_USER}",
                f"  RequestTTY yes",
                f'  RemoteCommand tmux attach -t claude-{name} || (echo "claude-{name} tmux session not running on {HOSTNAME_TAG}"; exit 1)',
                "",
            ]

        lines.append(f"# === restart aliases for {HOSTNAME_TAG} ===")
        lines.append("")
        for i in insts:
            name = i["name"]
            lines += [
                f"Host claude-restart-{HOSTNAME_TAG}-{name}",
                f"  HostName {RESTART_HOST}",
                f"  User root",
                f"  RequestTTY no",
                f'  RemoteCommand {RESTART_VIA} systemctl restart claude-remote@{name}.service && echo "claude {name} on {HOSTNAME_TAG} restarted; check Telegram"',
                "",
            ]

    out.write_text("\n".join(lines))
    return True, f"wrote {out} ({len(insts)} instances)"

# ---- TUI rendering -----------------------------------------------------------

def state_icon(i: dict) -> Text:
    if i["active"] == "active" and i["sub"] == "running" and i["tmux_alive"]:
        return Text(f"{ICON_DOT_ON}", style=C_GREEN)
    if i["active"] == "active":
        return Text(f"{ICON_DOT_ON}", style=C_YELLOW)
    if i["active"] == "activating":
        return Text(f"{ICON_DOT_ON}", style=C_PEACH)
    if i["active"] == "failed":
        return Text(f"{ICON_DOT_ON}", style=C_RED)
    return Text(f"{ICON_DOT_OFF}", style=C_OVERLAY)


def panel_width() -> int:
    """Cap at 130 cols, but leave at least 4 cols of breathing room either side."""
    w = console.size.width
    return min(130, max(60, w - 8))


def render_header() -> Text:
    title = Text(justify="center")
    title.append(f"{ICON_SERVER} ", style=C_LAVENDER)
    title.append("claude-mgr", style="title")
    title.append("  on  ", style="muted")
    title.append(HOSTNAME_TAG, style="host")
    return title


def render_footer(hint: str) -> Text:
    return Text(hint, justify="center", style="muted")


def render_screen(body, footer_hint: str | None = None) -> Panel:
    """Wrap a body renderable in the header / body / footer Panel layout."""
    parts = [render_header(), Rule(style=C_SURFACE1), body]
    if footer_hint:
        parts.append(Rule(style=C_SURFACE1))
        parts.append(render_footer(footer_hint))
    return Panel(
        Group(*parts),
        border_style=C_MAUVE,
        box=ROUNDED,
        padding=(1, 2),
        width=panel_width(),
    )


def print_centered(panel: Panel):
    """Print a panel horizontally + vertically centred in the terminal."""
    # Estimate panel height by rendering to a string buffer of matching width
    from io import StringIO
    from rich.console import Console as _C
    tmp = _C(file=StringIO(), width=panel.width or panel_width(),
             force_terminal=True, color_system=None)
    with tmp.capture() as cap:
        tmp.print(panel)
    rendered_lines = max(1, cap.get().count("\n"))
    top_pad = max(0, (console.size.height - rendered_lines) // 2)
    if top_pad:
        console.print("\n" * top_pad, end="")
    console.print(Align.center(panel))


# ---- Custom menu (renders INSIDE the panel) --------------------------------

def _read_key() -> str:
    """Read a single keypress. Returns 'up' / 'down' / 'enter' / 'esc' / a char."""
    if sys.platform == "win32":
        import msvcrt
        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            ch2 = msvcrt.getch()
            return {b"H": "up", b"P": "down", b"M": "right", b"K": "left"}.get(ch2, "")
        if ch == b"\r":
            return "enter"
        if ch == b"\x1b":
            return "esc"
        try:
            return ch.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            return {"[A": "up", "[B": "down", "[C": "right", "[D": "left"}.get(seq, "esc")
        if ch in ("\r", "\n"):
            return "enter"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def select_in_box(
    body_above_menu,
    options: list[tuple[str, object]],
    footer_hint: str = "↑↓ to navigate, enter to choose, q to quit",
):
    """
    Render `body_above_menu` (e.g. a table) followed by a highlighted menu of
    `options` inside a centred Catppuccin panel. Block until the user picks
    one, returns the option's value (or None on q/esc).
    """
    selected = 0
    n = len(options)
    if n == 0:
        return None

    while True:
        # Build menu lines with highlight on `selected`
        menu = Text()
        for i, (label, _val) in enumerate(options):
            if i == selected:
                menu.append("  ", style=C_PINK)
                menu.append(f" {label} ",
                            style=f"bold {C_BG} on {C_PINK}")
                menu.append("\n")
            else:
                menu.append(f"     {label}\n", style=C_FG)

        body = Group(body_above_menu, Text(""), menu) if body_above_menu else menu
        panel = render_screen(body, footer_hint=footer_hint)
        clear_screen()
        print_centered(panel)

        key = _read_key()
        if key == "up":
            selected = (selected - 1) % n
        elif key == "down":
            selected = (selected + 1) % n
        elif key == "enter":
            return options[selected][1]
        elif key in ("q", "esc"):
            return None


def render_instances_table(insts: list[dict]) -> Table:
    t = Table(
        box=ROUNDED, border_style=C_SURFACE1, header_style=f"bold {C_LAVENDER}",
        title_style=f"bold {C_PINK}", expand=True, show_lines=False,
    )
    t.add_column("", width=2, no_wrap=True)
    t.add_column("name", style=C_MAUVE, no_wrap=True)
    t.add_column("mode", no_wrap=True, width=7)
    t.add_column("state", no_wrap=True)
    t.add_column("tmux", justify="center", width=6)
    t.add_column(f"{ICON_FOLDER}  workdir", style=C_SUBTEXT, overflow="fold")
    t.add_column(f"{ICON_LINK} url", style=C_SAPPHIRE, overflow="fold", max_width=40)

    if not insts:
        t.add_row("", Text("(no instances yet)", style="muted"), "", "", "", "", "")
        return t

    for i in insts:
        state_text = Text()
        # Show the systemd sub-state (running, dead, exited, ...) coloured by
        # whether the unit is meant to be alive.
        if i["active"] == "active" and i["sub"] == "running":
            state_text.append(i["sub"], style="ok")
        elif i["active"] == "activating":
            state_text.append(i["sub"], style="warn")
        elif i["active"] == "failed":
            state_text.append(i["sub"], style="err")
        else:
            state_text.append(i["sub"], style="muted")

        tmux_mark = (Text(ICON_CHECK, style="ok") if i["tmux_alive"]
                     else Text(ICON_CROSS, style="muted"))

        mode = i.get("mode", "code")
        mode_text = Text(mode, style=(C_PEACH if mode == "agents" else C_SUBTEXT))

        url_short = ""
        if i["url"]:
            url_short = i["url"].split("/cli/")[-1] if "/cli/" in i["url"] else i["url"][-30:]

        t.add_row(
            state_icon(i),
            i["name"],
            mode_text,
            state_text,
            tmux_mark,
            i["workdir"],
            url_short,
        )
    return t


def clear_screen():
    if sys.stdout.isatty():
        # Use ANSI clear instead of os.system("clear") so we don't leak
        sys.stdout.write("\x1b[H\x1b[J")
        sys.stdout.flush()


# ---- TUI flows ---------------------------------------------------------------

def tui_main():
    while True:
        insts = list_instances()
        options: list[tuple[str, object]] = []
        for i in insts:
            mark = ICON_DOT_ON if i["active"] == "active" else ICON_DOT_OFF
            options.append((f"{mark}  {i['name']}", ("inst", i["name"])))
        options.append((f"{ICON_PLUS}  new instance", ("new", None)))
        options.append((f"{ICON_REFRESH}  sync ssh aliases", ("sync", None)))
        options.append((f"{ICON_BACK}  quit", ("quit", None)))

        ans = select_in_box(render_instances_table(insts), options)

        if ans is None or ans[0] == "quit":
            clear_screen()
            console.print("[muted]bye[/muted]")
            return
        if ans[0] == "new":
            tui_create()
        elif ans[0] == "sync":
            ok, msg = sync_ssh()
            clear_screen()
            console.print(f"[{'ok' if ok else 'err'}]{msg}[/]")
            input("press enter to continue...")
        elif ans[0] == "inst":
            tui_instance_menu(ans[1])


def render_instance_info(name: str, i: dict) -> Text:
    info = Text()
    info.append(f"{ICON_CUBE} ", style=C_MAUVE)
    info.append(f"{name}\n\n", style="instance")
    info.append("  status   ", style="muted")
    info.append(f"{i['active']}\n",
                style="ok" if i["active"] == "active" else "warn")
    info.append("  tmux     ", style="muted")
    info.append(f"{'alive' if i['tmux_alive'] else 'not running'}\n",
                style="ok" if i["tmux_alive"] else "err")
    info.append("  workdir  ", style="muted")
    info.append(f"{i['workdir']}\n", style="value")
    info.append("  mode     ", style="muted")
    mode = i.get("mode", "code")
    info.append(f"{mode}\n", style=("warn" if mode == "agents" else "value"))
    info.append("  url      ", style="muted")
    info.append(i["url"] or "(none captured)", style="url" if i["url"] else "muted")
    return info


def tui_instance_menu(name: str):
    while True:
        i = next((x for x in list_instances() if x["name"] == name), None)
        if not i:
            clear_screen()
            console.print(f"[err]instance {name} no longer exists[/err]")
            input("press enter...")
            return

        info = render_instance_info(name, i)
        venv_exists = has_venv(i["workdir"])
        is_default_wd = (Path(i["workdir"]).resolve() == Path(DEFAULT_WORKDIR).resolve())
        cur_mode = i.get("mode", "code")
        flip_target = "agents" if cur_mode == "code" else "code"
        options = [
            (f"{ICON_TMUX}  attach (Ctrl+b d to detach)", "attach"),
            (f"{ICON_LINK}  show last claude.ai url", "url"),
            (f"{ICON_REFRESH}  restart (kills convo, fresh url)", "restart"),
            (f"{ICON_CUBE}  switch mode -> {flip_target} (restarts session)", "switch-mode"),
            (f"{ICON_STOP}  stop", "stop"),
        ]
        if not is_default_wd:
            if venv_exists:
                options.append((f"{ICON_REFRESH}  rebuild .venv (uv venv from scratch)", "clean-venv"))
                options.append((f"{ICON_TRASH}  purge .venv (fall back to system Python)", "purge-venv"))
            else:
                options.append((f"{ICON_PLUS}  add .venv (auto-activate on next restart)", "add-venv"))
        options += [
            (f"{ICON_TRASH}  remove (keep workdir)", "remove"),
            (f"{ICON_TRASH}  remove + purge workdir", "purge"),
            (f"{ICON_BACK}  back", "back"),
        ]
        ans = select_in_box(info, options)

        if ans is None or ans == "back":
            return
        if ans == "attach":
            os.execvp("tmux", ["tmux", "attach", "-t", f"claude-{name}"])
        elif ans == "url":
            url = last_url(name) or "(no URL captured yet - try restarting)"
            clear_screen()
            print_centered(render_screen(Text(url, style="url", justify="center")))
            input("\npress enter to continue...")
        elif ans == "restart":
            clear_screen()
            with console.status(f"[info]restarting {name}...[/info]", spinner="dots"):
                ok, msg = restart_instance(name)
            console.print(f"[{'ok' if ok else 'err'}]{ICON_CHECK if ok else ICON_CROSS} {msg}[/]")
            input("press enter to continue...")
        elif ans == "stop":
            clear_screen()
            ok, msg = stop_instance(name)
            console.print(f"[{'ok' if ok else 'err'}]{ICON_CHECK if ok else ICON_CROSS} {msg}[/]")
            input("press enter to continue...")
        elif ans == "switch-mode":
            new_mode = "agents" if cur_mode == "code" else "code"
            confirm = select_in_box(
                Text(
                    f"Switch {name} from '{cur_mode}' to '{new_mode}'?\n"
                    f"The tmux session will be killed and restarted with the new inner command.\n"
                    f"Any in-flight conversation in '{cur_mode}' will be lost.",
                    style="warn", justify="center",
                ),
                [(f"{ICON_CROSS}  no, cancel", False),
                 (f"{ICON_REFRESH}  yes, switch to {new_mode}", True)],
                footer_hint="↑↓ to choose, enter to confirm",
            )
            if confirm:
                clear_screen()
                with console.status(f"[info]switching {name} to {new_mode}...[/info]", spinner="dots"):
                    write_mode_dropin(name, new_mode)
                    # Kill the tmux session so the wrapper rebuilds it with the new inner cmd
                    tmux("kill-session", "-t", f"claude-{name}")
                    r = systemctl("restart", f"claude-remote@{name}.service")
                    ok = r.returncode == 0
                    msg = (f"switched to {new_mode}; session restarting" if ok
                           else f"systemctl restart failed: {r.stderr.strip()}")
                console.print(f"[{'ok' if ok else 'err'}]{ICON_CHECK if ok else ICON_CROSS} {msg}[/]")
                input("press enter to continue...")
        elif ans == "clean-venv":
            clear_screen()
            with console.status(f"[info]rebuilding venv for {name}...[/info]", spinner="dots"):
                ok, msg = clean_venv(name)
            console.print(f"[{'ok' if ok else 'err'}]{ICON_CHECK if ok else ICON_CROSS} {msg}[/]")
            console.print("[muted]any deps that were installed are gone - re-install via pip / uv pip from inside the instance[/muted]")
            input("press enter to continue...")
        elif ans == "add-venv":
            clear_screen()
            with console.status(f"[info]creating venv for {name}...[/info]", spinner="dots"):
                ok, msg = add_venv(name)
            console.print(f"[{'ok' if ok else 'err'}]{ICON_CHECK if ok else ICON_CROSS} {msg}[/]")
            console.print("[muted]restart the instance for the wrapper to pick it up[/muted]")
            input("press enter to continue...")
        elif ans == "purge-venv":
            confirm = select_in_box(
                Text(f"Purge .venv for {name}?\nThe instance will use system Python on next restart.",
                     style="warn", justify="center"),
                [(f"{ICON_CROSS}  no, cancel", False),
                 (f"{ICON_TRASH}  yes, purge", True)],
                footer_hint="↑↓ to choose, enter to confirm",
            )
            if confirm:
                clear_screen()
                ok, msg = purge_venv(name)
                console.print(f"[{'ok' if ok else 'err'}]{ICON_CHECK if ok else ICON_CROSS} {msg}[/]")
                input("press enter to continue...")
        elif ans == "remove":
            confirm = select_in_box(
                Text(f"Remove {name}? Workdir will be kept.",
                     style="warn", justify="center"),
                [(f"{ICON_CROSS}  no, cancel", False),
                 (f"{ICON_CHECK}  yes, remove", True)],
                footer_hint="↑↓ to choose, enter to confirm",
            )
            if confirm:
                clear_screen()
                ok, msg = remove_instance(name, purge_workdir=False)
                console.print(f"[{'ok' if ok else 'err'}]{msg}[/]")
                input("press enter to continue...")
                return
        elif ans == "purge":
            warn = Text()
            warn.append(f"{ICON_WARN} DESTRUCTIVE\n\n", style="err")
            warn.append(f"This will DELETE the workdir for {name}.\n", style="value")
            warn.append(f"Workdir: ", style="muted")
            warn.append(f"{i['workdir']}\n\n", style="value")
            warn.append("Irreversible.", style="err")
            confirm = select_in_box(
                warn,
                [(f"{ICON_CROSS}  no, cancel", False),
                 (f"{ICON_TRASH}  yes, PURGE", True)],
                footer_hint="↑↓ to choose, enter to confirm",
            )
            if confirm:
                clear_screen()
                ok, msg = remove_instance(name, purge_workdir=True)
                console.print(f"[{'ok' if ok else 'err'}]{msg}[/]")
                input("press enter to continue...")
                return


def tui_create():
    clear_screen()
    body = Text("Create a new Claude Code instance", style="title", justify="center")
    print_centered(render_screen(body))
    console.print()

    name = questionary.text(
        "Instance name (lowercase, no spaces - e.g. dev, scratch, project1)",
        style=QSTYLE, qmark=ICON_PLUS,
        validate=lambda v: bool(re.fullmatch(r"[a-z][a-z0-9_-]*", v.strip())) or
                            "use lowercase letters, digits, _, -",
    ).ask()
    if not name:
        return
    name = name.strip()

    mode = select_in_box(
        Text(f"How should '{name}' run Claude?",
             style="title", justify="center"),
        [
            (f"{ICON_CUBE}  Claude Code (single agent, classic)", "code"),
            (f"{ICON_CUBE}  Claude Agents (multi-agent TUI; v2.1.139+)", "agents"),
        ],
        footer_hint="↑↓ to choose, enter to confirm",
    )
    if mode is None:
        return

    kind = select_in_box(
        Text(f"Where should '{name}' run?",
             style="title", justify="center"),
        [
            (f"{ICON_FOLDER}  new empty dir at {DEV_ROOT}/{name}", "new"),
            (f"{ICON_FOLDER}  an existing directory", "exist"),
            (f"{ICON_GIT}  git clone a repo and run there", "clone"),
            (f"{ICON_FOLDER}  default workspace ({DEFAULT_WORKDIR})", "root"),
        ],
    )
    if kind is None:
        return

    workdir = DEFAULT_WORKDIR
    clone_url = None
    if kind == "new":
        workdir = str(DEV_ROOT / name)
    elif kind == "exist":
        workdir = questionary.text("Full path to existing directory:",
                                    default=DEFAULT_WORKDIR, style=QSTYLE).ask()
        if not workdir:
            return
    elif kind == "clone":
        clone_url = questionary.text("Git URL to clone (https or ssh):",
                                      style=QSTYLE).ask()
        if not clone_url:
            return
        clone_url = clone_url.strip()
        suggested = str(DEV_ROOT / name)
        workdir = questionary.text("Where should the repo be cloned to?",
                                    default=suggested, style=QSTYLE).ask()
        if not workdir:
            return

    # Per-instance Python venv? Skip for the default /root workdir (it's the
    # throwaway slot, no need to clutter root with .venv).
    create_venv = False
    if workdir != DEFAULT_WORKDIR:
        venv_choice = select_in_box(
            Text("Give this instance its own Python venv?",
                 style="title", justify="center"),
            [(f"{ICON_CHECK}  yes - isolate pip installs (recommended)", True),
             (f"{ICON_CROSS}  no - use system Python", False)],
            footer_hint="↑↓ to choose, enter to confirm",
        )
        if venv_choice is None:
            return
        create_venv = venv_choice

    with console.status(f"[info]starting {name}...[/info]", spinner="dots"):
        ok, msg = start_instance(name, workdir, clone_url=clone_url,
                                  create_venv=create_venv, mode=mode)
    console.print(f"[{'ok' if ok else 'err'}]{ICON_CHECK if ok else ICON_CROSS} {msg}[/]")

    if ok:
        attach = select_in_box(
            Text(f"Attach to {name}'s tmux session now? (Ctrl+b d to detach)",
                 style="title", justify="center"),
            [(f"{ICON_TMUX}  yes, attach", True),
             (f"{ICON_BACK}  no, back to menu", False)],
            footer_hint="↑↓ to choose, enter to confirm",
        )
        if attach:
            os.execvp("tmux", ["tmux", "attach", "-t", f"claude-{name}"])
    else:
        input("press enter to continue...")

# ---- CLI ---------------------------------------------------------------------

def cmd_list(args):
    insts = list_instances()
    print_centered(render_screen(render_instances_table(insts)))


def cmd_start(args):
    create_venv = True
    if args.no_venv:
        create_venv = False
    mode = getattr(args, "mode", None) or "code"
    if mode not in ("code", "agents"):
        console.print(f"[err]invalid --mode {mode!r}; expected 'code' or 'agents'[/]")
        sys.exit(2)
    ok, msg = start_instance(args.name, args.workdir or DEFAULT_WORKDIR,
                              args.clone, create_venv=create_venv, mode=mode)
    console.print(f"[{'ok' if ok else 'err'}]{msg}[/]")
    sys.exit(0 if ok else 1)


def cmd_stop(args):
    ok, msg = stop_instance(args.name)
    console.print(f"[{'ok' if ok else 'err'}]{msg}[/]")
    sys.exit(0 if ok else 1)


def cmd_restart(args):
    ok, msg = restart_instance(args.name)
    console.print(f"[{'ok' if ok else 'err'}]{msg}[/]")
    sys.exit(0 if ok else 1)


def cmd_attach(args):
    os.execvp("tmux", ["tmux", "attach", "-t", f"claude-{args.name}"])


def cmd_url(args):
    url = last_url(args.name)
    if url:
        console.print(url)
    else:
        console.print("[muted](no URL captured)[/muted]")


def cmd_remove(args):
    ok, msg = remove_instance(args.name, purge_workdir=args.purge_workdir)
    console.print(f"[{'ok' if ok else 'err'}]{msg}[/]")
    sys.exit(0 if ok else 1)


def cmd_sync_ssh(args):
    ok, msg = sync_ssh()
    console.print(f"[{'ok' if ok else 'err'}]{msg}[/]")
    sys.exit(0 if ok else 1)


def cmd_clean_venv(args):
    ok, msg = clean_venv(args.name)
    console.print(f"[{'ok' if ok else 'err'}]{msg}[/]")
    sys.exit(0 if ok else 1)


def cmd_add_venv(args):
    ok, msg = add_venv(args.name)
    console.print(f"[{'ok' if ok else 'err'}]{msg}[/]")
    sys.exit(0 if ok else 1)


def cmd_purge_venv(args):
    ok, msg = purge_venv(args.name)
    console.print(f"[{'ok' if ok else 'err'}]{msg}[/]")
    sys.exit(0 if ok else 1)


def main():
    if len(sys.argv) == 1:
        if not sys.stdout.isatty():
            print("claude-mgr: TUI requires a terminal. See 'claude-mgr --help'.")
            sys.exit(1)
        try:
            tui_main()
        except KeyboardInterrupt:
            print()
        return

    p = argparse.ArgumentParser(prog="claude-mgr", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("list").set_defaults(func=cmd_list)
    s = sp.add_parser("start"); s.add_argument("name"); s.add_argument("--workdir"); s.add_argument("--clone"); s.add_argument("--no-venv", action="store_true", help="skip auto-creating <workdir>/.venv"); s.add_argument("--mode", choices=("code","agents"), default="code", help="run plain 'claude' (default) or the new 'claude agents' multi-agent TUI"); s.set_defaults(func=cmd_start)
    s = sp.add_parser("stop"); s.add_argument("name"); s.set_defaults(func=cmd_stop)
    s = sp.add_parser("restart"); s.add_argument("name"); s.set_defaults(func=cmd_restart)
    s = sp.add_parser("attach"); s.add_argument("name"); s.set_defaults(func=cmd_attach)
    s = sp.add_parser("url"); s.add_argument("name"); s.set_defaults(func=cmd_url)
    s = sp.add_parser("remove"); s.add_argument("name"); s.add_argument("--purge-workdir", action="store_true"); s.set_defaults(func=cmd_remove)
    sp.add_parser("sync-ssh").set_defaults(func=cmd_sync_ssh)
    s = sp.add_parser("clean-venv", help="nuke + recreate the .venv in this instance's workdir"); s.add_argument("name"); s.set_defaults(func=cmd_clean_venv)
    s = sp.add_parser("add-venv",   help="create .venv for an instance that doesn't have one yet"); s.add_argument("name"); s.set_defaults(func=cmd_add_venv)
    s = sp.add_parser("purge-venv", help="delete .venv (instance falls back to system Python)"); s.add_argument("name"); s.set_defaults(func=cmd_purge_venv)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
