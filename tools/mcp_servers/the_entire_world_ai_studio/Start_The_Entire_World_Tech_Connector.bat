@echo off
setlocal
title The Entire World Tech Connector

cd /d "%~dp0"

echo ==========================================
echo The Entire World Tech Connector
echo ==========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher "py" was not found.
    echo Please install Python 3.11, then run this again.
    pause
    exit /b 1
)

echo Checking Python 3.11...
py -3.11 --version >nul 2>nul
if errorlevel 1 (
    echo Python 3.11 was not found.
    echo Please install Python 3.11, then run this again.
    pause
    exit /b 1
)

set SETUP_MARKER=%LOCALAPPDATA%\TA_Tech_Connector_MCPHost\deps_installed.marker
if not exist "%LOCALAPPDATA%\TA_Tech_Connector_MCPHost" mkdir "%LOCALAPPDATA%\TA_Tech_Connector_MCPHost"

if exist "%SETUP_MARKER%" (
    echo Dependencies already checked.
) else (
    echo Checking dependencies...
    py -3.11 -m pip show PySide6 >nul 2>nul
    if errorlevel 1 py -3.11 -m pip install PySide6
    py -3.11 -m pip show fastmcp >nul 2>nul
    if errorlevel 1 py -3.11 -m pip install fastmcp
    py -3.11 -m pip show pywinpty >nul 2>nul
    if errorlevel 1 py -3.11 -m pip install pywinpty
    echo ok > "%SETUP_MARKER%"
)

echo Installing/updating local components...

set PYDIR=C:\Desktop\UnrealGenAISupport\Content\Python
set CFG=%~dp0knowledge\mcp_unreal_maya_knowledge_config.json

mkdir "%PYDIR%" 2>nul

if exist "%~dp0maya_mcp_server_quiet.py" copy /Y "%~dp0maya_mcp_server_quiet.py" "%PYDIR%\maya_mcp_server_quiet.py" >nul
if exist "%~dp0motionbuilder_mcp_server.py" copy /Y "%~dp0motionbuilder_mcp_server.py" "%PYDIR%\motionbuilder_mcp_server.py" >nul
if exist "%~dp0motionbuilder_command_port_setup.py" copy /Y "%~dp0motionbuilder_command_port_setup.py" "%PYDIR%\motionbuilder_command_port_setup.py" >nul

if exist "%CFG%" copy /Y "%CFG%" "%CFG%.bak" >nul 2>nul

py -3.11 -c "import json, pathlib, os, stat; cfg=pathlib.Path(r'%CFG%'); data=json.loads(cfg.read_text(encoding='utf-8')) if cfg.exists() else {'mcpServers':{}}; s=data.setdefault('mcpServers',{}); s['knowledge']={'type':'stdio','command':'py','args':['-3.11',r'%~dp0knowledge\knowledge_mcp_server_v2.py']}; s['maya']={'type':'stdio','command':'py','args':['-3.11',r'C:\Desktop\UnrealGenAISupport\Content\Python\maya_mcp_server_quiet.py']}; s['motionbuilder']={'type':'stdio','command':'py','args':['-3.11',r'C:\Desktop\UnrealGenAISupport\Content\Python\motionbuilder_mcp_server.py']}; s['ludus-mcp']={'type':'stdio','command':'npx','args':['-y','mcp-remote','https://mcp.ludusengine.com/mcp']}; cfg.parent.mkdir(parents=True, exist_ok=True); (os.chmod(cfg, stat.S_IWRITE) if cfg.exists() else None); cfg.write_text(json.dumps(data,indent=2),encoding='utf-8')"

@echo off
cd /d "%~dp0"
start "" pyw -3.11 -m app.main_window
exit