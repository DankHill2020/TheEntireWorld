@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=!SCRIPT_DIR:\=\\!"
set "SCRIPT_PATH=!SCRIPT_DIR!maya_setup.py"

start "" "C:\Program Files\Autodesk\Maya2023\bin\maya.exe" -command "python(\"__file__=r'!SCRIPT_PATH!'; exec(open(r'!SCRIPT_PATH!').read())\")"
