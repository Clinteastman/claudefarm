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
  start/stop/remove auto-update {repo}/desktop/claude-instances.cfg with the
  current set of instances. Desktops Include that file in their ~/.ssh/config
  to get auto-updated `ssh claude-<instance>` aliases. After the file changes,
  commit + push the homelab repo and have the desktop pull to receive the
  new aliases.

  Set CLAUDEFARM_REPO env var to override the default repo path.
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
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.theme import Theme
    from rich.box import ROUNDED
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.align import Align
    from rich.padding import Padding
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
HOMELAB_REPO = Path(os.environ.get("CLAUDEFARM_REPO", "/data/dev/claudefarm"))
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
        insts.append({
            "name": name, "unit": unit, "active": active, "sub": sub,
            "enabled": enabled, "tmux_alive": tmux_alive,
            "workdir": workdir, "url": url,
        })
    return insts


def read_workdir(name: str) -> str:
    dropin = DROPIN_DIR / f"claude-remote@{name}.service.d" / "workdir.conf"
    if dropin.exists():
        for ln in dropin.read_text().splitlines():
            if ln.startswith("Environment=CLAUDE_WORKDIR="):
                return ln.split("=", 2)[2].strip()
    return DEFAULT_WORKDIR


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


def remove_dropin(name: str) -> None:
    d = DROPIN_DIR / f"claude-remote@{name}.service.d"
    if d.exists():
        for f in d.iterdir():
            f.unlink()
        d.rmdir()
    systemctl("daemon-reload")


def start_instance(name: str, workdir: str = DEFAULT_WORKDIR,
                   clone_url: str | None = None) -> tuple[bool, str]:
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

    if workdir != DEFAULT_WORKDIR:
        write_workdir_dropin(name, workdir)

    systemctl("enable", f"claude-remote@{name}.service")
    r = systemctl("restart", f"claude-remote@{name}.service")
    if r.returncode != 0:
        return False, f"systemctl restart failed: {r.stderr.strip()}"
    sync_ssh()
    return True, f"started claude-remote@{name} (workdir={workdir})"


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
    if not HOMELAB_REPO.is_dir():
        return False, f"homelab repo not found at {HOMELAB_REPO} (set CLAUDEFARM_REPO env var)"
    out = HOMELAB_REPO / "desktop" / f"claude-instances-{HOSTNAME_TAG}.cfg"
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


def render_header() -> Panel:
    title = Text()
    title.append(f"{ICON_SERVER} ", style=C_LAVENDER)
    title.append("claude-mgr", style="title")
    title.append("  on  ", style="muted")
    title.append(HOSTNAME_TAG, style="host")
    return Panel(Align.center(title), border_style=C_MAUVE, box=ROUNDED, padding=(0, 1))


def render_instances_table(insts: list[dict]) -> Table:
    t = Table(
        box=ROUNDED, border_style=C_SURFACE1, header_style=f"bold {C_LAVENDER}",
        title_style=f"bold {C_PINK}", expand=True, show_lines=False,
    )
    t.add_column("", width=2, no_wrap=True)
    t.add_column("name", style=C_MAUVE, no_wrap=True)
    t.add_column("state", no_wrap=True)
    t.add_column("tmux", justify="center", width=6)
    t.add_column(f"{ICON_FOLDER}  workdir", style=C_SUBTEXT, overflow="fold")
    t.add_column(f"{ICON_LINK} url", style=C_SAPPHIRE, overflow="fold", max_width=40)

    if not insts:
        t.add_row("", Text("(no instances yet)", style="muted"), "", "", "", "")
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

        url_short = ""
        if i["url"]:
            url_short = i["url"].split("/cli/")[-1] if "/cli/" in i["url"] else i["url"][-30:]

        t.add_row(
            state_icon(i),
            i["name"],
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
        clear_screen()
        console.print(render_header())
        insts = list_instances()
        console.print(render_instances_table(insts))
        console.print()

        choices = []
        for i in insts:
            mark = ICON_DOT_ON if i["active"] == "active" else ICON_DOT_OFF
            label = f"  {mark}  {i['name']}"
            choices.append(questionary.Choice(title=label, value=("inst", i["name"])))
        if insts:
            choices.append(questionary.Separator("  "))
        choices.append(questionary.Choice(title=f"  {ICON_PLUS}  new instance",
                                          value=("new", None)))
        choices.append(questionary.Choice(title=f"  {ICON_REFRESH}  sync ssh aliases",
                                          value=("sync", None)))
        choices.append(questionary.Choice(title=f"  {ICON_BACK}  quit",
                                          value=("quit", None)))

        ans = questionary.select(
            "What now?",
            choices=choices,
            style=QSTYLE,
            qmark=ICON_CUBE,
            instruction="(arrows + enter, q to quit)",
        ).ask()

        if ans is None or ans[0] == "quit":
            console.print(f"[muted]bye[/muted]")
            return
        if ans[0] == "new":
            tui_create()
        elif ans[0] == "sync":
            ok, msg = sync_ssh()
            console.print(f"[{'ok' if ok else 'err'}]{msg}[/]")
            input("press enter to continue...")
        elif ans[0] == "inst":
            tui_instance_menu(ans[1])


def tui_instance_menu(name: str):
    while True:
        i = next((x for x in list_instances() if x["name"] == name), None)
        if not i:
            console.print(f"[err]instance {name} no longer exists[/err]")
            input("press enter...")
            return

        clear_screen()
        console.print(render_header())

        info = Text()
        info.append(f"{ICON_CUBE} ", style=C_MAUVE)
        info.append(f"{name}\n\n", style="instance")
        info.append(f"  status   ", style="muted")
        info.append(f"{i['active']}\n",
                    style="ok" if i["active"] == "active" else "warn")
        info.append(f"  tmux     ", style="muted")
        info.append(f"{'alive' if i['tmux_alive'] else 'not running'}\n",
                    style="ok" if i["tmux_alive"] else "err")
        info.append(f"  workdir  ", style="muted")
        info.append(f"{i['workdir']}\n", style="value")
        info.append(f"  url      ", style="muted")
        info.append(i["url"] or "(none captured)", style="url" if i["url"] else "muted")

        console.print(Panel(info, border_style=C_MAUVE, box=ROUNDED,
                            title=f"[title]instance[/title]", padding=(1, 2)))
        console.print()

        ans = questionary.select(
            f"Action for {name}",
            choices=[
                questionary.Choice(title=f"  {ICON_TMUX} attach (Ctrl+b d to detach)", value="attach"),
                questionary.Choice(title=f"  {ICON_LINK} show last claude.ai url", value="url"),
                questionary.Choice(title=f"  {ICON_REFRESH} restart (kills convo, fresh url)", value="restart"),
                questionary.Choice(title=f"  {ICON_STOP} stop", value="stop"),
                questionary.Separator(f"  "),
                questionary.Choice(title=f"  {ICON_TRASH} remove (keep workdir)", value="remove"),
                questionary.Choice(title=f"  {ICON_TRASH} remove + purge workdir", value="purge"),
                questionary.Separator(f"  "),
                questionary.Choice(title=f"  {ICON_BACK} back", value="back"),
            ],
            style=QSTYLE,
            qmark=ICON_CUBE,
        ).ask()

        if ans is None or ans == "back":
            return
        if ans == "attach":
            os.execvp("tmux", ["tmux", "attach", "-t", f"claude-{name}"])
        elif ans == "url":
            url = last_url(name) or "(no URL captured yet - try restarting)"
            console.print(Panel(Text(url, style="url"),
                                title=f"[title]url for {name}[/title]",
                                border_style=C_SAPPHIRE, box=ROUNDED, padding=(1, 2)))
            input("press enter to continue...")
        elif ans == "restart":
            with console.status(f"[info]restarting {name}...[/info]", spinner="dots"):
                ok, msg = restart_instance(name)
            console.print(f"[{'ok' if ok else 'err'}]{ICON_CHECK if ok else ICON_CROSS} {msg}[/]")
            input("press enter to continue...")
        elif ans == "stop":
            ok, msg = stop_instance(name)
            console.print(f"[{'ok' if ok else 'err'}]{ICON_CHECK if ok else ICON_CROSS} {msg}[/]")
            input("press enter to continue...")
        elif ans == "remove":
            if questionary.confirm(f"Remove {name}? (workdir kept)",
                                    default=False, style=QSTYLE).ask():
                ok, msg = remove_instance(name, purge_workdir=False)
                console.print(f"[{'ok' if ok else 'err'}]{msg}[/]")
                input("press enter to continue...")
                return
        elif ans == "purge":
            console.print(Panel(
                Text(f"This will DELETE the workdir directory for {name}.\n"
                     f"Workdir: {i['workdir']}\nThis is destructive and irreversible.",
                     style="err"),
                border_style=C_RED, box=ROUNDED, title=f"[title]{ICON_WARN} purge[/title]",
                padding=(1, 2)))
            if questionary.confirm("Really purge?", default=False, style=QSTYLE).ask():
                ok, msg = remove_instance(name, purge_workdir=True)
                console.print(f"[{'ok' if ok else 'err'}]{msg}[/]")
                input("press enter to continue...")
                return


def tui_create():
    clear_screen()
    console.print(render_header())
    console.print(Panel(Text("Create a new Claude Code instance", style="title"),
                        border_style=C_MAUVE, box=ROUNDED, padding=(0, 2)))
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

    kind = questionary.select(
        f"Where should '{name}' run?",
        choices=[
            questionary.Choice(title=f"  {ICON_FOLDER} new empty dir at {DEV_ROOT}/{name}",
                               value="new"),
            questionary.Choice(title=f"  {ICON_FOLDER} an existing directory",
                               value="exist"),
            questionary.Choice(title=f"  {ICON_GIT} git clone a repo and run there",
                               value="clone"),
            questionary.Choice(title=f"  {ICON_FOLDER} default workspace ({DEFAULT_WORKDIR})",
                               value="root"),
        ],
        style=QSTYLE, qmark=ICON_FOLDER,
    ).ask()
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

    with console.status(f"[info]starting {name}...[/info]", spinner="dots"):
        ok, msg = start_instance(name, workdir, clone_url=clone_url)
    console.print(f"[{'ok' if ok else 'err'}]{ICON_CHECK if ok else ICON_CROSS} {msg}[/]")

    if ok and questionary.confirm(
        f"Attach to {name}'s tmux session now? (Ctrl+b d to detach)",
        default=True, style=QSTYLE,
    ).ask():
        os.execvp("tmux", ["tmux", "attach", "-t", f"claude-{name}"])
    else:
        input("press enter to continue...")

# ---- CLI ---------------------------------------------------------------------

def cmd_list(args):
    insts = list_instances()
    console.print(render_header())
    console.print(render_instances_table(insts))


def cmd_start(args):
    ok, msg = start_instance(args.name, args.workdir or DEFAULT_WORKDIR, args.clone)
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
    s = sp.add_parser("start"); s.add_argument("name"); s.add_argument("--workdir"); s.add_argument("--clone"); s.set_defaults(func=cmd_start)
    s = sp.add_parser("stop"); s.add_argument("name"); s.set_defaults(func=cmd_stop)
    s = sp.add_parser("restart"); s.add_argument("name"); s.set_defaults(func=cmd_restart)
    s = sp.add_parser("attach"); s.add_argument("name"); s.set_defaults(func=cmd_attach)
    s = sp.add_parser("url"); s.add_argument("name"); s.set_defaults(func=cmd_url)
    s = sp.add_parser("remove"); s.add_argument("name"); s.add_argument("--purge-workdir", action="store_true"); s.set_defaults(func=cmd_remove)
    sp.add_parser("sync-ssh").set_defaults(func=cmd_sync_ssh)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
