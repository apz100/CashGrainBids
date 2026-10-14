$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
  throw "Virtual environment not found at $python. Run setup_new_computer.ps1 first."
}
& $python (Join-Path $root 'inspect_broadgrain_email.py')
