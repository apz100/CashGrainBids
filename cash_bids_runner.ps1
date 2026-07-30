# Run these in an elevated PowerShell on DERKS-SERVER (or remotely with admin rights)
$taskName = 'cash_bids_runner'
$script   = '\\DERKS-SERVER\Current\Adam\Code\CashGrainBids\run_cash_bids.ps1'
$ps       = (Get-Command powershell.exe).Source

# Remove old task if present
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action   = New-ScheduledTaskAction `
  -Execute $ps `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
  -WorkingDirectory '\\DERKS-SERVER\Current\Adam\Code\CashGrainBids'

$trigger  = New-ScheduledTaskTrigger -Daily -At 06:30
$principal= New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
             -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
             -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
  -Principal $principal -Settings $settings -Force