#!/bin/bash
# Copy the light or dark glasses tile onto Loop.app from system appearance.
set -e

PROJECT="${PROJECT:-/Users/ethankang/Documents/Codex/ai-market-briefing}"
APP_PATH="${APP_PATH:-$HOME/Applications/Loop.app}"

png_for_appearance() {
  if defaults read -g AppleInterfaceStyle 2>/dev/null | grep -qx Dark; then
    echo "$PROJECT/static/loop-icon-dark.png"
  else
    echo "$PROJECT/static/loop-icon-light.png"
  fi
}

apply_loop_app_icon() {
  local png resources iconset icns
  png="$(png_for_appearance)"
  resources="$APP_PATH/Contents/Resources"
  if [ ! -f "$png" ] || [ ! -d "$resources" ]; then
    return 0
  fi
  iconset="$(mktemp -d /tmp/loop-icon.XXXXXX.iconset)"
  icns="$(mktemp /tmp/loop-icon.XXXXXX.icns)"
  sips -z 16 16 "$png" --out "$iconset/icon_16x16.png" >/dev/null
  sips -z 32 32 "$png" --out "$iconset/icon_16x16@2x.png" >/dev/null
  sips -z 32 32 "$png" --out "$iconset/icon_32x32.png" >/dev/null
  sips -z 64 64 "$png" --out "$iconset/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 "$png" --out "$iconset/icon_128x128.png" >/dev/null
  sips -z 256 256 "$png" --out "$iconset/icon_256x256.png" >/dev/null
  sips -z 256 256 "$png" --out "$iconset/icon_128x128@2x.png" >/dev/null
  sips -z 512 512 "$png" --out "$iconset/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 "$png" --out "$iconset/icon_512x512.png" >/dev/null
  sips -z 1024 1024 "$png" --out "$iconset/icon_512x512@2x.png" >/dev/null
  iconutil -c icns "$iconset" -o "$icns"
  cp "$icns" "$resources/applet.icns"
  /usr/libexec/PlistBuddy -c "Set :CFBundleIconFile applet" "$APP_PATH/Contents/Info.plist" 2>/dev/null || true
  rm -rf "$iconset" "$icns"
  touch "$APP_PATH"
}

apply_loop_app_icon
