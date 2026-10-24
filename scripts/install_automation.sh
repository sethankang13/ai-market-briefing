#!/bin/bash
# Install the Loop weekday/login LaunchAgent (load only; does not launchctl start).
# RunAtLoad is true in the plist; run_daily.sh exits 0 if today's brief already exists.
set -e

PROJECT="/Users/ethankang/Documents/Codex/ai-market-briefing"
PLIST_SRC="$PROJECT/scripts/com.loop.dailybriefing.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.loop.dailybriefing.plist"
LABEL="com.loop.dailybriefing"

chmod +x "$PROJECT/scripts/run_daily.sh"
mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$PROJECT/logs"
cp "$PLIST_SRC" "$PLIST_DEST"

launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo "Installed LaunchAgent $LABEL"
echo "Plist: $PLIST_DEST"
echo "Pipeline log: $PROJECT/logs/launchd.log"
echo "launchd stdout: $PROJECT/logs/launchd_stdout.log"
echo "launchd stderr: $PROJECT/logs/launchd_stderr.log"
echo "Live runs need a gitignored .env in the project root (do not put keys in this plist)."
echo "The Mac must be on at 8:00 AM on weekdays for the calendar interval to fire."
echo "To run once without waiting for 8 AM: launchctl start $LABEL"
echo
echo "Job status:"
launchctl list "$LABEL" || launchctl list | grep "$LABEL" || true
