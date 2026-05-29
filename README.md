# claudefarm

> Run many Claude Code conversations in parallel on one Linux machine, attach
> to them from any laptop or terminal - never lose your place.

systemd keeps each conversation alive. tmux keeps the buffer in memory across
disconnects. Telegram notifies you when an instance starts so you know it is
ready and how to SSH in.

Catppuccin Mocha colour scheme throughout.

---

## What it looks like

```
        ╭───────────────────────────────────────────────────────────────────────────╮
        │                                                                           │
        │                            claude-mgr  on  k12                            │
        │  ───────────────────────────────────────────────────────────────────────  │
        │                                                                           │
        │   ╭────┬───────────┬────────┬─────────┬──────┬─────────────────╮ │
        │   │    │ name      │ mode   │ state   │ tmux │  workdir        │ │
        │   ├────┼───────────┼────────┼─────────┼──────┼─────────────────┤ │
        │   │ ●  │ gscontent │ code   │ running │   ✓  │ /data/dev/gsc.. │ │
        │   │ ●  │ homelab   │ code   │ running │   ✓  │ /data/dev/k12.. │ │
        │   │ ●  │ scratch   │ agents │ running │   ✓  │ /data/dev/scra. │ │
        │   │ ●  │ main      │ code   │ running │   ✓  │ /root           │ │
        │   ╰────┴───────────┴────────┴─────────┴──────┴─────────────────╯ │
        │                                                                           │
        │   ●  gscontent                                                            │
        │   ●  homelab                                                              │
        │   ●  scratch                                                              │
        │   ●  main                                                                 │
        │     new instance                                                       │
        │   ▎ sync ssh aliases                                                    │
        │     container shell (maintenance)                                      │
        │     quit                                                               │
        │                                                                           │
        │  ───────────────────────────────────────────────────────────────────────  │
        │               ↑↓ to navigate, enter to choose, q to quit                  │
        ╰───────────────────────────────────────────────────────────────────────────╯
```

Each row is a long-running Claude Code session living in its own tmux session
and systemd unit. Pick one, hit enter, you're attached. Detach (Ctrl-B d)
and the conversation keeps running on the server.

**`container shell (maintenance)`** drops you into a login shell on the box
that hosts every instance - for sysadmin chores like updating Claude Code
(`npm install -g @anthropic-ai/claude-code`, then restart instances to pick it
up), poking systemd, or anything else. Type `exit` to come back to the menu.
Handy when a client auto-launches `claude-mgr` on connect, so the TUI is the
only thing you land in.

---

## Why this exists

- **One Claude subscription, many parallel projects.** Different repos,
  different conversations, no waiting for one to finish before starting
  another.
- **Conversations survive disconnects.** The Claude process lives in tmux
  on the server. Close your laptop, drop your VPN, swap WiFi networks —
  the conversation is exactly where you left it.
- **Access from anywhere over SSH.** `ssh claude-<host>-<instance>` from
  any machine that can reach the server. Telegram notifies you when an
  instance (re)starts so you always know how to reconnect.
- **Cheap.** A 1 GB LXC or VPS hosts a dozen instances comfortably.
- **No new SaaS.** Your existing Claude account, your own server, plain
  SSH. No third-party broker.

---

## Architecture

```
+------------------+      ssh claude-<host>-<inst>      +-------------------+
|  client          | ----------------------------------> |  server (Linux)   |
|  Linux/Mac/Win   |                                     |                   |
|                  | <-- claude-instances-<host>.cfg --- |  - claude-mgr     |
|                  |     auto-generated SSH alias        |  - tmux sessions  |
|                  |     committed to this repo          |  - systemd units  |
+------------------+                                     +-------------------+
        |                                                          |
        |                   git pull                                |
        +-----------------------------------------------------------+
              (clients refresh aliases when the server spins up new
               instances; one-line cron or manual)
```

- **One server** (any Linux box with systemd) hosts the actual Claude Code
  processes.
- **Many clients** (laptops, desktops, phones via SSH apps) attach to them
  over SSH.
- The repo's `client/claude-instances-<host>.cfg` files are the only thing
  shared between server and clients — committed by the server, pulled by
  clients. Your `~/.ssh/config` Includes the glob, so adding more servers
  Just Works.

**Multi-server is supported out of the box.** Run `bootstrap.sh` on as many
machines as you like (`k12`, `vps-london`, `mac-mini-office`…); each will
publish its own `claude-instances-<host>.cfg`. Clients pull the repo and
get all aliases.

---

## Quick install

### Server (Linux only — needs systemd)

```bash
curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/server/bootstrap.sh | bash
```

Tested on Debian 12 (LXC + bare metal) and Ubuntu 22.04. See
[server/README.md](server/README.md) for the full breakdown — what gets
installed, where, and how to add your Telegram bot.

### Client

| Platform | One-liner |
|---|---|
| **Linux** | `curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/client/setup-client.sh \| bash` |
| **macOS** | `curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/client/setup-client.sh \| bash` |
| **Windows** | `iwr -useb https://raw.githubusercontent.com/Clinteastman/claudefarm/main/client/setup-client.ps1 \| iex` |

All three are idempotent — safe to re-run any time. They:

1. Clone (or pull) this repo to `~/github/claudefarm`
2. Generate an SSH key if you don't have one
3. Add the right `Include` line to `~/.ssh/config`
4. Try to copy your pubkey to the server (you'll be prompted for the server's password once)
5. Append a `claude-mgr` shell alias to `~/.bashrc` / `~/.zshrc` (or PowerShell profile on Windows)
6. Test the connection

After client setup the SSH aliases are live: `ssh claude-<host>-<instance>`
and the `claude-mgr` command brings up the TUI on the server.

See [client/README.md](client/README.md) for the per-platform breakdown
and what to do if you'd rather install manually.

---

## First ten minutes

```bash
# On the server
curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/server/bootstrap.sh | bash
claude-mgr                    # TUI picker → "new instance" → name it, give it a workdir
                              # claude-mgr creates the systemd unit, starts the instance,
                              # opens tmux, sends a Telegram notification

# On any client (laptop, second server, etc.)
curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/client/setup-client.sh | bash
# Reopen your shell, then:
claude-mgr                    # → SSH'es to the server, opens the same TUI
ssh claude-k12-myinstance     # → directly attach to a specific instance
```

Detach with **Ctrl-B d** (the tmux prefix). Reattach any time from any
client. The Claude Code session and your tool-use history persist.

---

## Repo layout

```
claudefarm/
├── README.md                         (you are here)
├── server/                           runs on the Linux box hosting instances
│   ├── README.md                       full server docs
│   ├── bootstrap.sh                    idempotent installer
│   ├── claude-mgr.py                   the TUI + CLI
│   ├── claude-statusline.py            per-instance Claude statusline
│   ├── claude-remote-with-telegram.sh  tmux + Telegram wrapper
│   ├── claude-remote@.service          systemd template (one unit per inst)
│   ├── tmux.conf                       Catppuccin tmux config + tab-title hooks
│   └── cheatsheet                      `cheatsheet` command quick-ref
└── client/                           runs on every laptop you attach from
    ├── README.md                       per-platform client docs
    ├── setup-client.sh                 Linux + macOS installer
    ├── setup-client.ps1                Windows installer
    ├── claude-statusline.py            local Claude statusline
    ├── ssh-config.example              sample SSH config block
    └── claude-instances-<host>.cfg     auto-generated per server (don't edit)
```

---

## A typical day

```bash
# Morning, at the desk: attach to your in-progress conversation
claude-mgr                    # → pick "homelab"

# Lunch: walk away, leave the terminal open. The instance keeps running.

# Mid-afternoon, elsewhere: SSH in from any machine.
ssh claude-k12-homelab        # drops straight into the tmux session

# Evening: back at the desk, claude-mgr → "homelab" again. Tmux scrollback
# shows everything from earlier in the day.
```

---

## Features beyond "tmux + ssh"

- **Per-instance systemd units** — instances survive reboots, are
  individually start/stop/restart-able, and you get all the usual
  `systemctl status`, `journalctl -u` introspection.
- **Telegram restart notifications** - every time an instance starts,
  a Telegram message tells you the instance name and the SSH command to
  reach it. Useful after reboots or manual restarts.
- **Auto-generated SSH aliases** — `claude-mgr` writes
  `client/claude-instances-<host>.cfg` whenever you add/remove instances.
  Commit + push the repo and clients pull to get the new aliases. No
  manual config editing.
- **Pick Claude Code or Claude Agents per instance** — when you create
  a new instance the TUI asks whether to run plain `claude` (single
  agent, classic) or the new multi-agent `claude agents` TUI (research
  preview from Claude Code v2.1.139+). Existing instances can be
  flipped between the two modes from the per-instance menu. CLI parity
  with `claude-mgr start <name> --mode agents`.
- **Catppuccin Mocha everywhere** — tmux status bar, Claude statusline,
  TUI picker. Consistent palette across the stack.
- **Auto-renamed terminal tabs** — tmux pushes the session name to the
  outer terminal via OSC 0/2, so Windows Terminal / iTerm / Kitty etc.
  show `lxc-<instance>` instead of "PowerShell" or "bash".
- **Idempotent installs** — server bootstrap and client setup scripts
  are safe to re-run any time. They detect existing state and skip
  what's done.
- **Works behind any firewall** — only outbound SSH needed from clients,
  outbound HTTPS from server (for Claude API + Telegram). No inbound
  ports beyond the SSH you'd already have.

---

## Requirements

| Side | Requirements |
|---|---|
| **Server** | Linux with systemd (Debian 12 / Ubuntu 22.04+ / Fedora 39+). ~1 GB RAM, ~5 GB disk. Internet access. Root or sudo. A working `ssh` you can reach from your clients. |
| **Client** | Linux / macOS / Windows. Git + OpenSSH. Network reachability to the server (LAN, Tailscale, WireGuard — claudefarm doesn't care). |

A Telegram bot + chat ID is **optional but recommended** — without it
you won't get notified when an instance restarts. You can always attach
via `ssh claude-<host>-<instance>` or `claude-mgr` directly.

---

## Security model

claudefarm gives you a tmux multiplexer over SSH, with a TUI that
manages systemd units. It does **not** add a new authentication layer —
your existing SSH config is the gate.

- **Server access** is whatever SSH access you've set up. Use keys, not
  passwords; consider `PermitRootLogin prohibit-password` etc. The
  scripts run as root by default because systemd units are easier that
  way; you can change the unit's User= if you'd rather not.
- **Session access is SSH-only.** Attach via `ssh claude-<host>-<instance>`
  or through the `claude-mgr` TUI. No browser-accessible URLs are
  generated or shared.
- **No public ports needed.** The server only needs outbound HTTPS
  (Claude API, Telegram, optional GitHub pull). Clients only need
  outbound SSH to the server.
- **The repo's `client/claude-instances-<host>.cfg` files contain only
  hostnames and tmux session names** — no secrets. Safe to push to a
  public repo.

---

## TUI hotkeys

| Key | Action |
|---|---|
| `↑` `↓` | Move selection |
| `Enter` | Open the highlighted instance / menu item |
| `n` | New instance (same as selecting "new instance") |
| `r` | Restart highlighted instance |
| `s` | Stop highlighted instance |
| `S` | Start a stopped instance |
| `d` | Delete highlighted instance (asks to confirm) |
| `y` | Sync SSH aliases (writes `client/claude-instances-<host>.cfg`; commit + push the repo yourself to share) |
| `?` | Help overlay |
| `q` | Quit |

Inside an instance menu (the screen you land on after picking a row),
there's a **"switch mode → agents"** (or "→ code") action that flips
the instance between single-Claude and `claude agents` multi-agent
modes. The current tmux session gets killed and the systemd unit
restarts with the new inner command; the in-flight conversation is
lost.

---

## CLI mode (skip the TUI)

`claude-mgr` is also a regular CLI:

```bash
claude-mgr list                            # show all instances + states
claude-mgr start <name>                    # start (or convert) an instance
                                           #   --workdir /path/to/repo
                                           #   --clone https://...
                                           #   --mode {code,agents}    (default code)
                                           #   --no-venv
claude-mgr stop <name>                     # stop a running instance
claude-mgr restart <name>                  # restart (sends Telegram notification)
claude-mgr remove <name>                   # remove the systemd unit + tmux session
                                           #   --purge-workdir
claude-mgr sync-ssh                        # regenerate the client SSH config (commit + push yourself)
claude-mgr add-venv <name>                 # create .venv in the instance's workdir
claude-mgr clean-venv <name>               # rebuild .venv from scratch
claude-mgr purge-venv <name>               # delete .venv (fall back to system Python)
```

To flip an existing instance from code mode to agents mode (or back):

```bash
claude-mgr start <name> --mode agents
```

This rewrites the per-instance `mode.conf` systemd drop-in and restarts
the unit. Equivalent to picking "switch mode" in the TUI.

---

## Troubleshooting

**`bash: line 1: 404:: command not found`** when running the one-liner
- The repo was private when you fetched the URL — GitHub returns a 404
  page that bash tries to execute. The script is now in a public repo;
  re-run the one-liner.

**`tmux attach -t claude-<x> failed`**
- Instance might not be running. Check `claude-mgr list` or
  `systemctl status claude-remote@<x>`.

**Telegram pings stopped**
- Check the bot token + chat ID in
  `/root/.config/telegram_notify.json` on the server, and that
  `/root/telegram_notify.py` exists and is executable. Test with:
  ```
  echo "test" | /root/telegram_notify.py
  ```

**Tab title doesn't update in Windows Terminal**
- Reattach after `tmux source-file ~/.tmux.conf` so the title-emitting
  format reloads. If still blank, see
  [server/README.md#tab-titles](server/README.md) for the strftime
  gotcha (`%%s` vs `%s` in `set-titles-string`).

**Claude session looks frozen after a network blip**
- It isn't — tmux is. Detach (Ctrl-B d) and reattach
  (`ssh claude-<host>-<x>` or via `claude-mgr`).

---

## Contributing

Issues and PRs welcome. The codebase is small (~1k lines of Python and
shell). Open an issue first if you're planning a sizeable change so we
can discuss design.

If you've found a corner case (a different distro, a different terminal
emulator, an SSH config that breaks something), a one-line bug report
in an issue is enough; including the relevant log lines / errors is
gold.

---

## See also

- [server/README.md](server/README.md) — server install, config reference, Telegram setup, troubleshooting
- [client/README.md](client/README.md) — per-platform client install, manual fallback, troubleshooting
- [Claude Code docs](https://docs.claude.com/en/docs/claude-code) — upstream Claude Code (the thing claudefarm runs N of)

---

## License

MIT — see [LICENSE](LICENSE).
