<#
.SYNOPSIS
  Daily job: start the database, collect new items, and write the northern-areas
  weather/hazard news CSV.

.DESCRIPTION
  Output:
    exports\northern-weather-news-YYYY-MM-DD.csv   items newly collected in the last 24h
    exports\northern-weather-news-latest.csv        copy of the most recent file
    exports\logs\run-YYYY-MM-DD.log                 log of the run
  Intended for Windows Task Scheduler (computer must be on at the scheduled time).
#>

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$stamp = Get-Date -Format "yyyy-MM-dd"
$exports = Join-Path $root "exports"
$logDir = Join-Path $exports "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "run-$stamp.log"
function Write-Log([string]$message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message" | Out-File -FilePath $log -Append -Encoding utf8
}

Write-Log "=== daily run started ==="

# 1. Docker engine (Docker Desktop)
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    $desktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $desktop) {
        Write-Log "Docker not running; starting Docker Desktop"
        Start-Process $desktop
    }
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Seconds 2
        docker info *> $null
        if ($LASTEXITCODE -eq 0) { break }
    }
}
if ($LASTEXITCODE -ne 0) { Write-Log "ERROR: Docker did not start"; exit 1 }

# 2. Database container
docker compose up -d db *> $null
for ($i = 0; $i -lt 60; $i++) {
    docker compose exec -T db pg_isready *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 2
}
if ($LASTEXITCODE -ne 0) { Write-Log "ERROR: database not ready"; exit 1 }

# 3. Migrate, collect, export
$py = Join-Path $root ".venv\Scripts\python.exe"
& $py -m app db migrate *>> $log

$summary = Join-Path $logDir "collect-$stamp.json"
& $py -m app collect 2>> $log | Out-File -FilePath $summary -Encoding utf8
$collectExit = $LASTEXITCODE
Write-Log "collect exit code: $collectExit (0 ok, 3 partial, 1 failed)"

$csv = Join-Path $exports "northern-weather-news-$stamp.csv"
& $py -m app export news-csv --since-hours 24 --output $csv *>> $log
if (Test-Path $csv) {
    Copy-Item $csv (Join-Path $exports "northern-weather-news-latest.csv") -Force
    Write-Log "wrote $csv"
} else {
    Write-Log "ERROR: CSV was not written"
    exit 1
}

Write-Log "=== daily run finished ==="
if ($collectExit -eq 1) { exit 1 }
exit 0
