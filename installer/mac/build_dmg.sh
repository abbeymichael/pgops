#!/bin/bash
# Mac DMG builder
# Creates a drag-to-install .dmg from the PyInstaller .app bundle
# Requirements: brew install create-dmg

set -e

APP_NAME="PGManager"
VERSION="1.0.0"
APP_PATH="dist/${APP_NAME}.app"
DMG_NAME="${APP_NAME}-${VERSION}-macOS.dmg"
DMG_OUT="dist/installer/${DMG_NAME}"

echo "============================================"
echo " PGManager — macOS DMG Builder"
echo "============================================"
echo

# Check .app exists
if [ ! -d "$APP_PATH" ]; then
  echo "ERROR: $APP_PATH not found."
  echo "Run build_mac.sh first to generate the .app bundle."
  exit 1
fi

# Check create-dmg
if ! command -v create-dmg &>/dev/null; then
  echo "Installing create-dmg via Homebrew..."
  brew install create-dmg
fi

mkdir -p "dist/installer"

echo "Building DMG..."
create-dmg \
  --volname "${APP_NAME} ${VERSION}" \
  --window-pos 200 120 \
  --window-size 600 400 \
  --icon-size 100 \
  --icon "${APP_NAME}.app" 160 185 \
  --hide-extension "${APP_NAME}.app" \
  --app-drop-link 430 185 \
  --background "installer/mac/dmg_background.png" \
  "$DMG_OUT" \
  "$APP_PATH" \
|| \
create-dmg \
  --volname "${APP_NAME} ${VERSION}" \
  --window-pos 200 120 \
  --window-size 540 360 \
  --icon-size 100 \
  --icon "${APP_NAME}.app" 150 180 \
  --hide-extension "${APP_NAME}.app" \
  --app-drop-link 380 180 \
  "$DMG_OUT" \
  "$APP_PATH"

echo
echo "✓ DMG created: $DMG_OUT"
echo
echo "Distribute this file. Users drag PGManager.app to Applications."
