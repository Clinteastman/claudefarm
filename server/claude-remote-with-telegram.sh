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

# Auto-activate per-instance Python venv if one exists at <workdir>/.venv.
# claude-mgr creates this on instance startup for non-default workdirs so
# `pip install` from inside Claude doesn't pollute the system Python.
if [ -f "$WORKDIR/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    . "$WORKDIR/.venv/bin/activate"
    echo "[$(date -Is)] activated venv at $WORKDIR/.venv" | tee -a "$LOG"
fi

# Build a list of -e flags so any env var the systemd unit handed us
# (CLAUDE_*, PREVIEW_*, TELEGRAM_*, plus VIRTUAL_ENV/PATH from venv) reaches
# the new tmux session and therefore Claude. Without this, only what we name
# explicitly survives - tmux servers shared across instances don't
# auto-propagate the wrapper's env to new sessions.
TMUX_ENV_ARGS=(-e "CLAUDE_INSTANCE=$INSTANCE")

# In agents mode, set CLAUDE_AGENTS_PARENT so the awtrix hooks know to
# route their state writes to <STATE_DIR>/<parent>/<pid>.json (the
# aggregator merges those by max-priority for one parent tile).
if [ "${CLAUDE_MODE:-code}" = "agents" ]; then
    TMUX_ENV_ARGS+=(-e "CLAUDE_AGENTS_PARENT=$INSTANCE")
    # Seed an idle placeholder so the parent tile appears immediately,
    # even before any agents have been dispatched. PID 0 reserved for
    # the wrapper itself.
    mkdir -p "/run/claude-status/$INSTANCE"
    printf '{"instance":"wrapper","state":"idle","ts":%d}\n' "$(date +%s)" \
        > "/run/claude-status/$INSTANCE/0.json" || true
fi
while IFS= read -r _name; do
    [ -n "${_name:-}" ] && TMUX_ENV_ARGS+=(-e "${_name}=${!_name}")
done < <(env | awk -F= '/^(PREVIEW_|TELEGRAM_|CLAUDEFARM_|CLAUDE_MGR_|VIRTUAL_ENV|PATH)/ {print $1}')

# Mode: "code" (default - single Claude Code session, gets its own
# claude.ai Remote Control URL) or "agents" (the new `claude agents`
# multi-agent TUI from Claude Code v2.1.139+; each dispatched agent
# inside it gets its own URL, the wrapper doesn't capture one).
MODE="${CLAUDE_MODE:-code}"
if [ "$MODE" = "agents" ]; then
    INNER_CMD="claude agents"
    echo "[$(date -Is)] mode=agents; running 'claude agents'" | tee -a "$LOG"
else
    INNER_CMD="claude --name \"$SESSION_NAME\""
    echo "[$(date -Is)] mode=code; running 'claude --name ...'" | tee -a "$LOG"
fi

tmux new-session -d -s "$SESSION" "${TMUX_ENV_ARGS[@]}" "$INNER_CMD"
tmux set-option -t "$SESSION" -g window-size latest 2>/dev/null || true
tmux set-option -t "$SESSION" -w aggressive-resize on 2>/dev/null || true

# Wait for the claude.ai Remote Control URL to surface in the pane (up
# to ~90s). Only meaningful in code mode; in agents mode the surrounding
# session has no URL of its own (each dispatched agent has its own).
URL=""
if [ "$MODE" = "code" ]; then
  for i in $(seq 1 45); do
    sleep 2
    PANE=$(tmux capture-pane -t "$SESSION" -p 2>/dev/null || true)
    URL=$(echo "$PANE" | grep -oE 'https://claude\.ai[a-zA-Z0-9./_?=&%+-]+' | head -1)
    [[ -n "$URL" ]] && break
  done
fi

if [ "$MODE" = "agents" ]; then
  MSG="LXC 105 Claude instance '${INSTANCE}' (re)started in AGENTS mode.

This session is the 'claude agents' multi-agent TUI. Dispatch agents
from inside; each dispatched agent has its own claude.ai URL shown in
the peek panel (Space).

Terminal: ssh claude-${INSTANCE}  (or: ssh root@192.168.50.62 -t tmux a -t $SESSION)
Workdir: ${WORKDIR}

Detach from tmux with Ctrl+b then d (do NOT Ctrl+C - that kills the TUI)."
else
  MSG="LXC 105 Claude instance '${INSTANCE}' (re)started.

Phone/desktop app: ${URL:-NO URL CAPTURED - check tmux}
Terminal: ssh claude-${INSTANCE}  (or: ssh root@192.168.50.62 -t tmux a -t $SESSION)
Workdir: ${WORKDIR}

Detach from tmux with Ctrl+b then d (do NOT Ctrl+C - that kills claude)."
fi

/root/telegram_notify.py "$MSG" >>/var/log/claude-remote-telegram.log 2>&1 || \
  echo "[$(date -Is)] Telegram failed" | tee -a "$LOG"

echo "[$(date -Is)] URL=${URL:-none}; entering watchdog loop for instance=$INSTANCE" | tee -a "$LOG"

# Keep this script alive so systemd treats us as the long-running unit.
# Exit when the tmux session dies, so systemd restarts us.
while tmux has-session -t "$SESSION" 2>/dev/null; do
  sleep 30
done

echo "[$(date -Is)] tmux session $SESSION ended; exiting for systemd restart" | tee -a "$LOG"
