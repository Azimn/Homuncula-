$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path ".venv")) {
    py -3.11 -m venv .venv
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -e ".[dev]"

$env:HOMUNCULA_PYTHON = $Python
$env:HOMUNCULA_ROOT = $Root

Set-Location (Join-Path $Root "desktop")
if (-not (Test-Path "node_modules")) {
    npm install
}

npm run dev
