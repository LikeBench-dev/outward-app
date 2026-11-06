@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare-release.ps1" %*
set "release_exit_code=%errorlevel%"
endlocal & exit /b %release_exit_code%
