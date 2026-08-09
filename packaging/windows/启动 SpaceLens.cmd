@echo off
cd /d "%~dp0"
SpaceLens.exe
if errorlevel 1 pause
