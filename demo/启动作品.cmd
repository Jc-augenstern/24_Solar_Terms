@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Local Python environment missing. Run preparation first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run.py --background
if errorlevel 1 pause
