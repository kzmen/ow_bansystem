@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title OW BAN ROOM

echo ========================================
echo   OW BAN ROOM - STARTER
echo ========================================
echo.

where py.exe >nul 2>nul
if not errorlevel 1 goto USE_PY

where python.exe >nul 2>nul
if not errorlevel 1 goto USE_PYTHON

echo [ERROR] Python was not found.
echo Install Python 3 and enable "Add Python to PATH".
echo Download: https://www.python.org/downloads/
echo.
pause
exit /b 1

:USE_PY
py -3 app_standalone.py
goto FINISHED

:USE_PYTHON
python app_standalone.py
goto FINISHED

:FINISHED
if errorlevel 1 (
  echo.
  echo ========================================
  echo [ERROR] The server could not start.
  echo Please send a screenshot of this window.
  echo ========================================
  echo.
  pause
)
endlocal
