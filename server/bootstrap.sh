#!/bin/bash
# bootstrap.sh - install / refresh claude-mgr on a Linux machine.
#
# Idempotent: skips anything that's already in place. Re-running upgrades.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/Clinteastman/claudefarm/main/server/bootstrap.sh | bash
#
# Or, after cloning:
#   bash /data/dev/claudefarm/server/bootstrap.sh
#
# Prereqs: Debian/Ubuntu Linux, root (or sudo), internet access.
#
# SECURITY: this is a curl|bash installer that runs as root and pulls third-party
# install scripts (NodeSource, astral.sh) plus npm/pip packages, none pinned by
# hash. Inspect this script before running it, and pin to a tag/commit you trust
# rather than `main` if you want reproducibility. Set CLAUDE_CODE_VERSION to pin
# the claude-code npm version.

# pipefail so a failing leg of a pipeline (e.g. git pull | sed) is detectable;
# we intentionally do NOT use `set -e` here - the script relies on explicit
# `|| fail` guards and per-step conditionals, and a blanket errexit would make a
# benign non-zero abort a half-finished install.
set -uo pipefail

# ---------- Catppuccin Mocha for our messages -------------------------------
M='\033[38;2;203;166;247m'   # mauve
G='\033[38;2;166;227;161m'   # green
Y='\033[38;2;249;226;175m'   # yellow
R='\033[38;2;243;139;168m'   # red
S='\033[38;2;108;112;134m'   # overlay
B='\033[1m'
N='\033[0m'

step()  { printf "${M}${B}==>${N} ${B}%s${N}\n" "$*"; }
info()  { printf "    ${S}%s${N}\n" "$*"; }
ok()    { printf "    ${G}OK${N}  ${S}%s${N}\n" "$*"; }
skip()  { printf "    ${S}--${N}  ${S}%s (already done)${N}\n" "$*"; }
warn()  { printf "    ${Y}!!${N}  ${Y}%s${N}\n" "$*"; }
fail()  { printf "    ${R}xx${N}  ${R}%s${N}\n" "$*"; exit 1; }

# ---------- preflight --------------------------------------------------------

step "preflight"

[ "$(id -u)" = "0" ] || fail "must run as root (try sudo bash $0)"
command -v apt-get >/dev/null 2>&1 || fail "apt-get not found - this script targets Debian/Ubuntu"
ok "running as root on a Debian-family system"

# ---------- system packages --------------------------------------------------

step "system packages"

NEED_APT=()
for pkg in tmux git python3 python3-pip curl ca-certificates; do
  if dpkg -s "$pkg" >/dev/null 2>&1; then
    skip "$pkg"
  else
    NEED_APT+=("$pkg")
  fi
done
if [ "${#NEED_APT[@]}" -gt 0 ]; then
  info "installing: ${NEED_APT[*]}"
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${NEED_APT[@]}" >/dev/null
  ok "installed ${NEED_APT[*]}"
fi

# nodejs (for claude-code) - need v20+
# Robust major-version parse: a non-numeric `node -v` (nvm shim, custom build)
# must not crash the `-lt` test - default to 0 so we (re)install.
NODE_VERSION="$(node -v 2>/dev/null | sed -n 's/^v\([0-9]\+\).*/\1/p')"
NODE_VERSION="${NODE_VERSION:-0}"
if [ "$NODE_VERSION" -lt 20 ]; then
  info "installing Node.js 20.x (current: v$NODE_VERSION)"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
  ok "node $(node -v) installed"
else
  skip "node $(node -v) (>= 20)"
fi

# python deps for claude-mgr TUI
step "python deps for claude-mgr TUI"
NEED_PIP=()
for mod in rich questionary; do
  if python3 -c "import $mod" >/dev/null 2>&1; then
    skip "$mod"
  else
    NEED_PIP+=("$mod")
  fi
done
if [ "${#NEED_PIP[@]}" -gt 0 ]; then
  info "pip3 install ${NEED_PIP[*]}"
  pip3 install --break-system-packages --quiet "${NEED_PIP[@]}" \
    || pip3 install --quiet "${NEED_PIP[@]}" \
    || fail "pip install failed"
  ok "installed ${NEED_PIP[*]}"
fi

# ---------- claude-code ------------------------------------------------------

step "claude-code"
if command -v claude >/dev/null 2>&1; then
  skip "claude $(claude --version 2>/dev/null | head -1)"
else
  info "npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION:-latest}"
  npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION:-latest}"
  ok "claude $(claude --version 2>/dev/null | head -1) installed"
fi

# ---------- uv (per-instance venv tool) -------------------------------------

step "uv (per-instance Python venv tool)"
if command -v uv >/dev/null 2>&1; then
  skip "uv $(uv --version 2>/dev/null | awk '{print $2}')"
else
  info "installing uv from astral.sh"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh \
    || pip3 install --break-system-packages --quiet uv \
    || fail "uv install failed (tried both curl + pip)"
  ok "uv $(uv --version 2>/dev/null | awk '{print $2}') installed"
fi

# ---------- repo clone -------------------------------------------------------

REPO_PATH="${CLAUDEFARM_REPO:-/data/dev/claudefarm}"
REPO_URL="https://github.com/Clinteastman/claudefarm.git"

step "homelab repo at $REPO_PATH"
if [ -d "$REPO_PATH/.git" ]; then
  info "updating existing clone"
  git -C "$REPO_PATH" pull --ff-only --quiet 2>&1 | sed 's/^/        /'
  # Gate the OK on git's own exit (PIPESTATUS[0]) - sed always exits 0, so a
  # failed pull would otherwise print "repo up to date" and relink stale code.
  if [ "${PIPESTATUS[0]}" -eq 0 ]; then
    ok "repo up to date"
  else
    warn "git pull failed - continuing with the existing checkout (may be stale)"
  fi
else
  info "cloning $REPO_URL"
  mkdir -p "$(dirname "$REPO_PATH")"
  git clone --quiet "$REPO_URL" "$REPO_PATH"
  ok "cloned"
fi

MGR="$REPO_PATH/server"
[ -d "$MGR" ] || fail "$MGR not found - is the repo up to date?"

# ---------- symlinks ---------------------------------------------------------

step "symlinks"
declare -A LINKS=(
  ["/root/.tmux.conf"]="$MGR/tmux.conf"
  ["/usr/local/bin/cheatsheet"]="$MGR/cheatsheet"
  ["/usr/local/bin/claude-mgr"]="$MGR/claude-mgr.py"
  ["/usr/local/bin/claude-statusline"]="$MGR/claude-statusline.py"
  ["/usr/local/bin/claude-remote-with-telegram.sh"]="$MGR/claude-remote-with-telegram.sh"
  ["/usr/local/bin/osc52-copy"]="$MGR/osc52-copy"
)
for link in "${!LINKS[@]}"; do
  target="${LINKS[$link]}"
  current="$(readlink -f "$link" 2>/dev/null || echo "")"
  # Always assert the exec bit, even on the "already linked" skip path, so a
  # refresh run repairs a target that somehow lost +x.
  chmod +x "$target" 2>/dev/null || true
  if [ "$current" = "$(readlink -f "$target")" ]; then
    skip "$link -> $target"
  else
    if [ -e "$link" ] && [ ! -L "$link" ]; then
      bk="${link}.pre-claude-mgr-$(date +%s).bak"
      mv "$link" "$bk"
      info "backed up existing $link to $bk"
    fi
    ln -sfn "$target" "$link"
    ok "$link -> $target"
  fi
done

# ---------- systemd unit -----------------------------------------------------

step "systemd template"
SRC="$MGR/claude-remote@.service"
DST="/etc/systemd/system/claude-remote@.service"
if cmp -s "$SRC" "$DST" 2>/dev/null; then
  skip "$DST in sync"
else
  cp "$SRC" "$DST"
  systemctl daemon-reload
  ok "$DST installed + daemon-reloaded"
fi

# ---------- per-host config --------------------------------------------------

step "per-host config (/etc/claude-mgr.conf)"
CONF="/etc/claude-mgr.conf"
HOSTNAME_TAG_DEFAULT="$(hostname -s)"
LAN_IP_DEFAULT="$(hostname -I | awk '{print $1}')"

if [ -f "$CONF" ]; then
  skip "$CONF (delete it to reconfigure)"
else
  cat > "$CONF" <<EOF
# claude-mgr per-host config. Sourced by /etc/profile.d/claude-mgr.sh and
# read by claude-mgr at runtime. Edit and re-source ~/.bashrc to apply.

# Short hostname tag used in SSH alias names and the tmux status bar.
CLAUDE_MGR_HOSTNAME="$HOSTNAME_TAG_DEFAULT"

# LAN IP used as the HostName in generated SSH aliases (so your desktop
# can ssh claude-<hostname>-<instance>).
CLAUDE_MGR_LAN_IP="$LAN_IP_DEFAULT"

# SSH user the desktop should use to attach.
CLAUDE_MGR_SSH_USER="root"

# How to restart instances from the desktop. Two options:
#   1. Local systemd:     CLAUDE_MGR_RESTART_HOST="<this LAN_IP>"; CLAUDE_MGR_RESTART_VIA=""
#   2. Via Proxmox host:  CLAUDE_MGR_RESTART_HOST="<proxmox IP>";  CLAUDE_MGR_RESTART_VIA="pct exec <ctid> --"
CLAUDE_MGR_RESTART_HOST="$LAN_IP_DEFAULT"
CLAUDE_MGR_RESTART_VIA=""

# Where the homelab repo lives on this machine (so claude-mgr can write
# the auto-synced SSH alias file there).
CLAUDEFARM_REPO="$REPO_PATH"

# Tell apps in interactive shells that the terminal does 24-bit color.
# The systemd template sets the same value for claudefarm-spawned
# sessions; this line is for when you SSH in and run `claude` (or any
# other TUI) directly.
COLORTERM=truecolor

# Optional extras: anything you set here gets exported into every Claude
# instance's environment via systemd EnvironmentFile=. Useful for tools
# like the gscontent 'preview' command that need PREVIEW_URL_BASE +
# PREVIEW_DIR set in the Claude shell.
#
# PREVIEW_URL_BASE="https://preview.example.com"
# PREVIEW_DIR="/data/dev/_preview"
EOF
  ok "wrote $CONF (review and edit as needed)"
fi

# Make the config available in every login shell
PROF="/etc/profile.d/claude-mgr.sh"
if [ ! -f "$PROF" ]; then
  cat > "$PROF" <<'EOF'
# Auto-loaded for all interactive shells. Sources /etc/claude-mgr.conf so
# claude-mgr picks up the per-host settings without needing them in the
# environment of every caller.
[ -r /etc/claude-mgr.conf ] && set -a && . /etc/claude-mgr.conf && set +a
EOF
  ok "wrote $PROF"
else
  skip "$PROF"
fi

# ---------- /root/.claude/settings.json --------------------------------------

step "claude code settings"
SETTINGS="/root/.claude/settings.json"
mkdir -p "$(dirname "$SETTINGS")"
if [ ! -f "$SETTINGS" ]; then
  # NOTE (security posture): this default is UNATTENDED-FRIENDLY but permissive -
  # every instance runs Claude as root with auto-approve (defaultMode=auto +
  # skipAutoPermissionPrompt) and remote control on, so a prompt-injected agent
  # can take destructive root actions with no human gate. That is intentional for
  # this homelab's remote-control workflow. To require manual approval instead,
  # set defaultMode to "default" and remove skipAutoPermissionPrompt below.
  cat > "$SETTINGS" <<'EOF'
{
  "permissions": { "defaultMode": "auto" },
  "theme": "dark",
  "remoteControlAtStartup": true,
  "skipAutoPermissionPrompt": true,
  "agentPushNotifEnabled": true,
  "statusLine": {
    "type": "command",
    "command": "/usr/local/bin/claude-statusline"
  }
}
EOF
  ok "wrote $SETTINGS"
elif ! grep -q '"statusLine"' "$SETTINGS"; then
  python3 - <<PY
import json, sys
from pathlib import Path
p = Path("$SETTINGS")
try:
    s = json.loads(p.read_text())
except (json.JSONDecodeError, OSError) as e:
    sys.stderr.write(f"settings.json is not valid JSON ({e}); leaving it untouched\n")
    sys.exit(0)
s.setdefault("statusLine", {"type": "command", "command": "/usr/local/bin/claude-statusline"})
p.write_text(json.dumps(s, indent=2) + "\n")
PY
  ok "added statusLine block to $SETTINGS (or left a hand-edited invalid file untouched)"
else
  skip "$SETTINGS (statusLine already present)"
fi

# ---------- next steps -------------------------------------------------------

step "done"
cat <<EOF

  ${G}${B}Install / refresh complete.${N}

  Next steps (interactive, do these once per machine):

    ${B}1.${N} Edit per-host config if needed:
         ${S}sudo \$EDITOR /etc/claude-mgr.conf${N}

    ${B}2.${N} Set up Telegram (so instance URLs ping your phone):
         drop a config at /root/.config/telegram_notify.json with
         your bot token and chat id, then ensure /root/telegram_notify.py
         exists (copy from another box or fetch from the homelab repo).

    ${B}3.${N} Run ${B}claude${N} once interactively to log into your Anthropic
         account. The token is stored in /root/.claude.

    ${B}4.${N} Run ${B}claude-mgr${N} to spin up your first instance.

    ${B}5.${N} On your desktop ~/.ssh/config, add a single Include line so
         every machine's instances appear as SSH aliases:
         ${S}Include $REPO_PATH/client/claude-instances-*.cfg${N}

  ${S}For the cheatsheet of commands and tmux key bindings: type ${N}${B}cheatsheet${N}

EOF
