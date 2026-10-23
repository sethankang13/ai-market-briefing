#!/bin/bash
# Compile ~/Applications/Loop.app, which runs scripts/start_app.sh via osascript.
set -e

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PROJECT="/Users/ethankang/Documents/Codex/ai-market-briefing"
APP_DIR="$HOME/Applications"
APP_PATH="$APP_DIR/Loop.app"

chmod +x "$PROJECT/scripts/start_app.sh"
chmod +x "$PROJECT/scripts/stop_app.sh"
mkdir -p "$APP_DIR"
osacompile -o "$APP_PATH" -e "do shell script \"$PROJECT/scripts/start_app.sh\""

echo "Loop.app is in ~/Applications; drag to Dock or Desktop"
