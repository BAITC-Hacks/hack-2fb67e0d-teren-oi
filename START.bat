@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 launch.py %*
) else (
  python launch.py %*
)
if errorlevel 1 (
  echo.
  echo Startup failed. Read the message above.
  echo Python 3.11+: https://www.python.org/downloads/
  echo Node.js 22.12+: https://nodejs.org/en/download
  pause
)
