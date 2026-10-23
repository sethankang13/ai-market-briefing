#!/bin/bash
# Start the Loop Streamlit UI (port 8501). Safe to run from Finder/osascript.
set -e

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

cd /Users/ethankang/Documents/Codex/ai-market-briefing
mkdir -p logs

if lsof -i :8501 2>/dev/null | grep -qi streamlit; then
  echo "Streamlit is already running on port 8501."
  open http://localhost:8501
  exit 0
fi

nohup streamlit run src/app.py --server.headless true --server.port 8501 > logs/streamlit.log 2>&1 &
echo $! > logs/streamlit.pid
open http://localhost:8501
