#!/bin/bash
# Stop the Loop Streamlit UI started by start_app.sh.
set -e

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

cd /Users/ethankang/Documents/ai-market-briefing
mkdir -p logs

PID_FILE="logs/streamlit.pid"
killed=0
if [ -f "$PID_FILE" ]; then
  pid=$(cat "$PID_FILE")
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    killed=1
  fi
  rm -f "$PID_FILE"
fi

if [ "$killed" -eq 0 ]; then
  pkill -f "streamlit run src/app.py" || true
fi
