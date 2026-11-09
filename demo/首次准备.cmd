@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare.ps1"
if errorlevel 1 (
  echo Preparation failed. See details above.
  pause
  exit /b 1
)
echo Preparation complete. Run the start entry to open the museum.
pause
