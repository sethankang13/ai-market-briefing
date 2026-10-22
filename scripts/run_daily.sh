#!/bin/bash
# Weekday LaunchAgent entry point for the Loop briefing.
# Relies on run_briefing.py loading a gitignored .env after cd. Do not echo secrets.
set -e

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

cd /Users/ethankang/Documents/Codex/ai-market-briefing
mkdir -p logs
python3 src/run_briefing.py >> logs/launchd.log 2>&1
