# claude-mgr

Multi-instance Claude Code on Linux. Each instance is one
`claude-remote@<name>.service` systemd unit that owns its own tmux session,
its own claude.ai Remote Control URL via Telegram, and optionally its own
working directory. Manage them all from a Catppuccin Mocha TUI.

Originally built for the K12 Claude LXC; now generic - install on any
Linux box with the bootstrap script.

## Install

```bash
curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/server/bootstrap.sh | bash
```

The script is idempotent - safe to re-run for upgrades. It will:

1. Install system packages (tmux, python3, git, nodejs)
2. `npm install -g @anthropic-ai/claude-code`
3. Clone this repo to `/data/dev/claudefarm` (override with `CLAUDEFARM_REPO`)
4. Symlink configs into place
5. Drop the systemd template into `/etc/systemd/system/`
6. Write a per-host config at `/etc/claude-mgr.conf`
7. Print the interactive next-steps (`claude` login, telegram setup)

## Per-host config

`/etc/claude-mgr.conf`:

```bash
CLAUDE_MGR_HOSTNAME="cabin"            # used in SSH alias names + tmux status
CLAUDE_MGR_LAN_IP="192.168.50.55"      # IP your desktop ssh's into
CLAUDE_MGR_SSH_USER="root"
CLAUDE_MGR_RESTART_HOST="192.168.50.55"
CLAUDE_MGR_RESTART_VIA=""              # or "pct exec <ctid> --" for LXCs
CLAUDEFARM_REPO="/data/dev/claudefarm"
```

## Usage

```
claude-mgr               # interactive Catppuccin TUI
claude-mgr list          # plain text list
claude-mgr start <name>  # creates if needed, defaults to /root
claude-mgr start <name> --workdir /path
claude-mgr start <name> --clone https://github.com/foo/bar.git
claude-mgr stop <name>
claude-mgr restart <name>
claude-mgr attach <name>
claude-mgr remove <name>
claude-mgr remove <name> --purge-workdir
claude-mgr sync-ssh
```

Every create/remove auto-regenerates `desktop/claude-instances-<hostname>.cfg`
in the repo. Commit + push to share with your desktop.

## Desktop SSH config

One Include line picks up aliases from every machine running claude-mgr:

```
Include ~/github/claudefarm/client/claude-instances-*.cfg
```

After that, `ssh claude-<host>-<instance>` attaches to the right tmux
session on the right machine.

## Files in this directory

| File | Role |
|---|---|
| `bootstrap.sh` | Idempotent installer. The single entry point. |
| `claude-mgr.py` | The TUI + CLI. Symlinked to `/usr/local/bin/claude-mgr`. |
| `claude-statusline.py` | Per-instance Claude Code statusline. |
| `claude-remote-with-telegram.sh` | tmux+telegram wrapper run by the systemd unit. |
| `claude-remote@.service` | systemd template. One unit per instance. |
| `tmux.conf` | Catppuccin Mocha tmux config. |
| `cheatsheet` | `cheatsheet` command - quick reference card. |
