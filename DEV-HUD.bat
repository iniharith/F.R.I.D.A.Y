@echo off
setlocal
title F.R.I.D.A.Y. HUD - Development Mode
cd /d %~dp0launcher

if not exist "node_modules" (
    echo Installing dependencies...
    call npm install
)

echo Starting F.R.I.D.A.Y. HUD in dev mode...
call npx electron .
