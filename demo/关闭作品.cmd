@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Local Python environment missing. Use Ctrl+C in the running window.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run.py --stop
if errorlevel 1 pause
