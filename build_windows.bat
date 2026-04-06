@echo off
setlocal EnableDelayedExpansion
title PGOps - Windows Build

echo ============================================
echo  PGOps - Windows Build Script
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Download from https://www.python.org/downloads/ and tick "Add to PATH".
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER% found.
echo.

:: Check Inno Setup
set "ISCC="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
)

if defined ISCC (
    echo [OK] Inno Setup 6 found.
    set "BUILD_INSTALLER=1"
) else (
    echo [WARN] Inno Setup 6 not found - no Setup.exe will be produced.
    echo        Get it from: https://jrsoftware.org/isinfo.php
    echo.
    set "BUILD_INSTALLER=0"
)

:: Step 0 - Check for bundled PG zip
echo.
if exist assets\pg_windows.zip (
    echo [OK] Bundled PostgreSQL zip found: assets\pg_windows.zip
) else (
    echo [WARN] assets\pg_windows.zip not found.
    echo        The app will download PostgreSQL at runtime instead.
    echo        To bundle it: download the zip from:
    echo        https://www.enterprisedb.com/download-postgresql-binaries
    echo        Choose: Windows x86-64, version 16.x, "zip" format
    echo        Save as: assets\pg_windows.zip
    echo.
)

:: Step 1 - Install deps
echo.
echo [1/3] Installing Python dependencies...
pip install PyQt6 requests qrcode Pillow pyinstaller --quiet --upgrade
if errorlevel 1 (
    echo [ERROR] pip install failed.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.

:: Step 2 - PyInstaller
echo.
echo [2/3] Building with PyInstaller...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"

pyinstaller pgops.spec --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    pause
    exit /b 1
)
echo [OK] Built: dist\PGOps\PGOps.exe

:: Step 3 - Inno Setup
echo.
if "%BUILD_INSTALLER%"=="1" (
    echo [3/3] Creating installer with Inno Setup...
    if not exist dist\installer mkdir dist\installer
    "%ISCC%" installer\windows.iss
    if errorlevel 1 (
        echo [ERROR] Inno Setup failed.
        pause
        exit /b 1
    )
    echo.
    echo ============================================
    echo  BUILD COMPLETE
    echo ============================================
    echo.
    echo  Installer : dist\installer\PGOps-Setup-1.0.0-Windows.exe
    echo  Raw app   : dist\PGOps\PGOps.exe
) else (
    echo [3/3] Skipped installer.
    echo.
    echo ============================================
    echo  BUILD COMPLETE ^(no installer^)
    echo ============================================
    echo.
    echo  Raw app: dist\PGOps\PGOps.exe
    echo  Zip the dist\PGOps\ folder to distribute manually.
)

echo.
echo  On first run the app downloads PostgreSQL binaries once ^(~150 MB^).
echo.
pause
