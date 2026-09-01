@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "[Environment]::SetEnvironmentVariable('FRIDAY_REASONING_MODE', 'local', 'User'); Write-Host 'FRIDAY will use local reasoning after restart.'"
pause
