@echo off
setlocal
title Rebuild The Entire World AST Index

cd /d "%~dp0"

set KDIR=C:\depot\tools\mcp_servers\knowledge_mcp
set INDEXER=%KDIR%\build_knowledge_index_v2.py

echo ==========================================
echo Rebuilding The Entire World AST Index
echo ==========================================
echo.

if not exist "%KDIR%" mkdir "%KDIR%"

echo Installing patched AST indexer...
copy /Y "%~dp0build_knowledge_index_v2.py" "%INDEXER%"

echo.
echo Starting AST index build...
py -3.11 "%INDEXER%"

echo.
echo Done.
pause