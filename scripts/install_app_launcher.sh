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

ICON_PNG="$PROJECT/static/loop-icon-light.png"
RESOURCES="$APP_PATH/Contents/Resources"
if [ -f "$ICON_PNG" ] && [ -d "$RESOURCES" ]; then
  ICONSET="$(mktemp -d /tmp/loop-icon.XXXXXX.iconset)"
  ICON_ICNS="$(mktemp /tmp/loop-icon.XXXXXX.icns)"
  sips -z 16 16 "$ICON_PNG" --out "$ICONSET/icon_16x16.png" >/dev/null
  sips -z 32 32 "$ICON_PNG" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
  sips -z 32 32 "$ICON_PNG" --out "$ICONSET/icon_32x32.png" >/dev/null
  sips -z 64 64 "$ICON_PNG" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 "$ICON_PNG" --out "$ICONSET/icon_128x128.png" >/dev/null
  sips -z 256 256 "$ICON_PNG" --out "$ICONSET/icon_256x256.png" >/dev/null
  sips -z 256 256 "$ICON_PNG" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
  sips -z 512 512 "$ICON_PNG" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 "$ICON_PNG" --out "$ICONSET/icon_512x512.png" >/dev/null
  sips -z 1024 1024 "$ICON_PNG" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
  iconutil -c icns "$ICONSET" -o "$ICON_ICNS"
  cp "$ICON_ICNS" "$RESOURCES/applet.icns"
  /usr/libexec/PlistBuddy -c "Set :CFBundleIconFile applet" "$APP_PATH/Contents/Info.plist" 2>/dev/null || true
  rm -rf "$ICONSET" "$ICON_ICNS"
  touch "$APP_PATH"
fi

echo "Loop.app is in ~/Applications; drag to Dock or Desktop"
