param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [string]$ExpectedPublisher = "The Entire World",
    [string]$ExpectedExecutable = "TechConnector.exe"
)

$ErrorActionPreference = "Stop"
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$scriptDir = Split-Path -Parent $PSCommandPath

& (Join-Path $scriptDir "verify_windows_signatures.ps1") `
    -Path $installerPath -ExpectedPublisher $ExpectedPublisher

$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("tc-signed-installer-" + [guid]::NewGuid().ToString("N"))
$installRoot = Join-Path $testRoot "installed"
New-Item -ItemType Directory -Force -Path $testRoot | Out-Null

try {
    $installArguments = @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
        "/DIR=$installRoot"
    )
    foreach ($pass in 1..2) {
        $install = Start-Process -FilePath $installerPath -ArgumentList $installArguments -Wait -PassThru
        if ($install.ExitCode -ne 0) {
            throw "Silent install/repair pass $pass failed with exit code $($install.ExitCode)."
        }
        $application = Join-Path $installRoot $ExpectedExecutable
        if (-not (Test-Path -LiteralPath $application)) {
            throw "Installed application is missing after pass ${pass}: $application"
        }
        & (Join-Path $scriptDir "verify_windows_signatures.ps1") `
            -Path $installRoot -Recurse -ExpectedPublisher $ExpectedPublisher
    }

    $application = Join-Path $installRoot $ExpectedExecutable
    $process = Start-Process -FilePath $application -PassThru
    if (-not $process.WaitForExit(10000)) {
        Stop-Process -Id $process.Id -Force
    } elseif ($process.ExitCode -ne 0) {
        throw "Installed application exited during launch smoke with code $($process.ExitCode)."
    }

    $uninstaller = Join-Path $installRoot "unins000.exe"
    if (-not (Test-Path -LiteralPath $uninstaller)) {
        throw "Inno Setup uninstaller is missing: $uninstaller"
    }
    $uninstall = Start-Process -FilePath $uninstaller `
        -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") `
        -Wait -PassThru
    if ($uninstall.ExitCode -ne 0) {
        throw "Silent uninstall failed with exit code $($uninstall.ExitCode)."
    }
    if (Test-Path -LiteralPath (Join-Path $installRoot $ExpectedExecutable)) {
        throw "Installed executable remains after uninstall."
    }
    Write-Host "Signed installer install/repair/launch/uninstall smoke passed."
}
finally {
    if (Test-Path -LiteralPath $testRoot) {
        $resolvedTestRoot = [System.IO.Path]::GetFullPath($testRoot)
        $resolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        if (-not $resolvedTestRoot.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean installer test path outside the temporary directory: $resolvedTestRoot"
        }
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
