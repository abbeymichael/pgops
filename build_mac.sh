#!/bin/bash
# PGOps — macOS Build Script
# Produces: dist/PGOps.app  +  dist/installer/PGOps-x.x.x-macOS.dmg

set -e

echo "============================================"
echo " PGOps — macOS Build Script"
echo "============================================"
echo

# ── Check Python 3 ────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found."
  echo "Install from https://www.python.org/downloads/macos/"
  exit 1
fi

PYVER=$(python3 --version 2>&1)
echo "[OK] $PYVER"

# ── Check Homebrew (for create-dmg) ───────────────────────────────────────
if ! command -v brew &>/dev/null; then
  echo
  echo "[WARN] Homebrew not found — DMG creation will be skipped."
  echo "       Install from https://brew.sh if you want a .dmg"
  BUILD_DMG=0
else
  BUILD_DMG=1
fi

# ── Install Python deps ───────────────────────────────────────────────────
echo
echo "[1/3] Installing Python dependencies..."
python3 -m pip install PyQt6 requests qrcode Pillow pyinstaller --quiet --upgrade
echo "[OK] Dependencies installed."

# ── PyInstaller ───────────────────────────────────────────────────────────
echo
echo "[2/3] Building with PyInstaller..."
rm -rf dist build

python3 -m PyInstaller pgops.spec --noconfirm

echo "[OK] .app bundle at: dist/PGOps.app"

# ── Code signing (optional — skip if no Apple Developer account) ──────────
# Uncomment and replace YOUR_IDENTITY if you have a Developer ID certificate:
# echo "Code signing..."
# codesign --deep --force --verify --verbose \
#   --sign "Developer ID Application: Your Name (TEAMID)" \
#   dist/PGOps.app

# ── DMG ───────────────────────────────────────────────────────────────────
if [ "$BUILD_DMG" = "1" ]; then
  echo
  echo "[3/3] Building DMG..."
  chmod +x installer/mac/build_dmg.sh
  bash installer/mac/build_dmg.sh
  echo
  echo "============================================"
  echo " BUILD COMPLETE"
  echo "============================================"
  echo
  echo " App bundle : dist/PGOps.app"
  echo " DMG        : dist/installer/PGOps-1.0.0-macOS.dmg"
  echo
else
  echo
  echo "[3/3] Skipped DMG (Homebrew/create-dmg not available)."
  echo
  echo "============================================"
  echo " BUILD COMPLETE (no DMG)"
  echo "============================================"
  echo
  echo " App bundle: dist/PGOps.app"
  echo " Distribute by zipping dist/PGOps.app"
  echo
fi

echo " First run: app will prompt to download PostgreSQL binaries (~150 MB)."
echo
