
param(
    [ValidateSet("reasoning-runtime", "full-tools")]
    [string]$Tier = "reasoning-runtime",

    [ValidateSet("stage", "freeze", "installer")]
    [string]$Mode = "freeze",

    [string]$Version = "",
    [string]$Python = "auto",
    [string]$DistRoot = "dist\windows",
    [switch]$NoClean,
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    $scriptPath = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptPath "..\..\..")).Path
}

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    $parts = $Python -split " "
    $exe = if (Test-Path -LiteralPath $Python) { $Python } else { $parts[0] }
    $baseArgs = @()
    if ($exe -ne $Python -and $parts.Length -gt 1) {
        $baseArgs = $parts[1..($parts.Length - 1)]
    }
    & $exe @baseArgs @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $Python $($Args -join ' ')"
    }
}

function Get-PythonInfo {
    param([string]$Command)
    $parts = $Command -split " "
    $exe = if (Test-Path -LiteralPath $Command) { $Command } else { $parts[0] }
    $baseArgs = @()
    if ($exe -ne $Command -and $parts.Length -gt 1) {
        $baseArgs = $parts[1..($parts.Length - 1)]
    }
    $payload = & $exe @baseArgs -c "import json, platform, struct, sys; print(json.dumps({'major': sys.version_info.major, 'minor': sys.version_info.minor, 'micro': sys.version_info.micro, 'implementation': platform.python_implementation(), 'bits': struct.calcsize('P') * 8, 'executable': sys.executable}))"
    if ($LASTEXITCODE -ne 0 -or -not $payload) {
        throw "Could not run release Python: $Command"
    }
    return ($payload | ConvertFrom-Json)
}

function Resolve-ReleasePython {
    param([string]$Requested)
    if ($Requested -and $Requested -ne "auto") {
        return $Requested
    }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python314\python.exe"),
        (Join-Path $env:ProgramFiles "Python314\python.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return "py -3.14"
}

function Assert-ReleasePython {
    param($Info)
    if ($Info.implementation -ne "CPython" -or $Info.major -ne 3 -or $Info.minor -ne 14 -or $Info.bits -ne 64) {
        throw "Release builds require 64-bit CPython 3.14.x. Found $($Info.implementation) $($Info.major).$($Info.minor).$($Info.micro) ($($Info.bits)-bit) at $($Info.executable)."
    }
}

function Read-AppVersion {
    param([string]$RepoRoot)
    $constants = Join-Path $RepoRoot "tech_connector\models\constants.py"
    $match = Select-String -LiteralPath $constants -Pattern 'APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($match -and $match.Matches.Count -gt 0) {
        return $match.Matches[0].Groups[1].Value.TrimStart("v")
    }
    return "0.0.0"
}

function Find-InnoCompiler {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    return ""
}

function Build-NativeGraphRuntime {
    param([string]$RepoRoot, [string]$OutputRoot, [string]$StageDir)
    $cmake = Get-Command cmake.exe -ErrorAction SilentlyContinue
    if (-not $cmake) {
        throw "CMake is required to build the TC native graph runtime."
    }
    $source = Join-Path $RepoRoot "tech_connector\game_engine\native"
    $build = Join-Path $OutputRoot "native\graph-runtime"
    & $cmake.Source -S $source -B $build -A x64 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Native graph runtime configure failed." }
    & $cmake.Source --build $build --config Release --parallel | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Native graph runtime build failed." }
    & $cmake.Source --build $build --config Release --target tc_graph_runtime_tests | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Native graph runtime test target failed to build." }
    $ctest = Join-Path (Split-Path -Parent $cmake.Source) "ctest.exe"
    & $ctest --test-dir $build -C Release --output-on-failure | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Native graph runtime tests failed." }
    $dll = Get-ChildItem -LiteralPath $build -Filter tc_graph_runtime.dll -Recurse | Select-Object -First 1
    if (-not $dll) { throw "Native graph runtime DLL was not produced." }
    $player = Get-ChildItem -LiteralPath $build -Filter tc_player.exe -Recurse | Select-Object -First 1
    if (-not $player) { throw "Native TC player executable was not produced." }
    $destination = Join-Path $StageDir "tech_connector\game_engine\native\bin"
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    Copy-Item -LiteralPath $dll.FullName -Destination (Join-Path $destination $dll.Name) -Force
    Copy-Item -LiteralPath $player.FullName -Destination (Join-Path $destination $player.Name) -Force
    return (Join-Path $destination $dll.Name)
}

$repoRoot = Resolve-RepoRoot
Set-Location $repoRoot

if (-not $Version) {
    $Version = Read-AppVersion $repoRoot
}

$distRootAbs = Join-Path $repoRoot $DistRoot
$stageRoot = Join-Path $distRootAbs "staged"
$stageDir = Join-Path $stageRoot $Tier
$buildRoot = Join-Path $distRootAbs "build\$Tier"
$freezeRoot = Join-Path $distRootAbs "frozen\$Tier"
$installerRoot = Join-Path $distRootAbs "installer"
$zipRoot = Join-Path $distRootAbs "portable"
$appName = if ($Tier -eq "reasoning-runtime") { "TechConnectorReasoningRuntime" } else { "TechConnectorFullTools" }
$productName = if ($Tier -eq "reasoning-runtime") { "Tech Connector Reasoning Runtime" } else { "Tech Connector Full Tools" }
$exeName = "TechConnector"

Write-Host "Repo: $repoRoot"
Write-Host "Tier: $Tier"
Write-Host "Mode: $Mode"
Write-Host "Version: $Version"

$Python = Resolve-ReleasePython $Python
$pythonInfo = Get-PythonInfo $Python
Assert-ReleasePython $pythonInfo
Write-Host "Python: $($pythonInfo.implementation) $($pythonInfo.major).$($pythonInfo.minor).$($pythonInfo.micro) ($($pythonInfo.bits)-bit)"

$stageArgs = @("tech_connector\packaging\stage_package.py", $Tier, "--out", $stageRoot)
if ($NoClean) {
    $stageArgs += "--no-clean"
}
Invoke-Python @stageArgs

if ($Mode -eq "stage") {
    Write-Host "Staged package: $stageDir"
    exit 0
}

$nativeGraphDll = Build-NativeGraphRuntime $repoRoot $buildRoot $stageDir
$nativePlayerExe = Join-Path (Split-Path -Parent $nativeGraphDll) "tc_player.exe"

$venvDir = Join-Path $distRootAbs ".venv-build"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    $venvInfo = Get-PythonInfo $venvPython
    if ($venvInfo.major -ne 3 -or $venvInfo.minor -ne 14 -or $venvInfo.bits -ne 64) {
        Write-Host "Replacing stale build environment created with Python $($venvInfo.major).$($venvInfo.minor)."
        Remove-Item -LiteralPath $venvDir -Recurse -Force
    }
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    Invoke-Python -m venv $venvDir
}

if (-not $SkipDependencyInstall) {
    & $venvPython -m pip install --upgrade pip wheel setuptools
    & $venvPython -m pip install -r tech_connector\packaging\requirements-build.txt
    & $venvPython -m pip install -r tech_connector\packaging\requirements-runtime.txt
}

$launcherDir = Join-Path $buildRoot "launcher"
New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null
$launcherPath = Join-Path $launcherDir "tech_connector_frozen_entry.py"
@"
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
os.environ.setdefault("AI_STUDIO_TOOLS_ROOT", str(root))
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from tech_connector.app.application import run_application

if __name__ == "__main__":
    run_application()
"@ | Set-Content -LiteralPath $launcherPath -Encoding ASCII

if (-not $NoClean) {
    Remove-Item -LiteralPath $freezeRoot -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force -Path $freezeRoot | Out-Null

$pyiArgs = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--onedir",
    "--name", $exeName,
    "--distpath", $freezeRoot,
    "--workpath", (Join-Path $buildRoot "pyinstaller-work"),
    "--specpath", (Join-Path $buildRoot "spec"),
    "--paths", $stageDir,
    "--add-data", "$stageDir\tech_connector\assets;tech_connector\assets",
    "--add-data", "$stageDir\tech_connector\data;tech_connector\data",
    "--add-data", "$stageDir\tech_connector\knowledge;tech_connector\knowledge",
    "--collect-submodules", "tech_connector",
    "--collect-submodules", "reasoning_runtime",
    "--add-binary", "$nativeGraphDll;tech_connector\game_engine\native\bin",
    "--add-binary", "$nativePlayerExe;tech_connector\game_engine\native\bin",
    $launcherPath
)

if ($Tier -eq "full-tools") {
    if (Test-Path -LiteralPath "$stageDir\maya_tools") {
        $pyiArgs += @("--add-data", "$stageDir\maya_tools;maya_tools")
    }
    if (Test-Path -LiteralPath "$stageDir\motionbuilder_tools") {
        $pyiArgs += @("--add-data", "$stageDir\motionbuilder_tools;motionbuilder_tools")
    }
    if (Test-Path -LiteralPath "$stageDir\plugins") {
        $pyiArgs += @("--add-data", "$stageDir\plugins;plugins")
    }
}

& $venvPython -m PyInstaller @pyiArgs

$frozenAppDir = Join-Path $freezeRoot $exeName
$frozenExe = Join-Path $frozenAppDir "$exeName.exe"
if (-not (Test-Path -LiteralPath $frozenExe)) {
    throw "Frozen executable was not created: $frozenExe"
}

@"
CPython $($pythonInfo.major).$($pythonInfo.minor).$($pythonInfo.micro)
$($pythonInfo.bits)-bit
Built from: $($pythonInfo.executable)
"@ | Set-Content -LiteralPath (Join-Path $frozenAppDir "PYTHON_RUNTIME.txt") -Encoding ASCII

New-Item -ItemType Directory -Force -Path $zipRoot | Out-Null
$zipPath = Join-Path $zipRoot "$appName-$Version-win64-portable.zip"
Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
Push-Location $frozenAppDir
try {
    & tar.exe -a -c -f $zipPath *
    if ($LASTEXITCODE -ne 0) { throw "Portable ZIP creation failed." }
} finally {
    Pop-Location
}
Write-Host "Portable zip: $zipPath"

if ($Mode -eq "freeze") {
    Write-Host "Frozen app: $frozenAppDir"
    exit 0
}

$iscc = Find-InnoCompiler
if (-not $iscc) {
    Write-Warning "Inno Setup compiler (ISCC.exe) was not found. Install Inno Setup 6 to produce installer EXEs."
    Write-Host "Frozen app remains available at: $frozenAppDir"
    Write-Host "Portable zip remains available at: $zipPath"
    exit 0
}

New-Item -ItemType Directory -Force -Path $installerRoot | Out-Null
$iss = Join-Path $repoRoot "tech_connector\packaging\windows\tech_connector_installer.iss"
& $iscc `
    "/DAppName=$productName" `
    "/DAppVersion=$Version" `
    "/DAppPublisher=The Entire World" `
    "/DSourceDir=$frozenAppDir" `
    "/DOutputDir=$installerRoot" `
    "/DOutputBaseFilename=$appName-$Version-win64-setup" `
    "/DExeName=$exeName.exe" `
    $iss

$installer = Join-Path $installerRoot "$appName-$Version-win64-setup.exe"
Write-Host "Installer: $installer"
