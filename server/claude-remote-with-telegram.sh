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

# Validate the instance name even though systemd normally hands us a
# claude-mgr-validated %i: a hostile $1 flows into the tmux session name, into
# paths under /root/.claude-instances and /run/claude-status, and into the
# inner command. Same charset as claude-mgr's NAME_RE (must start [a-z0-9]).
case "$INSTANCE" in
    ''|[!a-z0-9]*|*[!a-z0-9_-]*)
        echo "claude-remote: invalid instance name '$INSTANCE'" >&2
        exit 2 ;;
esac

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
cd "$WORKDIR" || {
    echo "[$(date -Is)] cannot cd to workdir '$WORKDIR'; aborting for systemd restart" | tee -a "$LOG"
    exit 1
}

# Auto-activate per-instance Python venv if one exists at <workdir>/.venv.
# claude-mgr creates this on instance startup for non-default workdirs so
# `pip install` from inside Claude doesn't pollute the system Python.
if [ -f "$WORKDIR/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    . "$WORKDIR/.venv/bin/activate"
    echo "[$(date -Is)] activated venv at $WORKDIR/.venv" | tee -a "$LOG"
fi

# Per-instance Claude config dir. All instances run as root (HOME=/root), so
# without this they share /root/.claude - including the agent-view SUPERVISOR
# (daemon/roster.json + the IPC sockets in daemon/). That shared supervisor is
# why `claude agents` in one instance ingests a plain `claude` session from
# another instance and then both crash. Isolate the config dir per instance and
# share only the login + settings from the canonical /root/.claude.
CANON="/root/.claude"
CLAUDE_CONFIG_DIR="/root/.claude-instances/$INSTANCE"
export CLAUDE_CONFIG_DIR
# Create the per-instance dir private (umask 077): it holds an OAuth/app-state
# copy plus symlinks to the login token.
(umask 077; mkdir -p "$CLAUDE_CONFIG_DIR")
chmod 700 /root/.claude-instances "$CLAUDE_CONFIG_DIR" 2>/dev/null || true
# Login token + settings: SYMLINK to canonical so a re-login (token refresh) or
# a settings.json edit propagates to every instance automatically.
for _f in .credentials.json settings.json; do
    if [ -e "$CANON/$_f" ] && [ ! -e "$CLAUDE_CONFIG_DIR/$_f" ]; then
        ln -s "$CANON/$_f" "$CLAUDE_CONFIG_DIR/$_f"
    fi
done
# App state (.claude.json: onboarding / workspace-trust, mutated per instance):
# copy ONCE, kept private. NB: a re-login does NOT refresh these copies - wipe
# /root/.claude-instances/*/.claude.json after rotating credentials.
if [ -e "$CANON/.claude.json" ] && [ ! -e "$CLAUDE_CONFIG_DIR/.claude.json" ]; then
    cp "$CANON/.claude.json" "$CLAUDE_CONFIG_DIR/.claude.json"
    chmod 600 "$CLAUDE_CONFIG_DIR/.claude.json" 2>/dev/null || true
fi
echo "[$(date -Is)] CLAUDE_CONFIG_DIR=$CLAUDE_CONFIG_DIR" | tee -a "$LOG"

# Build a list of -e flags so any env var the systemd unit handed us
# (CLAUDE_*, PREVIEW_*, TELEGRAM_*, plus VIRTUAL_ENV/PATH from venv) reaches
# the new tmux session and therefore Claude. Without this, only what we name
# explicitly survives - tmux servers shared across instances don't
# auto-propagate the wrapper's env to new sessions.
TMUX_ENV_ARGS=(-e "CLAUDE_INSTANCE=$INSTANCE" -e "CLAUDE_CONFIG_DIR=$CLAUDE_CONFIG_DIR")

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
done < <(env | awk -F= '/^(PREVIEW_|TELEGRAM_|CLAUDEFARM_|CLAUDE_MGR_|HONCHO_|VIRTUAL_ENV)/ {print $1} /^(PATH|HOME|COLORTERM)=/ {print $1}')

# Mode: "code" (default - single Claude Code session, gets its own
# claude.ai Remote Control URL) or "agents" (the new `claude agents`
# multi-agent TUI from Claude Code v2.1.139+; each dispatched agent
# inside it gets its own URL, the wrapper doesn't capture one).
MODE="${CLAUDE_MODE:-code}"
if [ "$MODE" = "agents" ]; then
    INNER_CMD=(claude agents)
    echo "[$(date -Is)] mode=agents; running 'claude agents'" | tee -a "$LOG"
else
    INNER_CMD=(claude --name "$SESSION_NAME")
    echo "[$(date -Is)] mode=code; running 'claude --name ...'" | tee -a "$LOG"
fi

# Pass the command as an argv array (not one string) so tmux execs it directly
# instead of via `sh -c`, and -c so the pane starts in the workdir.
tmux new-session -d -s "$SESSION" -c "$WORKDIR" "${TMUX_ENV_ARGS[@]}" "${INNER_CMD[@]}"
tmux set-option -t "$SESSION" window-size latest 2>/dev/null || true
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

  # Fail fast if URL never surfaced: claude likely crashed or got stuck on
  # auth. Exit non-zero so systemd restarts us instead of leaving the unit
  # "active" with a broken claude inside.
  if [ -z "$URL" ]; then
    echo "[$(date -Is)] no claude.ai URL after 90s; treating as failed start, exiting for systemd restart" | tee -a "$LOG"
    /root/telegram_notify.py "LXC 105 Claude instance '${INSTANCE}' failed to start (no URL captured after 90s); systemd will retry." \
      >>/var/log/claude-remote-telegram.log 2>&1 || true
    tmux kill-session -t "$SESSION" 2>/dev/null || true
    exit 1
  fi
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
# Exit when the tmux session dies OR when claude crashes inside it
# (leaving the pane on a shell instead of the claude process), so systemd
# restarts us.
BAD_SAMPLES=0
while tmux has-session -t "$SESSION" 2>/dev/null; do
  sleep 30

  # Liveness: at least one pane's current command should still be claude (or its
  # node/bun runtime). Require TWO consecutive bad samples before acting so a
  # momentary drop to a shell (a user's Ctrl+Z, a transient subprocess) doesn't
  # kill a live session and destroy in-flight conversation state. Check ALL
  # panes, not just the first - a split with claude not listed first is healthy.
  PANE_CMDS=$(tmux list-panes -t "$SESSION" -F '#{pane_current_command}' 2>/dev/null)
  if [ -z "$PANE_CMDS" ]; then
    continue  # session vanished mid-check; has-session catches it next loop
  fi
  if echo "$PANE_CMDS" | grep -qE '^(node|claude|claude\.exe|bun)$'; then
    BAD_SAMPLES=0
    continue
  fi
  BAD_SAMPLES=$((BAD_SAMPLES + 1))
  if [ "$BAD_SAMPLES" -ge 2 ]; then
    echo "[$(date -Is)] no claude/node pane for 2 consecutive checks (last: $(echo "$PANE_CMDS" | tr '\n' ',')); claude crashed - exiting for systemd restart" | tee -a "$LOG"
    tmux kill-session -t "$SESSION" 2>/dev/null || true
    exit 1
  fi
done

echo "[$(date -Is)] tmux session $SESSION ended; exiting for systemd restart" | tee -a "$LOG"
