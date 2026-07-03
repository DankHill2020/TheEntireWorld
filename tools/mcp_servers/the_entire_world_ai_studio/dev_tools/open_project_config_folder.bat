@echo off
setlocal
title Open The Entire World AI Config

set CFGDIR=%LOCALAPPDATA%\TA_AI_Studio_MCPHost

if not exist "%CFGDIR%" mkdir "%CFGDIR%"

explorer "%CFGDIR%"