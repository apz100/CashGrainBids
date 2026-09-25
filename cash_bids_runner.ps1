# Register this from a normal PowerShell. The task runs as the current user.
$taskName = 'cash_bids_runner'
$script   = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'run_cash_bids.ps1'
$ps       = (Get-Command powershell.exe).Source

# Remove old task if present
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action   = New-ScheduledTaskAction `
  -Execute $ps `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
  -WorkingDirectory (Split-Path -Parent $script)

$trigger  = New-ScheduledTaskTrigger -Daily -At 06:30
$userId   = "$env:USERDOMAIN\$env:USERNAME"
$principal= New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
             -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
             -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
  -Principal $principal -Settings $settings -Force
