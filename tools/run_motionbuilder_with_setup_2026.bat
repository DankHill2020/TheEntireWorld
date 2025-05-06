@echo off
setlocal enabledelayedexpansion

set "TOOLS_PATH=%~dp0"
if "%TOOLS_PATH:~-1%"=="\" set "TOOLS_PATH=%TOOLS_PATH:~0,-1%"

set "ESCAPED_TOOLS_PATH=%TOOLS_PATH:\=\\%"

set "MOBU_VERSION=2026"
set "STARTUP_DIR=%USERPROFILE%\Documents\MB\%MOBU_VERSION%\config\PythonStartup"
set "STARTUP_FILE=%STARTUP_DIR%\init_user.py"

if not exist "%STARTUP_DIR%" (
    mkdir "%STARTUP_DIR%"
)

findstr /C:"%ESCAPED_TOOLS_PATH%" "%STARTUP_FILE%" >nul 2>&1
if %errorlevel%==0 (
    echo Startup file already contains tools path. Skipping write.
) else (
    echo Adding tools path to MotionBuilder startup script...
    >> "%STARTUP_FILE%" echo.
    >> "%STARTUP_FILE%" echo # Added by setup
    >> "%STARTUP_FILE%" echo import sys
    >> "%STARTUP_FILE%" echo custom_path = r"%TOOLS_PATH%"
    >> "%STARTUP_FILE%" echo if custom_path not in sys.path:
    >> "%STARTUP_FILE%" echo     sys.path.append(custom_path^)
    >> "%STARTUP_FILE%" echo from motionbuilder_tools import motionbuilder_menu
)

set "MOBU_EXE=C:\Program Files\Autodesk\MotionBuilder %MOBU_VERSION%\bin\x64\motionbuilder.exe"
if exist "%MOBU_EXE%" (
    echo Launching MotionBuilder %MOBU_VERSION%...
    start "" "%MOBU_EXE%"
) else (
    echo ERROR: MotionBuilder executable not found at "%MOBU_EXE%"
)

echo Done.
endlocal
