@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Install.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" client.py backup
set "backup_exit=%errorlevel%"
pause
exit /b %backup_exit%
