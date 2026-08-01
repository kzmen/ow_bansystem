@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title OW BAN ROOM - CHECK

echo Checking Python...
where py.exe >nul 2>nul
if not errorlevel 1 goto USE_PY
where python.exe >nul 2>nul
if not errorlevel 1 goto USE_PYTHON

echo [ERROR] Python was not found.
pause
exit /b 1

:USE_PY
py -3 --version
py -3 -m unittest discover -s tests -v
goto FINISHED

:USE_PYTHON
python --version
python -m unittest discover -s tests -v
goto FINISHED

:FINISHED
echo.
if errorlevel 1 (
  echo [ERROR] A check failed.
) else (
  echo All checks passed.
)
pause
endlocal
