# Start the LabelGuard web app on http://localhost:8501 (localhost only).
param([int]$Port = 8501)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path ".venv\Scripts\python.exe")) { & "$PSScriptRoot\setup.ps1" }
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port $Port --server.headless false
