#!/bin/bash
# Weekday / login LaunchAgent entry point for the Loop briefing.
# Relies on run_briefing.py loading a gitignored .env after cd. Do not echo secrets.
set -e

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

cd /Users/ethankang/Documents/Codex/ai-market-briefing
mkdir -p logs briefs

TODAY="$(date +%F)"
BRIEF="briefs/${TODAY}.md"
if [ -f "$BRIEF" ]; then
  exit 0
fi

LOCK="logs/briefing.lock"
if [ -f "$LOCK" ]; then
  existing_pid="$(tr -d '[:space:]' < "$LOCK" 2>/dev/null || true)"
  if [ -n "$existing_pid" ] && kill -0 "$existing_pid" 2>/dev/null; then
    exit 0
  fi
fi

cleanup() { rm -f "$LOCK"; }
trap cleanup EXIT INT TERM HUP
echo "$$" > "$LOCK"
python3 src/run_briefing.py >> logs/launchd.log 2>&1
