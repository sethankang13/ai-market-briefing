#!/bin/bash
# Start the Loop Streamlit UI (port 8501). Safe to run from Finder/osascript.
set -e

# Finder/osascript inherit a tiny PATH. Streamlit lives in the python.org
# framework bin, not Homebrew, so include that first.
export PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

cd /Users/ethankang/Documents/Codex/ai-market-briefing
mkdir -p logs
bash scripts/apply_loop_icon.sh >/dev/null 2>&1 || true

URL="http://127.0.0.1:8501"

if lsof -nP -iTCP:8501 -sTCP:LISTEN 2>/dev/null | grep -qi streamlit; then
  echo "Streamlit is already running on port 8501."
  open "$URL"
  exit 0
fi

if command -v streamlit >/dev/null 2>&1; then
  STREAMLIT=(streamlit)
elif python3 -m streamlit --help >/dev/null 2>&1; then
  STREAMLIT=(python3 -m streamlit)
else
  echo "streamlit not found on PATH. From the project folder run: pip3 install -r requirements.txt" >&2
  exit 1
fi

nohup "${STREAMLIT[@]}" run src/app.py \
  --server.headless true \
  --server.address 127.0.0.1 \
  --server.port 8501 \
  > logs/streamlit.log 2>&1 &
echo $! > logs/streamlit.pid

ready=0
for _ in $(seq 1 40); do
  if curl -sf -o /dev/null --max-time 1 "$URL" 2>/dev/null; then
    ready=1
    break
  fi
  sleep 0.25
done

if [ "$ready" -eq 0 ]; then
  echo "Streamlit did not become ready on $URL. See logs/streamlit.log" >&2
  exit 1
fi

open "$URL"
