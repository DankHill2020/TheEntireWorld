@echo off
setlocal

rem Codex and some launchers can provide both PATH and Path. MSBuild's .NET
rem process launcher rejects that case-insensitive duplicate, so normalize it.
set "TC_QUALIFICATION_PATH=%PATH%"
set "PATH="
set "Path=%TC_QUALIFICATION_PATH%"
set "TC_QUALIFICATION_PATH="

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" (
  echo Visual Studio Installer's vswhere.exe was not found. 1>&2
  exit /b 2
)

set "VSROOT="
for /f "usebackq tokens=*" %%I in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSROOT=%%I"
if not defined VSROOT (
  echo A Visual Studio installation with the C++ x64 toolchain was not found. 1>&2
  exit /b 3
)

call "%VSROOT%\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64
if errorlevel 1 exit /b %errorlevel%
where cl.exe >nul 2>nul
if errorlevel 1 (
  echo Visual Studio initialized, but cl.exe is not available on PATH. 1>&2
  echo Selected installation: %VSROOT% 1>&2
  exit /b 4
)

set "NATIVE_ROOT=%~dp0..\game_engine\native"
set "BUILD_ROOT=%NATIVE_ROOT%\.tech_connector\cmake\LaunchQualification"

cmake -S "%NATIVE_ROOT%" -B "%BUILD_ROOT%" -G "Visual Studio 17 2022" -A x64
if errorlevel 1 exit /b %errorlevel%

cmake --build "%BUILD_ROOT%" --config Release --parallel 4
if errorlevel 1 exit /b %errorlevel%

ctest --test-dir "%BUILD_ROOT%" -C Release --output-on-failure
exit /b %errorlevel%
