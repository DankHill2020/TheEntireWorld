@echo off
setlocal
title Install The Entire World AI Components

cd /d "%~dp0"

set KDIR=C:\depot\tools\mcp_servers\knowledge_mcp
set PYDIR=C:\Desktop\UnrealGenAISupport\Content\Python
set CFG=C:\depot\tools\mcp_unreal_maya_knowledge_config.json

echo ==========================================
echo Installing The Entire World AI Components
echo ==========================================
echo.

mkdir "%KDIR%" 2>nul
mkdir "%PYDIR%" 2>nul

echo Copying Knowledge MCP v2...
copy /Y "%~dp0build_knowledge_index_v2.py" "%KDIR%\build_knowledge_index_v2.py"
copy /Y "%~dp0knowledge_mcp_server_v2.py" "%KDIR%\knowledge_mcp_server_v2.py"

echo Copying quiet Maya MCP...
copy /Y "%~dp0maya_mcp_server_quiet.py" "%PYDIR%\maya_mcp_server_quiet.py"

echo.
echo Updating MCP config...
if exist "%CFG%" copy /Y "%CFG%" "%CFG%.bak" >nul

py -3.11 -c "import json, pathlib; cfg=pathlib.Path(r'%CFG%'); data=json.loads(cfg.read_text(encoding='utf-8')) if cfg.exists() else {'mcpServers':{}}; s=data.setdefault('mcpServers',{}); s['knowledge']={'type':'stdio','command':'py','args':['-3.11',r'C:\depot\tools\mcp_servers\knowledge_mcp\knowledge_mcp_server_v2.py']}; s['maya']={'type':'stdio','command':'py','args':['-3.11',r'C:\Desktop\UnrealGenAISupport\Content\Python\maya_mcp_server_quiet.py']}; cfg.parent.mkdir(parents=True, exist_ok=True); cfg.write_text(json.dumps(data,indent=2),encoding='utf-8'); print('Updated', cfg)"

echo.
echo Done.
pause