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

# Run twice daily using the computer's local time zone (Eastern on this PC).
$triggers = @(
  (New-ScheduledTaskTrigger -Daily -At 07:30),
  (New-ScheduledTaskTrigger -Daily -At 16:00)
)
$userId   = "$env:USERDOMAIN\$env:USERNAME"
$principal= New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
             -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
             -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers `
  -Principal $principal -Settings $settings -Force
