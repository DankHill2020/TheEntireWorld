param(
    [ValidateSet("core", "official-tools", "combined", "reasoning-runtime", "full-tools")]
    [string]$Tier = "core",

    [ValidateSet("stage", "freeze", "installer")]
    [string]$Mode = "freeze",

    [string]$Version = "",
    [string]$Python = "auto",
    [switch]$NoClean,
    [switch]$SkipDependencyInstall
)

$script = Join-Path $PSScriptRoot "build_windows_package.ps1"
$argsList = @(
    "-ExecutionPolicy", "Bypass",
    "-File", $script,
    "-Tier", $Tier,
    "-Mode", $Mode,
    "-Python", $Python
)
if ($Version) {
    $argsList += @("-Version", $Version)
}
if ($NoClean) {
    $argsList += "-NoClean"
}
if ($SkipDependencyInstall) {
    $argsList += "-SkipDependencyInstall"
}

& powershell @argsList
