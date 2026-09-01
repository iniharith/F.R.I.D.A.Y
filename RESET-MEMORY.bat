@echo off
setlocal
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
    echo Run INSTALL-FRIDAY.bat first.
    pause
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -m core.memory.cli clear
pause