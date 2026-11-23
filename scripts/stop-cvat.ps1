<#
.SYNOPSIS
  Stop the LabelGuard-managed CVAT stack only.

.DESCRIPTION
  Runs "docker compose -p labelguard-cvat stop". Containers and volumes are
  kept, so CVAT data survives. Other Docker projects are not affected.
  Nothing is deleted.
#>
param([string]$CvatDir = (Join-Path $env:USERPROFILE "labelguard-cvat"))
$ErrorActionPreference = "Stop"
if (-not (Test-Path $CvatDir)) { Write-Error "No CVAT checkout at $CvatDir" }
Push-Location $CvatDir
try { docker compose -p labelguard-cvat stop } finally { Pop-Location }
