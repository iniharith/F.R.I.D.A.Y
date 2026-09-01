@echo off
setlocal
echo Configure FRIDAY optional OpenRouter reasoning
echo.
echo Create a NEW key at https://openrouter.ai/settings/keys
echo Never paste the key into chat, source files, or screenshots.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$secure = Read-Host 'Paste the NEW OpenRouter key' -AsSecureString; $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure); try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr); if (-not $plain.StartsWith('sk-or-')) { throw 'That does not look like an OpenRouter key.' }; [Environment]::SetEnvironmentVariable('OPENROUTER_API_KEY', $plain, 'User'); [Environment]::SetEnvironmentVariable('FRIDAY_OPENROUTER_MODEL', 'z-ai/glm-5.3-flash', 'User'); [Environment]::SetEnvironmentVariable('FRIDAY_REASONING_MODE', 'openrouter', 'User'); Write-Host 'GLM 5.3 Flash configured for future FRIDAY processes.' } finally { if ($ptr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }; $plain = $null }"
if errorlevel 1 (
    echo Configuration failed.
    pause
    exit /b 1
)
echo.
echo Fully close and restart FRIDAY.
pause
