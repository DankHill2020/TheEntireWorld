@echo off
setlocal
title Patch Installed Knowledge Indexer FTS Fix

cd /d "%~dp0"

set KDIR=C:\depot\tools\mcp_servers\knowledge_mcp
set INDEXER=%KDIR%\build_knowledge_index_v2.py

if not exist "%KDIR%" mkdir "%KDIR%"

echo Copying patched build_knowledge_index_v2.py...
copy /Y "%~dp0build_knowledge_index_v2.py" "%INDEXER%"

echo.
echo Patched:
echo %INDEXER%
echo.
echo Now rebuild the index with:
echo rebuild_ast_index.bat
echo.
pause