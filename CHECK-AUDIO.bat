@echo off
setlocal
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
    echo Run INSTALL-FRIDAY.bat first.
    pause
    exit /b 1
)
echo Available playback and microphone devices:
echo.
"%~dp0.venv\Scripts\python.exe" -m sounddevice
pause