@echo off
setlocal
title Install Substance Painter Tech Connector Bridge

cd /d "%~dp0"

echo ==========================================
echo Install Substance Painter Tech Connector Bridge
echo ==========================================
echo.

set PYTHON_CMD=

py -3.14 --version >nul 2>nul
if not errorlevel 1 set PYTHON_CMD=py -3.14

if "%PYTHON_CMD%"=="" (
py -3.11 --version >nul 2>nul
if not errorlevel 1 set PYTHON_CMD=py -3.11
)

if "%PYTHON_CMD%"=="" (
    py -3.10 --version >nul 2>nul
    if not errorlevel 1 set PYTHON_CMD=py -3.10
)

if "%PYTHON_CMD%"=="" (
    py -3.9 --version >nul 2>nul
    if not errorlevel 1 set PYTHON_CMD=py -3.9
)

if "%PYTHON_CMD%"=="" (
    python --version >nul 2>nul
    if not errorlevel 1 set PYTHON_CMD=python
)

if "%PYTHON_CMD%"=="" (
    echo No usable Python runtime was found.
    echo Please install Python, then run this again.
    pause
    exit /b 1
)

%PYTHON_CMD% install_substance_painter_bridge.py
if errorlevel 1 (
    echo.
    echo Substance Painter bridge install did not complete.
    pause
    exit /b 1
)

echo.
echo Restart Substance Painter. If needed, enable the bridge plugin from its Python/plugins menu.
pause
