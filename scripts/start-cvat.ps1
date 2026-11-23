<#
.SYNOPSIS
  Start a local CVAT Community Edition stack managed by LabelGuard.

.DESCRIPTION
  Clones CVAT at a pinned release tag into a folder OUTSIDE the LabelGuard
  repository (default: %USERPROFILE%\labelguard-cvat) and starts it with
  Docker Compose under the project name "labelguard-cvat", bound to localhost.
  Other Docker projects and containers are not touched.

  Requirements: Docker Desktop with the WSL2 backend, git, ~15 GB free disk.

.EXAMPLE
  .\scripts\start-cvat.ps1
  .\scripts\start-cvat.ps1 -Tag v2.22.0 -CvatDir D:\cvat
#>
param(
    [string]$Tag = "v2.83.0",  # latest CVAT release on 2026-11-23; pair with cvat-sdk==2.83.0
    [string]$CvatDir = (Join-Path $env:USERPROFILE "labelguard-cvat"),
    [int]$MinFreeGB = 15,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$Project = "labelguard-cvat"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker is not installed. Install Docker Desktop (WSL2 backend) first."
}
docker info *> $null
if ($LASTEXITCODE -ne 0) { Write-Error "Docker is installed but not running. Start Docker Desktop." }

$drive = (Get-Item $env:USERPROFILE).PSDrive
$freeGB = [math]::Round((Get-PSDrive $drive.Name).Free / 1GB, 1)
if ($freeGB -lt $MinFreeGB -and -not $Force) {
    Write-Error "Only $freeGB GB free on $($drive.Name):. CVAT images need about $MinFreeGB GB. Free space or pass -Force."
}

if (-not (Test-Path $CvatDir)) {
    git clone --depth 1 --branch $Tag https://github.com/cvat-ai/cvat.git $CvatDir
} else {
    Write-Host "Reusing existing CVAT checkout at $CvatDir"
}

Push-Location $CvatDir
try {
    $env:CVAT_HOST = "localhost"
    # CVAT's stock compose publishes Traefik on all interfaces. This override (written
    # next to the CVAT checkout, not into it) rebinds it to 127.0.0.1 only.
    # Needs Docker Compose >= 2.24 for the !override tag. Not yet verified on a real run.
    $override = Join-Path $CvatDir "docker-compose.labelguard-localhost.yml"
    @"
services:
  traefik:
    ports: !override
      - "127.0.0.1:8080:8080"
      - "127.0.0.1:8090:8090"
"@ | Set-Content -Path $override -Encoding ascii
    docker compose -p $Project -f docker-compose.yml -f $override up -d
    Write-Host "Waiting for http://localhost:8080/api/server/about ..."
    $ok = $false
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://localhost:8080/api/server/about"
            if ($r.StatusCode -eq 200) { $ok = $true; break }
        } catch { Start-Sleep -Seconds 5 }
    }
    if (-not $ok) { Write-Error "CVAT did not become ready in time. Check: docker compose -p $Project ps" }
    Write-Host "CVAT is up at http://localhost:8080"
    Write-Host "Create an admin account once (interactive, password is not logged):"
    Write-Host "  docker exec -it cvat_server bash -ic 'python3 ~/manage.py createsuperuser'"
} finally {
    Pop-Location
}
