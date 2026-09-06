@echo off
title The Busy Business Bits - demo
cd /d "%~dp0"

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (py -3 --version >nul 2>&1 && set "PY=py -3")
if not defined PY (python --version >nul 2>&1 && set "PY=python")
if not defined PY (python3 --version >nul 2>&1 && set "PY=python3")
if not defined PY (
  echo Python 3 was not found on this PC. Get it from python.org
  pause
  exit /b
)

echo Starting the Bits in demo mode with: %PY%
%PY% "busy_business_bits.py" --demo
if errorlevel 1 (
  echo.
  echo   The Bits stopped with an error. If it mentions Pillow, check
  echo   bits_install_log.txt in this folder.
  echo.
  pause
)
exit /b
