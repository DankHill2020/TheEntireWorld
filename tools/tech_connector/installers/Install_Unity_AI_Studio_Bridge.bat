@echo off
setlocal
title Install Unity Tech Connector Bridge

cd /d "%~dp0"

set PYTHON_CMD=
py -3.11 --version >nul 2>nul
if not errorlevel 1 set PYTHON_CMD=py -3.11
if "%PYTHON_CMD%"=="" (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set PYTHON_CMD=py -3
)
if "%PYTHON_CMD%"=="" (
    python --version >nul 2>nul
    if not errorlevel 1 set PYTHON_CMD=python
)
if "%PYTHON_CMD%"=="" (
    echo No usable Python runtime was found.
    if not "%AI_STUDIO_NONINTERACTIVE%"=="1" pause
    exit /b 1
)

%PYTHON_CMD% install_unity_bridge.py %*
if errorlevel 1 (
    if not "%AI_STUDIO_NONINTERACTIVE%"=="1" pause
    exit /b 1
)

if not "%AI_STUDIO_NONINTERACTIVE%"=="1" pause
