@echo off
setlocal
title The Entire World Tech Connector

cd /d "%~dp0"

echo ==========================================
echo The Entire World Tech Connector
echo ==========================================
echo.

set "PYTHON_EXE="
set "PYTHONW_EXE="
set "PYTHON_ARGS="

py -3.14 --version >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHONW_EXE=pyw"
    set "PYTHON_ARGS=-3.14"
)

if not defined PYTHON_EXE if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    set "PYTHONW_EXE=%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"
)

if not defined PYTHON_EXE (
    echo Python 3.14 was not found.
    echo Please run "py install 3.14", then launch this again.
    pause
    exit /b 1
)

if /I not "%PYTHONW_EXE%"=="pyw" if not exist "%PYTHONW_EXE%" set "PYTHONW_EXE=%PYTHON_EXE%"
echo Using Python: %PYTHON_EXE% %PYTHON_ARGS%
echo Checking installed runtime dependencies...
"%PYTHON_EXE%" %PYTHON_ARGS% -c "import cryptography, PySide6, requests, websockets"
if errorlevel 1 (
    echo.
    echo Required dependencies are missing. This launcher will not install or update
    echo packages automatically. In a dedicated environment, run:
    echo   %PYTHON_EXE% %PYTHON_ARGS% -m pip install -r "%~dp0packaging\requirements-runtime.txt"
    pause
    exit /b 1
)

@echo off
for %%I in ("%~dp0..") do set TOOLS_ROOT=%%~fI
echo.
echo Tech Connector requires account sign-in, license acceptance, and activation.
echo Downloading or cloning from GitHub does not create an activated entitlement.
cd /d "%TOOLS_ROOT%"
start "" "%PYTHONW_EXE%" %PYTHON_ARGS% -m tech_connector.studio_main
exit
