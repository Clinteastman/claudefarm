# claudefarm

Multi-instance Claude Code over SSH. One server runs N parallel Claude
sessions under systemd + tmux, each with its own claude.ai Remote Control
URL pinged to Telegram. Any client SSHes in and attaches.

Designed to be installed on any Linux box, not just one specific machine.
Catppuccin Mocha TUI + Nerd Font icons throughout.

## Layout

```
server/   stuff that runs on the box hosting the Claude instances
client/   stuff that runs on every laptop/desktop you control them from
```

## Quick install

**Server** (the box that will host the instances):
```bash
curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/server/bootstrap.sh | bash
```

**Client** (any Linux/macOS laptop you want to attach from):
```bash
curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/client/setup-client.sh | bash
```

Both scripts are idempotent - safe to re-run for upgrades.

See `server/README.md` and `client/README.md` for details on each.

## How it fits together

```
+------------------+      ssh claude-<host>-<inst>     +-------------------+
|                  | ----------------------------------> |                   |
|  client          |                                     |  server           |
|  (laptop, etc.)  | <-- claude-instances-<host>.cfg --- |  (claude-mgr +    |
|                  |     auto-generated SSH alias        |   systemd units)  |
|                  |     committed to this repo          |                   |
+------------------+                                     +-------------------+
        |                                                          |
        |                git pull                                   |
        +-----------------------------------------------------------+
                       (refresh aliases when server
                        spins up / removes instances)
```

The server's `claude-mgr sync-ssh` writes a per-host alias file
(`client/claude-instances-<server-hostname>.cfg`) and commits it. Clients
`git pull` to pick up new aliases. The Include line in their `~/.ssh/config`
is a glob, so adding more servers just adds more files - no client config
changes needed.
