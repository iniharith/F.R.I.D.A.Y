@echo off
setlocal
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
    echo Run INSTALL-FRIDAY.bat first.
    pause
    exit /b 1
)
py312\python.exe installer\repair-venv.py
"%~dp0.venv\Scripts\python.exe" -m core.main
pause