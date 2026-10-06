$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path ".venv")) {
    py -3.11 -m venv .venv
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -e ".[dev,package]"
& $Python -m pytest -q
& $Python -m ruff check src tests

$Resources = Join-Path $Root "desktop\resources"
New-Item -ItemType Directory -Force -Path $Resources | Out-Null

$PyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name", "agentd",
    "--distpath", $Resources,
    "--workpath", (Join-Path $Root "build\pyinstaller"),
    "--specpath", (Join-Path $Root "build"),
    "--collect-all", "playwright",
    "--collect-all", "pywinauto",
    "--collect-all", "sherpa_onnx",
    (Join-Path $Root "agentd_entry.py")
)
& $Python -m PyInstaller @PyInstallerArgs

Set-Location (Join-Path $Root "desktop")
npm install
npm run typecheck
npm run dist:win
