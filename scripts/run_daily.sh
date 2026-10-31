#!/bin/bash
# Daily / login LaunchAgent entry point for the Loop briefing.
# Relies on a gitignored .env after cd. Do not echo secrets.
set -e

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"
if [ -d "/Library/Frameworks/Python.framework/Versions/Current/bin" ]; then
  export PATH="/Library/Frameworks/Python.framework/Versions/Current/bin:$PATH"
fi

cd /Users/ethankang/Documents/ai-market-briefing
mkdir -p logs briefs

LOG="logs/launchd.log"
log_line() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"
}

# Best-effort Notification Center. Ignore TCC / osascript failures.
notify() {
  /usr/bin/osascript -e "display notification \"$1\" with title \"LOOP\"" >/dev/null 2>&1 || true
}

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

log_line "start: daily briefing"

TODAY="$(date +%F)"
BRIEF="briefs/${TODAY}.md"
if [ -f "$BRIEF" ]; then
  log_line "skip: ${BRIEF} already exists"
  exit 0
fi

LOCK="logs/briefing.lock"
if [ -f "$LOCK" ]; then
  existing_pid="$(tr -d '[:space:]' < "$LOCK" 2>/dev/null || true)"
  if [ -n "$existing_pid" ] && kill -0 "$existing_pid" 2>/dev/null; then
    log_line "skip: briefing already running (pid ${existing_pid})"
    exit 0
  fi
fi

cleanup() { rm -f "$LOCK"; }
trap cleanup EXIT INT TERM HUP
echo "$$" > "$LOCK"
notify "Briefing in progress…"

set +e
python3 src/run_briefing.py >> "$LOG" 2>&1
status=$?
set -e

if [ "$status" -eq 0 ]; then
  log_line "complete: daily briefing"
  notify "Today's briefing is ready."
else
  log_line "failure: daily briefing exit ${status}"
  exit "$status"
fi
