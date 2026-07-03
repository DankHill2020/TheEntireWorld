@echo off
setlocal
title DEV Rebuild AST Index

cd /d "%~dp0.."

set KDIR=C:\depot\tools\mcp_servers\knowledge_mcp
set INDEXER=%KDIR%\build_knowledge_index_v2.py

mkdir "%KDIR%" 2>nul
copy /Y "%~dp0..\build_knowledge_index_v2.py" "%INDEXER%"

py -3.11 "%INDEXER%"
pause