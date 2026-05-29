# client/

Everything that turns a laptop / desktop into a control terminal for Claude
instances running on a [server](../server/README.md).

The client side is **just SSH plumbing**: a clone of this repo (so you have
the auto-generated alias files), an Include line in your `~/.ssh/config`,
and your pubkey on the server. No claude-mgr, no systemd, no Python deps.

Works on Linux, macOS, and Windows.

## Quick install

| Platform | One-liner |
|---|---|
| **Linux** (Debian/Ubuntu/Fedora/...) | `curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/client/setup-client.sh \| bash` |
| **macOS** | `curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/client/setup-client.sh \| bash` |
| **Windows** (PowerShell 5+) | `iwr -useb https://raw.githubusercontent.com/Clinteastman/claudefarm/main/client/setup-client.ps1 \| iex` |

All three are idempotent - safe to re-run any time. They:

1. Clone (or pull) this repo to `~/github/claudefarm` (override path interactively)
2. Find or generate an SSH key (ed25519, no passphrase)
3. Add the right `Include` line at the top of your SSH config
4. Try to copy your pubkey to the server (you'll be prompted for the server's password once)
5. Test the connection
6. Print the SSH aliases you can now use

## Per-platform install (the long form)

### Linux

```bash
curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/client/setup-client.sh | bash
```

Prereqs: `git`, `ssh`, `ssh-keygen`. On Debian/Ubuntu: `sudo apt install git openssh-client`.

The script will prompt for clone location, ask before generating a key,
ask before copying the pubkey to the server. Defaults to K12
(`192.168.50.62`) - override with env vars before piping:

```bash
K12_HOST=10.0.0.5 K12_USER=pi curl -sSL ... | bash
```

### macOS

Same as Linux - macOS ships with `git` (via Xcode CLT or Homebrew) and
OpenSSH out of the box.

```bash
curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/client/setup-client.sh | bash
```

If you've never used git before, macOS will prompt to install Xcode Command
Line Tools - accept it.

### Windows (PowerShell)

```powershell
iwr -useb https://raw.githubusercontent.com/Clinteastman/claudefarm/main/client/setup-client.ps1 | iex
```

Prereqs: PowerShell 5+, `git`, OpenSSH client. Install with:

```powershell
winget install Git.Git Microsoft.OpenSSH.Beta
```

(OpenSSH client is pre-installed on Windows 10 1809+ but `Microsoft.OpenSSH.Beta` is more current.)

To pass non-default settings, download and run with parameters:

```powershell
iwr -useb https://raw.githubusercontent.com/Clinteastman/claudefarm/main/client/setup-client.ps1 -OutFile setup.ps1
.\setup.ps1 -ServerHost 10.0.0.5 -ServerUser pi -RepoPath C:\projects\claudefarm
```

### Manual install (any platform)

If you'd rather skip the script:

1. **Clone the repo** anywhere convenient. The default in our scripts is
   `~/github/claudefarm` (Unix) or `%USERPROFILE%\github\claudefarm` (Windows).
   ```bash
   git clone https://github.com/Clinteastman/claudefarm.git ~/github/claudefarm
   ```

2. **Add the Include line** at the **TOP** of your SSH config (BEFORE any
   `Host` blocks - position matters, the Include leaks Host scope if it's
   inside one):
   - Linux/macOS: `~/.ssh/config`
   - Windows: `%USERPROFILE%\.ssh\config`

   Line to add:
   ```
   Include ~/github/claudefarm/client/claude-instances-*.cfg
   ```
   (Adjust the path if you cloned elsewhere. On Windows use forward slashes
   anyway, OpenSSH for Windows accepts them.)

3. **Authorise your pubkey** on the server. Easiest way from a Unix client:
   ```bash
   ssh-copy-id root@<server-ip>
   ```
   On Windows or if `ssh-copy-id` isn't available:
   ```powershell
   type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@<server-ip> "cat >> ~/.ssh/authorized_keys"
   ```

4. **Test**:
   ```bash
   ssh claude-<server-tag>-<instance>
   # e.g. ssh claude-k12-main
   ```

## Usage

### Attach to an instance

```bash
ssh claude-<server>-<instance>
```

Detach with `Ctrl+b d` (NOT Ctrl+C - that kills Claude). Re-attach any
time. The conversation stays exactly where you left it.

Examples (with K12 as the server tag):
- `ssh claude-k12-main`
- `ssh claude-k12-homelab`
- `ssh claude-k12-gscontent`

### Open the manager TUI

```bash
ssh claude-mgr-<server>
# e.g. ssh claude-mgr-k12
```

This is just a normal SSH alias that runs `claude-mgr` on the server with
a TTY. Use it to start / stop / restart / create instances from any client.

### Restart an instance from the client

```bash
ssh claude-restart-<server>-<instance>
```

Kills the current Claude conversation, starts a fresh one, and sends a
Telegram notification. Useful when you want a clean slate.

## Refreshing aliases

When the server creates or removes instances, it commits the updated
`client/claude-instances-<server>.cfg` file. Pull in your local clone to
pick up the changes:

```bash
git -C ~/github/claudefarm pull   # Linux/macOS
```

```powershell
git -C $env:USERPROFILE\github\claudefarm pull   # Windows
```

Optional: drop a cron entry / scheduled task to auto-pull every minute so
new aliases appear without you noticing.

## Multiple servers

Got more than one machine running claude-mgr? Each server writes its own
file:

```
client/
├── claude-instances-k12.cfg       (from K12 LXC)
├── claude-instances-cabin.cfg     (from cabin Pi)
├── claude-instances-vps.cfg       (from cloud VPS)
```

The Include in your SSH config is a **glob** (`claude-instances-*.cfg`) so
adding more servers requires zero client changes. You'll just see
`ssh claude-cabin-main` and `ssh claude-vps-main` start working when those
servers' files appear in the next `git pull`.

## Files in this directory

| File | Role |
|---|---|
| `setup-client.sh` | Linux + macOS installer (bash) |
| `setup-client.ps1` | Windows installer (PowerShell) |
| `claude-statusline.py` | Optional Catppuccin statusline for your **local** Claude Code (not for instances on the server). Run-time configurable via `~/.claude/settings.json`. |
| `ssh-config.example` | Sample `~/.ssh/config` showing the Include line in context. |
| `claude-instances-<host>.cfg` | Auto-generated. One per server. Don't edit. |

## Troubleshooting

### `ssh: Could not resolve hostname claude-k12-main`

Your SSH config doesn't have the Include line, OR it's not at the top of
the file (anything below a `Host` block gets nested inside that block's
scope). Move the Include to the very top.

Verify by running `ssh -G claude-k12-main` - it should print
`hostname 192.168.50.62` (or your server's IP). If it prints
`hostname claude-k12-main` instead, the alias isn't being picked up.

### "Permission denied (publickey)"

Your pubkey isn't on the server. Re-run the installer (it's idempotent and
will offer to copy the key again), or do it manually:

```bash
ssh-copy-id root@<server-ip>                                          # Linux/macOS
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@<server-ip> "cat >> ~/.ssh/authorized_keys"   # Windows
```

### "claude-<x> tmux session not running on <host>"

The server's Claude instance isn't running. SSH to the server's manager
and check:
```bash
ssh claude-mgr-<server>
# In the TUI, look at the state column - if it's not 'running' the
# systemd unit failed. Restart from the menu.
```

Or check from a shell on the server:
```bash
systemctl status claude-remote@<instance>.service
journalctl -u claude-remote@<instance>.service -n 100
```

### Aliases haven't updated after the server created a new instance

Run `git pull` in your local clone. The aliases live in this repo - they
don't propagate over the network in real time, only via git.

### CRLF / line-ending errors on Linux/macOS

If you cloned the repo on Windows first and synced via cloud, you may have
CRLF endings. Run inside the clone:

```bash
git config --global core.autocrlf input    # then re-clone
# or fix in place:
find . -type f \( -name '*.sh' -o -name '*.cfg' -o -name '*.py' \) -exec sed -i 's/\r$//' {} +
```

The repo's `.gitattributes` enforces LF on these files going forward.

### The Catppuccin TUI shows boxes instead of icons

Your terminal's font doesn't have Nerd Font glyphs. Install one:

- **Windows Terminal**: `winget install Microsoft.CascadiaCode` then set the
  font in Settings to `Cascadia Code NF` or `Cascadia Mono NF`.
- **macOS Terminal / iTerm2**: download a Nerd Font from
  https://www.nerdfonts.com/font-downloads and set it as the terminal font.
- **Linux**: `sudo apt install fonts-cascadia-code` (or download Nerd Fonts
  manually) - then set the terminal font.

Recommended fonts: CaskaydiaCove Nerd Font, JetBrainsMono Nerd Font,
FiraCode Nerd Font.

The colours work without a Nerd Font - only the icons render as boxes.

## Pasting screenshots OR files into a remote Claude (paste-image hotkey)

Claude Code's local Alt+V (paste image) and drag-drop (paste file) only
work when Claude is running locally - over SSH the remote Claude can't
see your client's clipboard or local files. This bundle ships one hotkey
that handles both cases:

**Screenshots**:
1. Take a screenshot the way you always do (Win+Shift+S, PrtSc, Spectacle,
   Cmd+Shift+4 + Ctrl-to-clipboard, etc).
2. Press the bound hotkey.
3. PNG is SCP'd to `<server>:/data/dev/_paste/<timestamp>.png` and the
   path is typed into the focused window.

**Files** (CSVs, zips, PDFs, anything you'd normally drag-drop into Claude):
1. Select file(s) in your file manager and Ctrl+C (or Cmd+C on Mac).
2. Press the same hotkey.
3. Each file is SCP'd to `<server>:/data/dev/_paste/<ts>-N-<original-name>`
   and the paths get typed in space-separated.

Either way: hit Enter, ask Claude to look at it. End-to-end ~2 seconds for
small files, longer for big ones. Path(s) also land on your clipboard as
a fallback. Server-side `/data/dev/_paste/` auto-cleans files older than 7
days, so the staging area never balloons.

### Windows

The PowerShell script `paste-image.ps1` does the work; bind it to a hotkey
via either of these:

**Option A: AutoHotkey (recommended)**

1. Install AutoHotkey v2 from https://www.autohotkey.com/v2/
2. Edit `paste-image.ahk` if your repo is somewhere other than `~/github/claudefarm`
3. Double-click `paste-image.ahk` to load. Drop a shortcut into
   `shell:startup` (Win+R) for autoload at login.

Default hotkey: **Win+Shift+V**.

> **Why not Ctrl+Alt+V?** On UK / international keyboards Windows treats
> Ctrl+Alt as AltGr, and AltGr+V types ®. If the script ever fails to
> load you'd accidentally spam ® into your terminal. Win+Shift+V has no
> default OS binding so it's safe regardless.

**Option B: PowerToys Keyboard Manager**

1. Install Microsoft PowerToys from https://aka.ms/powertoys
2. Settings -> Keyboard Manager -> Remap shortcut
3. Map your hotkey of choice to: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\<you>\github\claudefarm\client\paste-image.ps1"`

### Linux

Install the right clipboard + auto-type tools for your session:

```bash
# X11 (most distros, GNOME-on-Xorg, i3, etc.)
sudo apt install xclip xdotool

# Wayland (GNOME 40+, Sway, KDE Wayland session)
sudo apt install wl-clipboard wtype
```

Bind the hotkey via your DE:

| DE | Where |
|---|---|
| GNOME | Settings -> Keyboard -> Custom Shortcuts -> Add. Command: `~/github/claudefarm/client/paste-image.sh` |
| KDE | System Settings -> Shortcuts -> Custom Shortcuts -> Edit -> New -> Global Shortcut -> Command/URL |
| i3/sway | `bindsym Ctrl+Mod1+v exec ~/github/claudefarm/client/paste-image.sh` in your config |
| XFCE | Settings -> Keyboard -> Application Shortcuts -> Add |

Suggested hotkey: **Super+Shift+V** (avoids the AltGr+V conflict that
generates ® on UK / international layouts).

### macOS

Install nothing - `osascript` and `pbpaste`/`pbcopy` ship with macOS.
Bind the hotkey via:

**Option A: Raycast / Alfred / Hammerspoon**
Bind a hotkey to run `~/github/claudefarm/client/paste-image.sh`.

**Option B: Built-in Automator + System Settings**
1. Automator -> New -> Quick Action
2. Add "Run Shell Script" -> `~/github/claudefarm/client/paste-image.sh`
3. Save as "Paste image to claudefarm"
4. System Settings -> Keyboard -> Keyboard Shortcuts -> Services -> bind a hotkey

You'll likely need to grant **Accessibility** permission to your terminal
the first time auto-type runs (System Settings -> Privacy & Security ->
Accessibility) - macOS prompts for it.

### Configuration (all platforms)

Defaults target K12 (`192.168.50.62`, root, `/data/dev/_paste`). Override via
env vars (Linux/macOS) or script parameters (Windows):

```bash
# Linux/macOS - export before running, e.g. via your shortcut command
PASTE_SERVER_HOST=10.0.0.5 PASTE_SERVER_USER=pi ~/github/claudefarm/client/paste-image.sh
```

```powershell
# Windows - pass as parameters
.\paste-image.ps1 -ServerHost 10.0.0.5 -ServerUser pi -RemoteDir /tmp/paste
```

### Troubleshooting

**"SCP to ... failed"** - your pubkey isn't on the server. Re-run
`setup-client.sh` / `setup-client.ps1` (it offers to copy your key) or
do it manually with `ssh-copy-id`.

**Path appears in the wrong window** - SendKeys / xdotool types into
whatever window has focus when the script finishes. Make sure you don't
click away after pressing the hotkey. The path is also on your clipboard
- just `Ctrl+V` it where you actually wanted it.

**"no image on the clipboard"** - your screenshot tool put the image in
some other format than PNG. Win+Shift+S → screenshot toolbar → click the
notification (which keeps it on clipboard) usually works. Some Linux
screenshot tools save to file but don't put on clipboard - check tool
settings.

## Optional: local Claude statusline

`claude-statusline.py` in this directory is a Catppuccin Mocha statusline
for the Claude Code you run **locally** on this machine (not for the
remote instances on the server - those have their own statusline shipped
with `server/`).

To wire it in, add this to `~/.claude/settings.json` (Linux/macOS) or
`%USERPROFILE%\.claude\settings.json` (Windows):

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 /full/path/to/claudefarm/client/claude-statusline.py"
  }
}
```

Shows model, context %, cost, 5-hour rate-limit (when high), worktree, vim
mode, and output style.
