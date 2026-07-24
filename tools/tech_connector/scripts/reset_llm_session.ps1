[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$KeepNzxtCam,
    [switch]$KeepExplorer,
    [switch]$IncludeBuildHelpers,
    [switch]$CloseModelUis
)

$ErrorActionPreference = "SilentlyContinue"
$script:ResetCmdlet = $PSCmdlet

function Get-MemorySnapshot {
    $samples = Get-Counter `
        "\Memory\Available MBytes", `
        "\Memory\Committed Bytes", `
        "\Memory\Commit Limit"
    $values = @{}
    foreach ($sample in $samples.CounterSamples) {
        $values[$sample.Path.ToLowerInvariant()] = [double]$sample.CookedValue
    }
    $available = ($values.GetEnumerator() | Where-Object Key -Like "*\memory\available mbytes").Value
    $committed = ($values.GetEnumerator() | Where-Object Key -Like "*\memory\committed bytes").Value
    $limit = ($values.GetEnumerator() | Where-Object Key -Like "*\memory\commit limit").Value
    [pscustomobject]@{
        AvailableRAM_GB = [math]::Round($available / 1024, 2)
        Committed_GB = [math]::Round($committed / 1GB, 2)
        CommitLimit_GB = [math]::Round($limit / 1GB, 2)
    }
}

function Get-GpuSnapshot {
    if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
        return $null
    }
    $line = nvidia-smi `
        --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu `
        --format=csv,noheader,nounits |
        Select-Object -First 1
    if (-not $line) {
        return $null
    }
    $parts = @($line -split "," | ForEach-Object { $_.Trim() })
    [pscustomobject]@{
        GPU = $parts[0]
        TotalVRAM_MB = [int]$parts[1]
        UsedVRAM_MB = [int]$parts[2]
        FreeVRAM_MB = [int]$parts[3]
        GPUUtilization = "$($parts[4])%"
    }
}

function Stop-ProcessesByPattern {
    param(
        [string[]]$Patterns,
        [string]$Label
    )
    $matches = Get-Process | Where-Object {
        $name = $_.ProcessName
        foreach ($pattern in $Patterns) {
            if ($name -like $pattern) {
                return $true
            }
        }
        return $false
    }
    foreach ($process in $matches) {
        if ($script:ResetCmdlet.ShouldProcess(
            "$($process.ProcessName) [$($process.Id)]",
            "Stop $Label process"
        )) {
            Write-Host "Stopping $Label process $($process.ProcessName) [$($process.Id)]"
            Stop-Process -Id $process.Id -Force
        }
    }
}

function Stop-OllamaModels {
    if (Get-Command ollama -ErrorAction SilentlyContinue) {
        $rows = @(ollama ps 2>$null | Select-Object -Skip 1)
        foreach ($row in $rows) {
            $model = ($row -split "\s+")[0]
            if ($model -and $script:ResetCmdlet.ShouldProcess($model, "Unload Ollama model")) {
                Write-Host "Unloading Ollama model $model"
                ollama stop $model | Out-Null
            }
        }
    }
    Stop-ProcessesByPattern `
        -Patterns @("ollama*", "llama-server*", "llama_cpp_server*") `
        -Label "model runtime"
}

$beforeMemory = Get-MemorySnapshot
$beforeGpu = Get-GpuSnapshot

Write-Host ""
Write-Host "LLM resource reset started."
Write-Host "Before:"
$beforeMemory | Format-Table -AutoSize
if ($beforeGpu) {
    $beforeGpu | Format-Table -AutoSize
}

Stop-OllamaModels

if ($CloseModelUis) {
    Stop-ProcessesByPattern `
        -Patterns @("LM Studio*", "lmstudio*", "koboldcpp*") `
        -Label "model UI"
}

if (-not $KeepNzxtCam) {
    Stop-ProcessesByPattern `
        -Patterns @("NZXT*") `
        -Label "NZXT CAM"
}

if ($IncludeBuildHelpers) {
    Stop-ProcessesByPattern `
        -Patterns @("AutomationTool*", "UnrealBuildTool*", "UbaAgent*", "UbaSessionServer*") `
        -Label "Unreal build helper"
}

if (-not $KeepExplorer) {
    $explorer = @(Get-Process explorer)
    foreach ($process in $explorer) {
        if ($PSCmdlet.ShouldProcess("Explorer [$($process.Id)]", "Restart process")) {
            Write-Host "Restarting Explorer [$($process.Id)]"
            Stop-Process -Id $process.Id -Force
        }
    }
    if (-not $WhatIfPreference) {
        Start-Sleep -Milliseconds 750
        Start-Process explorer.exe
    }
}

Start-Sleep -Seconds 2
$afterMemory = Get-MemorySnapshot
$afterGpu = Get-GpuSnapshot

Write-Host ""
Write-Host "After:"
$afterMemory | Format-Table -AutoSize
if ($afterGpu) {
    $afterGpu | Format-Table -AutoSize
}

$ramRecovered = $afterMemory.AvailableRAM_GB - $beforeMemory.AvailableRAM_GB
$vramRecovered = if ($beforeGpu -and $afterGpu) {
    $afterGpu.FreeVRAM_MB - $beforeGpu.FreeVRAM_MB
} else {
    0
}

Write-Host (
    "Reset complete. Available RAM change: {0:+0.00;-0.00;0.00} GB; free VRAM change: {1:+0;-0;0} MB." `
        -f $ramRecovered, $vramRecovered
)
if ($WhatIfPreference) {
    Write-Host "WhatIf only: no processes were stopped."
} elseif ($KeepNzxtCam) {
    Write-Host "NZXT CAM was left running."
} else {
    Write-Host "NZXT CAM remains stopped."
}
