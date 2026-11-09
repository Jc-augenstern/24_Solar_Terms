@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Local Python environment missing. Run preparation first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\build_beijing.py
if errorlevel 1 (
  echo Beijing report is incomplete. Existing caches and reports were preserved; see the failure log.
  pause
  exit /b 1
)
echo Beijing report updated. Refresh the local page.
pause
