$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
  throw "Virtual environment not found at $python. Run setup_new_computer.ps1 first."
}
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $root 'pw-browsers'
& $python (Join-Path $root 'setup_ingredion_login.py')
