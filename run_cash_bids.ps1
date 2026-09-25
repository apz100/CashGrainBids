$ErrorActionPreference = 'Stop'

$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$script = Join-Path $root 'cash_bids_via_playwright_UPDATED.py'
$logs   = Join-Path $root 'logs'

if (-not (Test-Path -LiteralPath $python)) {
  throw "Virtual environment not found at $python. Run setup_new_computer.ps1 first."
}

# Keep Playwright browsers under the project (works for any account)
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $root 'pw-browsers'

New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd_HHmm'
$log   = Join-Path $logs "run_$stamp.log"

Write-Host "Running $script with $python..."
Write-Host "PY: $python"
Write-Host "ROOT: $root"
Write-Host "PLAYWRIGHT_BROWSERS_PATH: $env:PLAYWRIGHT_BROWSERS_PATH"

# call python, capture output to log but don’t crash the host
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $python $script *>> $log 2>&1
$code = $LASTEXITCODE
$ErrorActionPreference = $prevEAP

Write-Host "Done. ExitCode=$code  Log: $log"
Get-Content -Tail 80 $log
if ($code -ne 0) { exit $code }
