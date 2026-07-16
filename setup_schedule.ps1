# =====================================================================
#  Registers a ROBUST daily 17:00 scheduled task for the pizza tracker,
#  designed to NEVER be delayed or silently skipped:
#    - fires at exactly 17:00 (Task Scheduler is punctual, unlike GitHub)
#    - WakeToRun: wakes the PC from sleep to run
#    - StartWhenAvailable: if the PC was off at 17:00, runs ASAP once it's on
#    - runs on battery too
#    - runs whether you're logged in or not
#    - retries up to 3 times (5 min apart) if a run fails
#
#  HOW TO RUN (once):
#    1. Right-click PowerShell -> "Run as administrator"
#    2. cd to this project folder
#    3. Run:   powershell -ExecutionPolicy Bypass -File .\setup_schedule.ps1
# =====================================================================

$ErrorActionPreference = "Stop"
$bat = Join-Path $PSScriptRoot "run_daily.bat"
if (-not (Test-Path $bat)) { throw "run_daily.bat not found next to this script." }

$action  = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At 17:00

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

# S4U = run whether the user is logged on or not (no stored password); Highest = admin.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest

Register-ScheduledTask -TaskName "PizzaTracker" `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

Write-Host ""
Write-Host "OK - 'PizzaTracker' scheduled daily at 17:00." -ForegroundColor Green
Write-Host "It will wake the PC, run if a start was missed, work on battery, and retry on failure."
Write-Host ""
Write-Host "Check it:   schtasks /query /tn PizzaTracker /v /fo LIST"
Write-Host "Run now:    schtasks /run /tn PizzaTracker"
