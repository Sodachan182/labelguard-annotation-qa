<#
.SYNOPSIS
  Level 2 (real data) and optional Level 3 (CVAT) tests on a BDD100K subset.

.EXAMPLE
  .\scripts\test-bdd100k.ps1 -Profile smoke -AcceptLicense
  .\scripts\test-bdd100k.ps1 -Profile standard -WithCvat
#>
param(
    [ValidateSet("smoke", "standard", "extended")][string]$Profile = "smoke",
    [switch]$AcceptLicense,
    [switch]$WithCvat
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
Push-Location $root
try {
    if (-not (Test-Path "data\bdd100k\$Profile\labels")) {
        if (-not $AcceptLicense) {
            Write-Error "Subset '$Profile' is not downloaded. Re-run with -AcceptLicense to accept the BDD100K license and fetch it."
        }
        & $py -m labelguard.cli bdd100k fetch --profile $Profile --accept-license
    }
    & $py -m pytest -m realdata -q
    & $py -m labelguard.cli bdd100k benchmark --profile $Profile
    if ($WithCvat) {
        & $py scripts\cvat_bdd100k_e2e.py --profile $Profile
    }
} finally { Pop-Location }
