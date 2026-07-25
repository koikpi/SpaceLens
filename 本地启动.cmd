@echo off
cd /d "%~dp0"
where python.exe >nul 2>nul
if errorlevel 1 (
  echo Python 3 was not found. Please install Python 3 first.
  pause
  exit /b 1
)
python.exe local_server.py
if errorlevel 1 pause
