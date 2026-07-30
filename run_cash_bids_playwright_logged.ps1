$ErrorActionPreference = "Stop"

$root   = "\\DERKS-SERVER\Current\Adam\Code\CashGrainBids"
$logDir = "C:\Temp"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$logFile = Join-Path $logDir ("cashbids_" + (Get-Date -Format "yyyy-MM-dd_HHmmss") + ".log")

$py = "$root\.venv\Scripts\python.exe"
$script = "$root\cash_bids_via_playwright_UPDATED.py"

Write-Host "=== RUN CONTEXT ==="
Write-Host "User: $env:USERNAME"
Write-Host "Computer: $env:COMPUTERNAME"
Write-Host "Pwd: $(Get-Location)"
Write-Host "Python: $py"
Write-Host "Script exists: $(Test-Path $script)"
Write-Host "JSON exists: $(Test-Path "\\DERKS-SERVER\Current\Adam\Code\derks-elevator-bids-2c0a610dd373.json")"
Write-Host "==================="

"=== START $(Get-Date) ===" | Out-File -FilePath $logFile -Encoding utf8
"User: $env:USERNAME  Computer: $env:COMPUTERNAME" | Out-File $logFile -Append
"Pwd(before): $(Get-Location)" | Out-File $logFile -Append
"Python: $py" | Out-File $logFile -Append
"Script: $script" | Out-File $logFile -Append

Push-Location $root
try {
    & $py $script 2>&1 | Tee-Object -FilePath $logFile -Append
    $exit = $LASTEXITCODE
    "=== EXITCODE: $exit ===" | Out-File $logFile -Append
    if ($exit -ne 0) { throw "Python exited with code $exit" }
}
catch {
    "=== ERROR ===" | Out-File $logFile -Append
    ($_ | Out-String) | Out-File $logFile -Append
    throw
}
finally {
    Pop-Location
    "=== END $(Get-Date) ===" | Out-File $logFile -Append
}

Write-Host "Log written to: $logFile"

