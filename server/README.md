# server/

Everything that runs on the **Linux** machine hosting your Claude Code
instances. Install with one command, manage with `claude-mgr`.

> Linux only. The server uses systemd to keep instances alive across
> reboots and tmux to hold each conversation in memory. Neither
> macOS nor Windows are supported as servers - you can still use them
> as **clients** to attach (see [`client/README.md`](../client/README.md)).

## Tested on

| Distro | Status |
|---|---|
| Debian 12 (bookworm) | ✓ Primary target. Bare metal + LXC. |
| Ubuntu 22.04+        | ✓ Should work, same package names. |
| Fedora 39+           | ⚠ Not tested but bootstrap.sh detects `apt-get` only. PRs welcome. |
| macOS                | ✗ No systemd. |
| Windows              | ✗ No systemd, no tmux. |

## Prerequisites

- Linux with systemd (Debian/Ubuntu primary)
- Root or sudo access (the script must write `/etc/systemd/system/`)
- Internet access (apt + npm + git fetches)
- ~1 GB RAM idle, ~5 GB disk for claude-code + node_modules + your repos
- Optional: a Telegram bot + chat ID (so URLs ping your phone)

## Install

```bash
curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/server/bootstrap.sh | bash
```

Idempotent - skips anything already installed. Re-run to upgrade.

What it does, in order:

1. **System packages** - installs (or skips) `tmux`, `git`, `python3`,
   `python3-pip`, `curl`, `ca-certificates` via apt.
2. **Node.js 20+** - installs from NodeSource if your existing version is
   too old.
3. **Python deps** - `rich` and `questionary` for the TUI (via pip,
   `--break-system-packages` if needed).
4. **claude-code** - `npm install -g @anthropic-ai/claude-code` if not
   already present.
5. **Repo clone** - clones (or pulls) this repo to `/data/dev/claudefarm`.
   Override location with `CLAUDEFARM_REPO=/path/to/your/clone bash bootstrap.sh`.
6. **Symlinks** - links the scripts into `/usr/local/bin/` and `/root/`.
   Existing files get backed up to `*.pre-claudefarm-<timestamp>.bak`.
7. **systemd template** - copies `claude-remote@.service` into
   `/etc/systemd/system/` and runs `daemon-reload`.
8. **Per-host config** - writes `/etc/claude-mgr.conf` with sensible
   defaults from your hostname + LAN IP. Edit to taste.
9. **Claude Code settings** - writes (or merges) `/root/.claude/settings.json`
   with the statusline command and `remoteControlAtStartup: true`.

## After install

Three interactive steps, in this order:

### 1. Set up Telegram (optional but recommended)

Drop a config at one of these paths so the wrapper script can ping URLs to you:

- `/root/.config/telegram_notify.json`
- `~/.nanobot/config.json`

Format:
```json
{
  "telegram_bot_token": "1234567890:ABC...",
  "telegram_chat_id": "987654321"
}
```

Bot creation: chat with [@BotFather](https://t.me/botfather), `/newbot`,
follow prompts, paste the token here. Get your chat ID by sending any
message to your new bot then visiting
`https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser.

You also need `/root/telegram_notify.py` itself - copy from another box,
or just write a small one that reads stdin and POSTs to
`api.telegram.org/bot{token}/sendMessage`.

### 2. Authenticate Claude Code

```bash
claude
```

Run it once interactively. It opens a browser flow (or prints a URL to
paste). Token gets stored in `/root/.claude/.credentials.json` - all
instances share it.

### 3. Spin up your first instance

```bash
claude-mgr
```

Pick "new instance", give it a name, choose a workdir. Done.

## Per-host config

`/etc/claude-mgr.conf` is sourced into the environment by
`/etc/profile.d/claude-mgr.sh` and read by `claude-mgr` at startup.

| Variable | What | Example |
|---|---|---|
| `CLAUDE_MGR_HOSTNAME`    | Short tag used in SSH alias names + tmux status bar | `k12`, `cabin`, `vps` |
| `CLAUDE_MGR_LAN_IP`      | IP your clients SSH into                            | `192.168.50.62` |
| `CLAUDE_MGR_SSH_USER`    | SSH user the client uses                            | `root` |
| `CLAUDE_MGR_RESTART_HOST`| Where the desktop should SSH to issue restarts      | same as LAN_IP, OR a Proxmox host |
| `CLAUDE_MGR_RESTART_VIA` | Prefix to wrap restart command in                   | empty (local), `pct exec 105 --` (LXC) |
| `CLAUDEFARM_REPO`        | Where the cloned repo lives on this server          | `/data/dev/claudefarm` |

After editing, log out + back in (or `source /etc/claude-mgr.conf`) and
run `claude-mgr sync-ssh` to regenerate the alias file with the new tag.

### Examples

**Bare-metal Linux box on your LAN, restarts itself:**
```bash
CLAUDE_MGR_HOSTNAME="cabin"
CLAUDE_MGR_LAN_IP="192.168.50.10"
CLAUDE_MGR_SSH_USER="root"
CLAUDE_MGR_RESTART_HOST="192.168.50.10"
CLAUDE_MGR_RESTART_VIA=""
CLAUDEFARM_REPO="/data/dev/claudefarm"
```

**Proxmox LXC where restarts go through `pct exec` on the host:**
```bash
CLAUDE_MGR_HOSTNAME="k12"
CLAUDE_MGR_LAN_IP="192.168.50.62"     # the LXC's IP
CLAUDE_MGR_SSH_USER="root"
CLAUDE_MGR_RESTART_HOST="192.168.50.55" # the Proxmox host
CLAUDE_MGR_RESTART_VIA="pct exec 105 --"
CLAUDEFARM_REPO="/data/dev/claudefarm"
```

## Usage

### TUI

```bash
claude-mgr
```

Centred Catppuccin Mocha box. Arrow keys navigate, enter chooses, q quits.

### CLI

```bash
claude-mgr list                              # plain text list of instances
claude-mgr start <name>                      # creates if needed, runs in /root
claude-mgr start <name> --workdir /path
claude-mgr start <name> --clone https://github.com/foo/bar.git
claude-mgr stop <name>
claude-mgr restart <name>                    # kills convo, fresh URL via Telegram
claude-mgr attach <name>                     # tmux attach
claude-mgr url <name>                        # last claude.ai URL captured
claude-mgr remove <name>                     # stop + disable, KEEP workdir
claude-mgr remove <name> --purge-workdir     # also delete workdir
claude-mgr sync-ssh                          # regenerate the alias file
```

Every `start`, `stop`, `restart`, `remove` auto-runs `sync-ssh` so the alias
file stays current. Commit + push the repo to share with clients.

## File reference

| File | Symlinked to | Role |
|---|---|---|
| `bootstrap.sh`                      | -                              | Idempotent installer / upgrader. Curl + bash. |
| `claude-mgr.py`                     | `/usr/local/bin/claude-mgr`    | TUI + CLI. Cathedral of menus + commands. |
| `claude-statusline.py`              | `/usr/local/bin/claude-statusline` | Per-instance Claude statusline (model, ctx %, cost, instance name). |
| `claude-remote-with-telegram.sh`    | `/usr/local/bin/claude-remote-with-telegram.sh` | Wrapper run by systemd. Spawns `claude` in tmux, scrapes URL, Telegrams. |
| `claude-remote@.service`            | `/etc/systemd/system/claude-remote@.service` | systemd template. One unit per instance: `claude-remote@<name>.service`. |
| `tmux.conf`                         | `/root/.tmux.conf`             | Catppuccin Mocha tmux config with Nerd Font icons. |
| `cheatsheet`                        | `/usr/local/bin/cheatsheet`    | Type `cheatsheet` for tmux + claude-mgr quick-ref. |

## Troubleshooting

### `claude-mgr: command not found`

The shell that's looking for it doesn't have `/usr/local/bin` on PATH (this
sometimes happens with `pct exec` or non-interactive SSH). Either use the
absolute path `/usr/local/bin/claude-mgr` or fix PATH in `/etc/profile`.

### Bootstrap fails at `pip install rich questionary`

If you're on Debian 12+ with PEP 668 (externally-managed python), pip will
refuse to install system-wide. The bootstrap passes `--break-system-packages`
to override - if that's still failing, run manually:
```bash
pip3 install --break-system-packages rich questionary
```

### Instance shows "running" but `tmux ls` is empty

The wrapper exited (probably because `claude` itself crashed or was
killed). Check `journalctl -u claude-remote@<name>.service -n 100` for
the underlying error. systemd will restart it after `RestartSec=15`.

### Telegram isn't receiving URLs

1. `/root/telegram_notify.py` exists and is executable.
2. Config has the right token + chat ID.
3. Manually test: `echo "test" | /root/telegram_notify.py`
4. Wrapper logs at `/var/log/claude-remote-<instance>.log`.

### Want to nuke and start over

```bash
systemctl list-units 'claude-remote@*.service' --no-legend | awk '{print $1}' | xargs -r systemctl stop
systemctl list-unit-files 'claude-remote@*.service' --no-legend | awk '{print $1}' | xargs -r systemctl disable
rm -rf /etc/systemd/system/claude-remote@*.service.d
systemctl daemon-reload
```

This stops + disables every instance and removes per-instance drop-ins.
The systemd template, scripts, and per-host config stay (re-run bootstrap to
restore them).

## Uninstall

There's no uninstall script. Manual cleanup:

```bash
# Stop + disable all instances
systemctl list-units 'claude-remote@*.service' --no-legend | awk '{print $1}' \
    | xargs -r systemctl disable --now

# Remove systemd unit + drop-ins
rm /etc/systemd/system/claude-remote@.service
rm -rf /etc/systemd/system/claude-remote@*.service.d
systemctl daemon-reload

# Remove symlinks
rm /usr/local/bin/{claude-mgr,claude-statusline,cheatsheet,claude-remote-with-telegram.sh}
rm /root/.tmux.conf

# Remove per-host config
rm /etc/claude-mgr.conf /etc/profile.d/claude-mgr.sh

# Remove repo clone (optional - keeps the source if you want to reinstall)
rm -rf /data/dev/claudefarm
```

claude-code and node + python stay - those have other uses.
