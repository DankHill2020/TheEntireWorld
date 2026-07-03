@echo off
title Build Knowledge Index

echo Building knowledge index...
py -3.11 "C:\depot\tools\mcp_servers\knowledge_mcp\build_knowledge_index.py"

echo.
echo Done.
pause