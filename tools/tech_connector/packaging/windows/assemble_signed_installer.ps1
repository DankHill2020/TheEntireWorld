param(
    [ValidateSet("core", "combined")][string]$Tier = "core",
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$DistRoot = "dist\windows",
    [string]$ExpectedPublisher = "The Entire World"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $PSCommandPath
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\..\..")).Path
Set-Location $repoRoot

python tech_connector\packaging\release_gate.py --source-root $repoRoot --production
if ($LASTEXITCODE -ne 0) { throw "Production release gate failed." }

$freezeRoot = Join-Path $repoRoot "$DistRoot\frozen\$Tier\TechConnector"
if (-not (Test-Path -LiteralPath (Join-Path $freezeRoot "TechConnector.exe"))) {
    throw "Frozen application is missing at '$freezeRoot'."
}
& (Join-Path $scriptDir "verify_windows_signatures.ps1") `
    -Path $freezeRoot -Recurse -ExpectedPublisher $ExpectedPublisher

$isccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $iscc) {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { $iscc = $command.Source }
}
if (-not $iscc) { throw "Inno Setup 6 is required to assemble the installer." }

$productName = if ($Tier -eq "core") { "Tech Connector Core" } else { "Tech Connector + Official Tools Bundle" }
$appName = if ($Tier -eq "core") { "TechConnectorCore" } else { "TechConnectorCombined" }
$installerRoot = Join-Path $repoRoot "$DistRoot\installer"
New-Item -ItemType Directory -Force -Path $installerRoot | Out-Null

& $iscc `
    "/DAppName=$productName" `
    "/DAppVersion=$Version" `
    "/DAppPublisher=The Entire World" `
    "/DSourceDir=$freezeRoot" `
    "/DOutputDir=$installerRoot" `
    "/DOutputBaseFilename=$appName-$Version-win64-setup" `
    "/DExeName=TechConnector.exe" `
    "/DLicenseFile=$(Join-Path $repoRoot 'tech_connector\LICENSE.md')" `
    "/DInfoBeforeFile=$(Join-Path $repoRoot 'tech_connector\packaging\windows\installer_info.txt')" `
    (Join-Path $scriptDir "tech_connector_installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE." }

$installer = Join-Path $installerRoot "$appName-$Version-win64-setup.exe"
if (-not (Test-Path -LiteralPath $installer)) { throw "Installer was not created." }
Write-Output $installer
