param(
    [int]$Samples = 6,
    [int]$IntervalSeconds = 5,
    [string]$Label = "",
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Continue"

function New-SafeName([string]$Value) {
    $safe = $Value -replace '[^A-Za-z0-9_.-]+', '_'
    if ([string]::IsNullOrWhiteSpace($safe)) {
        return "capture"
    }
    return $safe.Trim("_")
}

function Add-Section([string]$Title, [scriptblock]$Body) {
    "`n==== $Title ====`n" | Out-File -LiteralPath $script:ReportPath -Append -Encoding utf8
    try {
        & $Body | Out-String -Width 240 | Out-File -LiteralPath $script:ReportPath -Append -Encoding utf8
    } catch {
        "ERROR: $($_.Exception.Message)" | Out-File -LiteralPath $script:ReportPath -Append -Encoding utf8
    }
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$labelPart = New-SafeName $Label
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $env:TEMP "tech_connector_graphics_stall"
}
$CaptureDir = Join-Path $OutputRoot "${timestamp}_${labelPart}"
New-Item -ItemType Directory -Force -Path $CaptureDir | Out-Null

$script:ReportPath = Join-Path $CaptureDir "graphics_stall_report.txt"
$JsonlPath = Join-Path $CaptureDir "samples.jsonl"
$EventsPath = Join-Path $CaptureDir "display_events.csv"
$DxDiagPath = Join-Path $CaptureDir "dxdiag.txt"

"Tech Connector Windows graphics stall capture" | Out-File -LiteralPath $ReportPath -Encoding utf8
"Time: $(Get-Date -Format o)" | Out-File -LiteralPath $ReportPath -Append -Encoding utf8
"Label: $Label" | Out-File -LiteralPath $ReportPath -Append -Encoding utf8
"Samples: $Samples every $IntervalSeconds seconds" | Out-File -LiteralPath $ReportPath -Append -Encoding utf8
"Output: $CaptureDir" | Out-File -LiteralPath $ReportPath -Append -Encoding utf8

Add-Section "OS" {
    Get-ComputerInfo | Select-Object OsName,OsVersion,WindowsVersion,OsBuildNumber,CsManufacturer,CsModel,CsProcessors,CsNumberOfLogicalProcessors,CsTotalPhysicalMemory
}

Add-Section "Display Adapters" {
    Get-CimInstance Win32_VideoController -ErrorAction Stop |
        Select-Object Name,DriverVersion,DriverDate,AdapterRAM,VideoProcessor,CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate
}

Add-Section "Monitors" {
    Get-CimInstance -Namespace root\wmi WmiMonitorID -ErrorAction Stop |
        ForEach-Object {
            [pscustomobject]@{
                InstanceName = $_.InstanceName
                Manufacturer = -join ($_.ManufacturerName | Where-Object { $_ } | ForEach-Object { [char]$_ })
                ProductCode = -join ($_.ProductCodeID | Where-Object { $_ } | ForEach-Object { [char]$_ })
                Serial = -join ($_.SerialNumberID | Where-Object { $_ } | ForEach-Object { [char]$_ })
                Active = $_.Active
            }
        }
}

Add-Section "Graphics Registry Settings" {
    $paths = @(
        "HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
        "HKCU:\Software\Microsoft\Avalon.Graphics",
        "HKCU:\Software\Microsoft\DirectX\UserGpuPreferences"
    )
    foreach ($path in $paths) {
        if (Test-Path $path) {
            "[$path]"
            Get-ItemProperty -Path $path | Select-Object * -ExcludeProperty PSPath,PSParentPath,PSChildName,PSDrive,PSProvider
        }
    }
}

Add-Section "High-Memory Interactive Processes" {
    Get-Process |
        Where-Object { $_.ProcessName -match "^(dwm|chrome|msedge|Code|Codex|ChatGPT|Discord|steam|steamwebhelper|Teams|Slack|firefox|ollama|python|maya|UnrealEditor|nvcontainer)$" } |
        Sort-Object WorkingSet64 -Descending |
        Select-Object -First 80 ProcessName,Id,CPU,WorkingSet64,PrivateMemorySize64,PagedMemorySize64,NonpagedSystemMemorySize64,HandleCount,StartTime
}

Add-Section "Recent Display/GPU/System Events" {
    $start = (Get-Date).AddDays(-7)
    Get-WinEvent -FilterHashtable @{LogName="System"; StartTime=$start} -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ProviderName -match "Display|nvlddmkm|WHEA|Kernel-Power|Desktop Window Manager" -or
            $_.Message -match "display driver|nvlddmkm|LiveKernelEvent|WHEA|hardware error"
        } |
        Select-Object TimeCreated,ProviderName,Id,LevelDisplayName,Message |
        Select-Object -First 80
}

try {
    Get-WinEvent -FilterHashtable @{LogName="System"; StartTime=(Get-Date).AddDays(-7)} -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ProviderName -match "Display|nvlddmkm|WHEA|Kernel-Power|Desktop Window Manager" -or
            $_.Message -match "display driver|nvlddmkm|LiveKernelEvent|WHEA|hardware error"
        } |
        Select-Object TimeCreated,ProviderName,Id,LevelDisplayName,Message |
        Export-Csv -LiteralPath $EventsPath -NoTypeInformation -Encoding utf8
} catch {
    "Could not export event CSV: $($_.Exception.Message)" | Out-File -LiteralPath $ReportPath -Append -Encoding utf8
}

$nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvidiaSmi) {
    Add-Section "NVIDIA GPU Summary" {
        & $nvidiaSmi.Source --query-gpu=timestamp,name,driver_version,pstate,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,power.limit,temperature.gpu,clocks.gr,clocks.mem --format=csv
    }
    Add-Section "NVIDIA GPU Processes" {
        & $nvidiaSmi.Source --query-compute-apps=pid,process_name,used_memory --format=csv
    }
}

try {
    Start-Process -FilePath "dxdiag.exe" -ArgumentList "/t", "`"$DxDiagPath`"" -WindowStyle Hidden -Wait
} catch {
    "Could not run dxdiag: $($_.Exception.Message)" | Out-File -LiteralPath $ReportPath -Append -Encoding utf8
}

for ($i = 1; $i -le [Math]::Max(1, $Samples); $i++) {
    $sample = [ordered]@{
        time = (Get-Date -Format o)
        label = $Label
        memory = $null
        processes = Get-Process |
            Where-Object { $_.ProcessName -match "^(dwm|chrome|msedge|Code|Codex|ChatGPT|Discord|steam|steamwebhelper|Teams|Slack|firefox|ollama|python|maya|UnrealEditor|nvcontainer)$" } |
            Sort-Object WorkingSet64 -Descending |
            Select-Object -First 80 ProcessName,Id,CPU,WorkingSet64,PrivateMemorySize64,PagedMemorySize64,NonpagedSystemMemorySize64,HandleCount
    }
    try {
        $sample.memory = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop | Select-Object FreePhysicalMemory,TotalVisibleMemorySize
    } catch {
        $sample.memory_error = $_.Exception.Message
    }
    if ($nvidiaSmi) {
        try {
            $sample.nvidia_gpu = & $nvidiaSmi.Source --query-gpu=timestamp,name,driver_version,pstate,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,temperature.gpu --format=csv,noheader,nounits
            $sample.nvidia_processes = & $nvidiaSmi.Source --query-compute-apps=pid,process_name,used_memory --format=csv,noheader,nounits
        } catch {
            $sample.nvidia_error = $_.Exception.Message
        }
    }
    ($sample | ConvertTo-Json -Depth 6 -Compress) | Out-File -LiteralPath $JsonlPath -Append -Encoding utf8
    if ($i -lt $Samples) {
        Start-Sleep -Seconds $IntervalSeconds
    }
}

Add-Section "Capture Files" {
    Get-ChildItem -LiteralPath $CaptureDir | Select-Object Name,Length,LastWriteTime
}

Write-Host "Graphics stall capture written to: $CaptureDir"
