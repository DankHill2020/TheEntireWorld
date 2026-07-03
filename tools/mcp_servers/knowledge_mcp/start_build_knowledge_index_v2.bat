@echo off
title Build Knowledge Index v2 AST

echo Building AST knowledge index...
py -3.11 "C:\depot\tools\mcp_servers\knowledge_mcp\build_knowledge_index_v2.py"

echo.
echo Done.
pause