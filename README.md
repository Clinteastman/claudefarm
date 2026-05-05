# claudefarm

Run many Claude Code conversations in parallel on one Linux machine, attach
to them from any laptop, never lose your place. systemd keeps each one
alive, tmux keeps the conversation in memory, Telegram pings you the
[claude.ai Remote Control](https://docs.claude.com/en/docs/claude-code/remote-control)
URL on every restart so you can switch between desktop, terminal and phone.
Catppuccin Mocha TUI throughout.

## What it looks like

```
        ╭──────────────────────────────────────────────────────────────────────╮
        │                                                                      │
        │                          claude-mgr  on  k12                         │
        │  ──────────────────────────────────────────────────────────────────  │
        │                                                                      │
        │   ╭────┬───────────┬─────────┬──────┬─────────────────┬───────────╮  │
        │   │    │ name      │ state   │ tmux │  workdir       │  url     │  │
        │   ├────┼───────────┼─────────┼──────┼─────────────────┼───────────┤  │
        │   │ ●  │ gscontent │ running │   ✓  │ /data/dev/gsc.. │ /cli/...  │  │
        │   │ ●  │ homelab   │ running │   ✓  │ /data/dev/k12.. │ /cli/...  │  │
        │   │ ●  │ main      │ running │   ✓  │ /root           │ /cli/...  │  │
        │   ╰────┴───────────┴─────────┴──────┴─────────────────┴───────────╯  │
        │                                                                      │
        │   ●  gscontent                                                       │
        │   ●  homelab                                                         │
        │   ●  main                                                            │
        │     new instance                                                  │
        │   ▎ sync ssh aliases                                               │
        │     quit                                                          │
        │                                                                      │
        │  ──────────────────────────────────────────────────────────────────  │
        │             ↑↓ to navigate, enter to choose, q to quit               │
        ╰──────────────────────────────────────────────────────────────────────╯
```

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
              (clients refresh aliases when server spins up new
               instances; one-line cron or manual)
```

- **One server** (any Linux box) hosts the actual Claude Code processes.
- **Many clients** (laptops, desktops, phones via SSH apps) attach to them.
- The repo's `client/claude-instances-<host>.cfg` files are the only thing
  shared between server and clients - committed by the server, pulled by
  clients. Your `~/.ssh/config` Includes the glob, so adding more servers
  Just Works.

## Quick install

### Server (Linux only - needs systemd)

```bash
curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/server/bootstrap.sh | bash
```

Tested on Debian 12 (LXC + bare metal). See [server/README.md](server/README.md) for full details.

### Client

| Platform | One-liner |
|---|---|
| **Linux** | `curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/client/setup-client.sh \| bash` |
| **macOS** | `curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/client/setup-client.sh \| bash` |
| **Windows** | `iwr -useb https://raw.githubusercontent.com/Clinteastman/claudefarm/main/client/setup-client.ps1 \| iex` |

See [client/README.md](client/README.md) for the per-platform breakdown
and what to do if you'd rather install manually.

After client setup, the SSH aliases are live: `ssh claude-<host>-<instance>`.

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
│   ├── tmux.conf                       Catppuccin tmux config
│   └── cheatsheet                      `cheatsheet` command quick-ref
└── client/                           runs on every laptop you attach from
    ├── README.md                       per-platform client docs
    ├── setup-client.sh                 Linux + macOS installer
    ├── setup-client.ps1                Windows installer
    ├── claude-statusline.py            local Claude statusline (with Remote: On/Off badge)
    ├── ssh-config.example              sample SSH config block
    └── claude-instances-<host>.cfg     auto-generated per server (don't edit)
```

## How a typical day looks

```bash
# From any machine where you ran the client installer:
ssh claude-mgr-k12          # opens the TUI on K12 over SSH (server-side claude-mgr)
ssh claude-k12-main         # attaches to the 'main' tmux session on K12
ssh claude-k12-homelab      # attaches to the 'homelab' instance
# ... close laptop, switch to phone, keep talking to the same Claude
```

Each instance is reachable simultaneously from all your devices via the
[claude.ai Remote Control](https://docs.claude.com/en/docs/claude-code/remote-control)
URL Telegram pings you when the instance starts. The terminal is just one
of those clients.

## Why this exists

- **One claude.ai login funds many parallel projects.** Different repos,
  different conversations, no waiting for one to finish.
- **Conversations survive disconnects.** The Claude process lives in tmux
  on the server. Drop your VPN, close your laptop, the conversation is
  exactly where you left it.
- **Phone access for free.** No need for Nabu Casa-style hosted services.
  The Telegram-pinged claude.ai URL works in the iOS/Android Claude app.

## Requirements

| Side | Requirements |
|---|---|
| **Server** | Linux with systemd (Debian 12 / Ubuntu 22.04+ / Fedora 39+). 1 GB RAM, ~5 GB disk. Internet access. Root or sudo. A working `ssh` you can reach from your clients. |
| **Client** | Linux / macOS / Windows. Git + OpenSSH. Network reachability to the server (LAN or Tailscale or whatever - claudefarm doesn't care). |

A telegram bot + chat ID is **optional** but recommended - without it you
won't get the new claude.ai URL pinged when an instance restarts. You can
still see it via `claude-mgr url <name>` or by attaching to the tmux session.

## See also

- [server/README.md](server/README.md) - server install, config reference, troubleshooting
- [client/README.md](client/README.md) - per-platform client install, manual fallback, troubleshooting
- [Claude Code docs](https://docs.claude.com/en/docs/claude-code) - upstream Claude Code (the thing claudefarm runs N of)
- [Remote Control](https://docs.claude.com/en/docs/claude-code/remote-control) - the feature that lets phone/desktop/terminal share a session
