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

set SETUP_MARKER=%LOCALAPPDATA%\TA_AI_Studio_MCPHost\deps_installed.marker
if not exist "%LOCALAPPDATA%\TA_AI_Studio_MCPHost" mkdir "%LOCALAPPDATA%\TA_AI_Studio_MCPHost"

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

set KDIR=C:\depot\tools\mcp_servers\knowledge_mcp
set PYDIR=C:\Desktop\UnrealGenAISupport\Content\Python
set CFG=C:\depot\tools\mcp_unreal_maya_knowledge_config.json

mkdir "%KDIR%" 2>nul
mkdir "%PYDIR%" 2>nul

if exist "%~dp0build_knowledge_index_v2.py" copy /Y "%~dp0build_knowledge_index_v2.py" "%KDIR%\build_knowledge_index_v2.py" >nul
if exist "%~dp0knowledge_mcp_server_v2.py" copy /Y "%~dp0knowledge_mcp_server_v2.py" "%KDIR%\knowledge_mcp_server_v2.py" >nul
if exist "%~dp0maya_mcp_server_quiet.py" copy /Y "%~dp0maya_mcp_server_quiet.py" "%PYDIR%\maya_mcp_server_quiet.py" >nul
if exist "%~dp0motionbuilder_mcp_server.py" copy /Y "%~dp0motionbuilder_mcp_server.py" "%PYDIR%\motionbuilder_mcp_server.py" >nul
if exist "%~dp0motionbuilder_command_port_setup.py" copy /Y "%~dp0motionbuilder_command_port_setup.py" "%PYDIR%\motionbuilder_command_port_setup.py" >nul

if exist "%CFG%" copy /Y "%CFG%" "%CFG%.bak" >nul 2>nul

py -3.11 -c "import json, pathlib; cfg=pathlib.Path(r'%CFG%'); data=json.loads(cfg.read_text(encoding='utf-8')) if cfg.exists() else {'mcpServers':{}}; s=data.setdefault('mcpServers',{}); s['knowledge']={'type':'stdio','command':'py','args':['-3.11',r'C:\depot\tools\mcp_servers\knowledge_mcp\knowledge_mcp_server_v2.py']}; s['maya']={'type':'stdio','command':'py','args':['-3.11',r'C:\Desktop\UnrealGenAISupport\Content\Python\maya_mcp_server_quiet.py']}; s['motionbuilder']={'type':'stdio','command':'py','args':['-3.11',r'C:\Desktop\UnrealGenAISupport\Content\Python\motionbuilder_mcp_server.py']}; cfg.parent.mkdir(parents=True, exist_ok=True); cfg.write_text(json.dumps(data,indent=2),encoding='utf-8')"

echo.
echo Launching The Entire World AI Studio...
start "" pyw -3.11 "%~dp0the_entire_world_ai_studio.py"
exit /b 0