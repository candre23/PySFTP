@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.11 or newer, then rerun setup.bat.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -m venv .venv
  if errorlevel 1 goto :error
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
if not exist "rclone\rclone.exe" (
  echo.
  echo WARNING: Place rclone.exe in the rclone folder before launching.
)
echo.
echo Setup complete. Double-click Launch PySFTP.vbs to start without a console.
pause
exit /b 0
:error
echo Setup failed. Read the errors above.
pause
exit /b 1
