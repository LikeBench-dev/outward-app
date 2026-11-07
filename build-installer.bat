@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-installer.ps1" -CommitRelease %*
endlocal & exit /b %errorlevel%
