@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_MY_ANALYSIS.ps1"
echo.
pause
