@echo off
setlocal
echo Configure FRIDAY Hermes Portal fallback reasoning
echo.
echo Create a NEW key at https://portal.nousresearch.com
echo Never paste the key into chat, source files, or screenshots.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$secure = Read-Host 'Paste the NEW Hermes Portal key' -AsSecureString; $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure); try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr); if (-not $plain) { throw 'The key is empty.' }; [Environment]::SetEnvironmentVariable('HERMES_API_KEY', $plain, 'User'); [Environment]::SetEnvironmentVariable('FRIDAY_HERMES_MODEL', 'z-ai/glm-5.3-flash', 'User'); Write-Host 'Hermes Portal fallback configured with GLM 5.3 Flash for future FRIDAY processes.' } finally { if ($ptr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }; $plain = $null }"
if errorlevel 1 (
    echo Configuration failed.
    pause
    exit /b 1
)
echo.
echo Fully close and restart FRIDAY.
pause
