@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Local Python environment missing. Run preparation first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 scripts\build_cities.py --resume
set "CITY_TASK_EXIT=%ERRORLEVEL%"
if "%CITY_TASK_EXIT%"=="2" echo Some cities remain incomplete or blocked. Progress and existing reports are preserved. See data\batch_tasks.json and README.md.
if "%CITY_TASK_EXIT%"=="0" echo Requested city operation finished successfully.
pause
exit /b %CITY_TASK_EXIT%
