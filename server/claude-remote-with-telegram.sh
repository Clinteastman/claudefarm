#!/bin/bash
# Spawns one interactive `claude` instance inside its own tmux session.
# `remoteControlAtStartup=true` in settings.json makes that session register
# with Anthropic Remote Control so phone/desktop app reach the SAME conversation
# that ssh+tmux attaches to. Telegrams the URL on each (re)start.
# Designed for systemd Restart=always.
#
# Usage: claude-remote-with-telegram.sh <instance>
#   <instance>: short label (e.g. main, dev, personal). Tmux session and
#               claude --name will both incorporate this label, so multiple
#               instances coexist without collision.
#
# Run via the systemd template: claude-remote@<instance>.service
#   systemctl enable --now claude-remote@main
#   systemctl enable --now claude-remote@dev
#   systemctl enable --now claude-remote@personal

set -u

INSTANCE="${1:-main}"
SESSION="claude-${INSTANCE}"
SESSION_NAME="LXC-105-${INSTANCE}"
WORKDIR="${CLAUDE_WORKDIR:-/root}"
LOG="/var/log/claude-remote-${INSTANCE}.log"

echo "[$(date -Is)] Wrapper starting; instance=$INSTANCE tmux=$SESSION workdir=$WORKDIR" | tee -a "$LOG"

# Clean any stale session for THIS instance only (don't disturb sibling instances)
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Start interactive claude inside a detached tmux session.
# Workspace trust is per-directory; the chosen workdir must be pre-trusted.
# To use a different workdir, set CLAUDE_WORKDIR=/path in the systemd unit
# (or environment file) and ssh in once to accept trust on first run.
cd "$WORKDIR"

# `tmux -e` propagates the env var into the new session so the Claude
# Code statusline can show which K12 instance is running here.
tmux new-session -d -s "$SESSION" -e "CLAUDE_INSTANCE=$INSTANCE" "claude --name \"$SESSION_NAME\""
tmux set-option -t "$SESSION" -g window-size latest 2>/dev/null || true
tmux set-option -t "$SESSION" -w aggressive-resize on 2>/dev/null || true

# Wait for the claude.ai Remote Control URL to surface in the pane (up to ~90s).
URL=""
for i in $(seq 1 45); do
  sleep 2
  PANE=$(tmux capture-pane -t "$SESSION" -p 2>/dev/null || true)
  URL=$(echo "$PANE" | grep -oE 'https://claude\.ai[a-zA-Z0-9./_?=&%+-]+' | head -1)
  [[ -n "$URL" ]] && break
done

MSG="LXC 105 Claude instance '${INSTANCE}' (re)started.

Phone/desktop app: ${URL:-NO URL CAPTURED - check tmux}
Terminal: ssh claude-${INSTANCE}  (or: ssh root@192.168.50.62 -t tmux a -t $SESSION)
Workdir: ${WORKDIR}

Detach from tmux with Ctrl+b then d (do NOT Ctrl+C - that kills claude)."

/root/telegram_notify.py "$MSG" >>/var/log/claude-remote-telegram.log 2>&1 || \
  echo "[$(date -Is)] Telegram failed" | tee -a "$LOG"

echo "[$(date -Is)] URL=${URL:-none}; entering watchdog loop for instance=$INSTANCE" | tee -a "$LOG"

# Keep this script alive so systemd treats us as the long-running unit.
# Exit when the tmux session dies, so systemd restarts us.
while tmux has-session -t "$SESSION" 2>/dev/null; do
  sleep 30
done

echo "[$(date -Is)] tmux session $SESSION ended; exiting for systemd restart" | tee -a "$LOG"
