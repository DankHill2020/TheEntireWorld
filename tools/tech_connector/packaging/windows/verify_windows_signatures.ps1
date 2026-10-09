param(
    [Parameter(Mandatory = $true)][string]$Path,
    [string]$ExpectedPublisher = "",
    [switch]$Recurse
)

$ErrorActionPreference = "Stop"
$resolved = (Resolve-Path -LiteralPath $Path).Path
$files = if ((Get-Item -LiteralPath $resolved).PSIsContainer) {
    Get-ChildItem -LiteralPath $resolved -File -Recurse:$Recurse | Where-Object {
        $_.Extension -in @(".exe", ".dll", ".msi", ".msix")
    }
} else {
    @(Get-Item -LiteralPath $resolved)
}
if (-not $files) { throw "No signable Windows artifacts were found at '$resolved'." }

$failures = @()
foreach ($file in $files) {
    $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
    if ($signature.Status -ne "Valid") {
        $failures += "$($file.FullName): $($signature.Status)"
        continue
    }
    if ($ExpectedPublisher -and $signature.SignerCertificate.Subject -notlike "*$ExpectedPublisher*") {
        $failures += "$($file.FullName): unexpected publisher '$($signature.SignerCertificate.Subject)'"
    }
}
if ($failures) {
    throw "Windows signature verification failed:`n$($failures -join "`n")"
}
Write-Host "Verified $($files.Count) signed Windows artifact(s)."

