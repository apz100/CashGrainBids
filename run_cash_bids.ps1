# \\DERKS-SERVER\Current\Adam\Code\CashGrainBids\run_cash_bids.ps1
$ErrorActionPreference = 'Stop'

# UNC root we use from workstations:
$uncRoot = '\\DERKS-SERVER\Current\Adam\Code\CashGrainBids'

function Use-LocalPathIfServer($unc) {
  if ($env:COMPUTERNAME -ieq 'DERKS-SERVER') {
    $m = [regex]::Match($unc, '^(\\\\DERKS-SERVER)\\([^\\]+)\\(.*)$')
    if ($m.Success) {
      $share = $m.Groups[2].Value   # e.g. 'Current'
      $rest  = $m.Groups[3].Value   # e.g. 'Adam\Code\CashGrainBids'
      try {
        $shareObj = Get-SmbShare -Name $share -ErrorAction Stop
        return Join-Path $shareObj.Path $rest
      } catch { }
    }
  }
  return $unc
}

$root   = Use-LocalPathIfServer $uncRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$script = Join-Path $root 'cash_bids_via_playwright.py'
$logs   = Join-Path $root 'logs'

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
