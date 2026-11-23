# Level 1 checks: lint + unit/UI tests. Real-data tests run too when data/bdd100k/smoke exists.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
.\.venv\Scripts\ruff.exe check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
.\.venv\Scripts\python.exe -m pytest
exit $LASTEXITCODE
