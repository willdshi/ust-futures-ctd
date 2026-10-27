# Register a Windows scheduled task that stores the previous day's SOFR every weekday morning.
#
#   powershell -ExecutionPolicy Bypass -File scripts\register_morning_sofr.ps1 [-At 10:00]
#
# Runs scripts\morning_sofr.py (see its docstring): the NY Fed rates under today's as-of date, after the
# morning publication, so a run for the previous day needn't wait for the evening fetch (design section 10,
# phase 1b B7). A non-zero exit code means the fixing wasn't published yet or the fetch failed; the evening
# fetch then stores the file as before. Output is appended to data\fetch.log.
# Remove with: Unregister-ScheduledTask -TaskName ctd-morning-sofr
param(
    [string]$At = "10:00"
)

$repo = Split-Path -Parent $PSScriptRoot
$py = "$env:USERPROFILE\miniconda3\envs\ctd\python.exe"
$cmd = "& '$py' '$repo\scripts\morning_sofr.py' *>> '$repo\data\fetch.log'; exit `$LASTEXITCODE"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -Command `"$cmd`"" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName "ctd-morning-sofr" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Previous day's SOFR for the CTD model (design section 10, phase 1b B7)" -Force
