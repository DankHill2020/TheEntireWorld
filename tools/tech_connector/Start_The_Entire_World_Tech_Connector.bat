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
set SETUP_MARKER=%LOCALAPPDATA%\TA_Tech_Connector_MCPHost\deps_py314_installed.marker
if not exist "%LOCALAPPDATA%\TA_Tech_Connector_MCPHost" mkdir "%LOCALAPPDATA%\TA_Tech_Connector_MCPHost"

if exist "%SETUP_MARKER%" (
    echo Dependencies already checked.
) else (
    echo Checking dependencies...
    "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r "%~dp0packaging\requirements-runtime.txt"
    if errorlevel 1 exit /b 1
    echo ok > "%SETUP_MARKER%"
)

echo Checking media analysis dependencies...
"%PYTHON_EXE%" %PYTHON_ARGS% -m pip show imageio >nul 2>nul
if errorlevel 1 "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r "%~dp0requirements\media.txt"
"%PYTHON_EXE%" %PYTHON_ARGS% -m pip show imageio-ffmpeg >nul 2>nul
if errorlevel 1 "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r "%~dp0requirements\media.txt"

echo Installing/updating local components...

set PYDIR=C:\Desktop\UnrealGenAISupport\Content\Python
set CFG=%~dp0knowledge\mcp_unreal_maya_knowledge_config.json

mkdir "%PYDIR%" 2>nul

if exist "%~dp0maya_mcp_server_quiet.py" copy /Y "%~dp0maya_mcp_server_quiet.py" "%PYDIR%\maya_mcp_server_quiet.py" >nul
if exist "%~dp0motionbuilder_mcp_server.py" copy /Y "%~dp0motionbuilder_mcp_server.py" "%PYDIR%\motionbuilder_mcp_server.py" >nul
if exist "%~dp0motionbuilder_command_port_setup.py" copy /Y "%~dp0motionbuilder_command_port_setup.py" "%PYDIR%\motionbuilder_command_port_setup.py" >nul

if exist "%CFG%" copy /Y "%CFG%" "%CFG%.bak" >nul 2>nul

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import json, pathlib, os, stat; cfg=pathlib.Path(r'%CFG%'); python_command='python'; python_args=[]; data=json.loads(cfg.read_text(encoding='utf-8')) if cfg.exists() else {'mcpServers':{}}; s=data.setdefault('mcpServers',{}); s['knowledge']={'type':'stdio','command':python_command,'args':python_args+[r'%~dp0knowledge\knowledge_mcp_server_v2.py']}; s['unreal']={'type':'stdio','command':python_command,'args':python_args+[r'%~dp0bridges\unreal\unreal_mcp_server.py']}; s['maya']={'type':'stdio','command':python_command,'args':python_args+[r'C:\Desktop\UnrealGenAISupport\Content\Python\maya_mcp_server_quiet.py']}; s['motionbuilder']={'type':'stdio','command':python_command,'args':python_args+[r'C:\Desktop\UnrealGenAISupport\Content\Python\motionbuilder_mcp_server.py']}; s['ludus-mcp']={'type':'stdio','command':'npx','args':['-y','mcp-remote','https://mcp.ludusengine.com/mcp']}; cfg.parent.mkdir(parents=True, exist_ok=True); (os.chmod(cfg, stat.S_IWRITE) if cfg.exists() else None); cfg.write_text(json.dumps(data,indent=2),encoding='utf-8')"

@echo off
for %%I in ("%~dp0..") do set TOOLS_ROOT=%%~fI
cd /d "%TOOLS_ROOT%"
start "" "%PYTHONW_EXE%" %PYTHON_ARGS% -m tech_connector.studio_main
exit
