$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Get-Command py.exe -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python.exe -ErrorAction SilentlyContinue }
if (-not $python) {
  throw "Python 3 is not installed. Install it from https://www.python.org/downloads/windows/ and enable 'Add python.exe to PATH', then run this script again."
}

$pythonExe = $python.Source
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
  & $pythonExe -m venv (Join-Path $root '.venv')
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $root 'requirements.txt')
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $root 'pw-browsers'
& $venvPython -m playwright install chromium

Write-Host "Setup complete. Test with .\run_cash_bids.ps1"
