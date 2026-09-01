@echo off
setlocal
cd /d %~dp0
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo Inno Setup 6 is required.
    echo Install it with: winget install JRSoftware.InnoSetup
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Run INSTALL-FRIDAY.bat before building the installer.
    pause
    exit /b 1
)
if not exist "dist-launcher\FRIDAY-HUD.exe" (
    echo ERROR: Run BUILD-HUD.bat before building the installer.
    pause
    exit /b 1
)
echo Building the complete offline installer. This can take several minutes.
"%ISCC%" "installer\FRIDAY.iss"
if errorlevel 1 (
    echo INSTALLER BUILD FAILED.
    pause
    exit /b 1
)
echo.
echo Build complete: installer-output\FRIDAY-Setup.exe
echo Keep FRIDAY-Setup.exe and all FRIDAY-Setup-*.bin files together.
pause
