<#
.SYNOPSIS
    Starts (or restarts) the WeatherGPT backend and frontend for local development.

.DESCRIPTION
    - Kills any uvicorn process already bound to the backend port
    - Starts FastAPI on http://127.0.0.1:3001 and waits until /api/health answers
    - Starts the Vite dev server on http://localhost:5173

.PARAMETER BackendOnly
    Only restart the backend. Use this after editing backend/.env, because the
    settings are read once at startup.

.EXAMPLE
    .\scripts\start-dev.ps1
    .\scripts\start-dev.ps1 -BackendOnly
#>
[CmdletBinding()]
param(
    [switch]$BackendOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$logDir = Join-Path $env:LOCALAPPDATA "Temp\opencode"
$backendPort = 3001

function Stop-Backend {
    # Match both the python interpreter and any cmd.exe wrapper left behind.
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='cmd.exe'" |
        Where-Object { $_.CommandLine -like "*uvicorn*$backendPort*" } |
        ForEach-Object {
            Write-Host "  stopping backend (pid $($_.ProcessId))"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Start-Sleep -Seconds 2
}

function Start-Detached {
    <#
        Starts a process with no inherited console handles.
        Using WMI instead of Start-Process keeps the child from holding the
        parent's stdout pipe open, so this script returns immediately.
    #>
    param(
        [Parameter(Mandatory)] [string] $FilePath,
        [Parameter(Mandatory)] [string[]] $Arguments,
        [Parameter(Mandatory)] [string] $WorkingDirectory,
        [Parameter(Mandatory)] [string] $OutLog
    )

    # Only quote arguments that contain spaces; quoting everything shifts the
    # balance of quote characters and makes cmd.exe mis-parse the line.
    $cmdArgs = ($Arguments | ForEach-Object {
        if ($_ -match '\s') { '"' + $_ + '"' } else { $_ }
    }) -join " "

    # cmd.exe rule: with more than two quotes it strips the first and last
    # quote on the line, so the executable itself must be quoted inside.
    $inner = '"' + $FilePath + '" ' + $cmdArgs + ' > "' + $OutLog + '" 2>&1'
    $commandLine = 'cmd.exe /c "' + $inner + '"'

    Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine     = $commandLine
        CurrentDirectory = $WorkingDirectory
    } | Out-Null
}

function Start-Backend {
    Write-Host "starting backend on http://127.0.0.1:$backendPort ..."
    $python = Join-Path $root ".venv\Scripts\python.exe"
    if (-not (Test-Path $python)) {
        $python = Join-Path $backendDir ".venv\Scripts\python.exe"
    }
    if (-not (Test-Path $python)) {
        throw "No Python virtual environment found. Create one and run: pip install -r backend\requirements.txt"
    }

    Start-Detached `
        -FilePath $python `
        -Arguments @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$backendPort") `
        -WorkingDirectory $backendDir `
        -OutLog (Join-Path $logDir "backend.log")

    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$backendPort/api/health" -TimeoutSec 3
            Write-Host "  backend is up (v$($health.version))"
            Write-Host "  anthropic configured: $($health.providers.anthropic.configured)"
            return
        } catch {
            # keep waiting
        }
    }
    Write-Warning "backend did not answer /api/health in time. Check $logDir\backend.err.log"
}

Write-Host "WeatherGPT dev environment"
Stop-Backend
Start-Backend

if (-not $BackendOnly) {
    Write-Host "starting frontend on http://localhost:5173 ..."
    Start-Detached `
        -FilePath "npm.cmd" `
        -Arguments @("run", "dev") `
        -WorkingDirectory $frontendDir `
        -OutLog (Join-Path $logDir "vite.log")
    Start-Sleep -Seconds 5
    Write-Host "  frontend: http://localhost:5173"
}

Write-Host ""
Write-Host "logs: $logDir"
