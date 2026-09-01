@echo off
setlocal
title F.R.I.D.A.Y. HUD Launcher
cd /d %~dp0

if exist "dist-launcher\FRIDAY-HUD.exe" (
    echo Starting F.R.I.D.A.Y. HUD...
    start "" "dist-launcher\FRIDAY-HUD.exe"
) else (
    echo HUD not built yet. Starting in dev mode...
    cd launcher
    call npx electron .
)
