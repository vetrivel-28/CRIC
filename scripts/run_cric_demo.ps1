param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765,
    [ValidateSet("postgres", "csv")]
    [string]$Source = "postgres"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$dataRoot = Join-Path $projectRoot "data"
if ($Source -eq "csv" -and -not (Test-Path -LiteralPath $dataRoot -PathType Container)) {
    Write-Error "CRIC data directory is missing: $dataRoot"
    exit 1
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "Python was not found on PATH. Activate the existing CRIC Python environment first."
    exit 1
}

$mutex = [System.Threading.Mutex]::new($false, "Local\CRICDemoPort$Port")
$ownsMutex = $false
try {
    try {
        $ownsMutex = $mutex.WaitOne(0)
    }
    catch [System.Threading.AbandonedMutexException] {
        $ownsMutex = $true
    }
    if (-not $ownsMutex) {
        Write-Error "A CRIC demo launcher already owns port $Port. No second server was started."
        exit 1
    }

    $probe = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
    $probeStarted = $false
    try {
        $probe.Start()
        $probeStarted = $true
    }
    catch {
        Write-Error "Port $Port on 127.0.0.1 is already occupied or unavailable. No server was started."
        exit 1
    }
    finally {
        if ($probeStarted) {
            $probe.Stop()
        }
    }

    Set-Location -LiteralPath $projectRoot
    if ($Source -eq "postgres") {
        Write-Host "Starting CRIC with PostgreSQL analytics. Configure CRIC_DB_* or PG* environment variables."
    }
    else {
        Write-Host "Starting CRIC in explicit CSV mode with historical datasets from $dataRoot"
    }
    Write-Host "Open http://127.0.0.1:$Port/ after the local service reports ready."
    Write-Host "Press Ctrl+C in this window to stop the service."

    & $python.Source -m backend.api --source $Source --data-root $dataRoot --port $Port
    if ($LASTEXITCODE -ne 0) {
        Write-Error "The CRIC local service exited with code $LASTEXITCODE."
        exit $LASTEXITCODE
    }
}
finally {
    if ($ownsMutex) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
