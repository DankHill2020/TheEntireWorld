@echo off
setlocal
title The Entire World AI Studio DEBUG

cd /d "%~dp0"

echo ==========================================
echo The Entire World AI Studio DEBUG
echo ==========================================
echo.

py -3.11 -m pip show PySide6 >nul 2>nul
if errorlevel 1 py -3.11 -m pip install PySide6

py -3.11 -m pip show fastmcp >nul 2>nul
if errorlevel 1 py -3.11 -m pip install fastmcp

py -3.11 -m pip show pywinpty >nul 2>nul
if errorlevel 1 py -3.11 -m pip install pywinpty

py -3.11 "%~dp0the_entire_world_ai_studio.py"
pause