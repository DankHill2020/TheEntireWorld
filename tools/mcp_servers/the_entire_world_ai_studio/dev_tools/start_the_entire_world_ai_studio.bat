@echo off
setlocal
title The Entire World AI Studio

cd /d "%~dp0"

echo ==========================================
echo The Entire World AI Studio
echo ==========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher "py" was not found.
    echo Install Python 3.11, then run this again.
    pause
    exit /b 1
)

echo Checking Python 3.11...
py -3.11 --version
if errorlevel 1 (
    echo Python 3.11 was not found.
    echo Install Python 3.11, then run this again.
    pause
    exit /b 1
)

echo Checking Python dependencies...
py -3.11 -m pip show PySide6 >nul 2>nul
if errorlevel 1 py -3.11 -m pip install PySide6

py -3.11 -m pip show fastmcp >nul 2>nul
if errorlevel 1 py -3.11 -m pip install fastmcp

py -3.11 -m pip show pywinpty >nul 2>nul
if errorlevel 1 py -3.11 -m pip install pywinpty

echo.
echo Launching Studio...
start "" pyw -3.11 "%~dp0the_entire_world_ai_studio.py"
exit /b 0