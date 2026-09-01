@echo off
setlocal
title F.R.I.D.A.Y. HUD - Build Script
color 0B
echo.
echo  ============================================
echo   F.R.I.D.A.Y. HUD LAUNCHER - BUILD SYSTEM
echo  ============================================
echo.

cd /d %~dp0

echo [1/5] Checking Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js is not installed. Download from https://nodejs.org
    pause
    exit /b 1
)
echo       Node.js OK

echo [2/5] Installing Electron dependencies...
cd launcher
call npm ci
if errorlevel 1 (
    echo ERROR: npm install failed
    pause
    exit /b 1
)
echo       Dependencies installed

echo [3/5] Building portable EXE...
call npx electron-builder --win portable --config
if errorlevel 1 (
    echo ERROR: electron-builder failed
    pause
    exit /b 1
)

echo.
echo  ============================================
echo   BUILD COMPLETE!
echo  ============================================
echo   Output: dist-launcher\FRIDAY-HUD.exe
echo  ============================================
echo.

cd ..
pause
