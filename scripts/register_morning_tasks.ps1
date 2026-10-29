# Register the weekday-morning scheduled task that collects the previous business day D and derives it
# (roadmap 1b.B7 and 1e.5; data.md section 4):
#
#   ctd-morning  09:15  scripts\morning.py, one step after another:
#                         1. ctd fetch --catch-up --notify: every daily source for D (end-of-day TreasuryDirect
#                            prices, never the provisional same-evening file; Databento, queryable from 09:00)
#                            and the 4 business days before it still missing
#                         2. scripts\morning_sofr.py: D's SOFR, published about 08:00
#                         3. scripts\morning_derive.py: ctd derive --notify if D's data is stored, else an alert
#
#   powershell -ExecutionPolicy Bypass -File scripts\register_morning_tasks.ps1
#
# Times are local (Eastern). The task appends to data\morning.log, as UTF-8. Until 2026-10-28 there were four
# tasks (ctd-daily-fetch, ctd-morning-sofr, ctd-morning-databento, ctd-morning-derive, logging to fetch.log,
# sofr.log, databento.log and derive.log); this script removes them. Steps run as separate tasks collided
# when they started together after a missed start (2026-10-27, 2026-10-28). A non-zero exit code means a gap
# (see data\gaps.log and `ctd check`), a failed build, or a derive skipped for missing data (with a desktop
# alert).
# The task wakes the PC to run (-WakeToRun; Windows sets the wake timer 30 seconds early, listed by
# `powercfg /waketimers`) and needs "Allow wake timers" on in the power plan (data.md section 4).
#
# Remove with: Unregister-ScheduledTask -TaskName ctd-morning
param(
    [string]$At = "09:15",
    [switch]$NoNotify
)

$repo = Split-Path -Parent $PSScriptRoot
$py = "$env:USERPROFILE\miniconda3\envs\ctd\python.exe"
$days = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
$notify = if ($NoNotify) { " --no-notify" } else { "" }

foreach ($old in "ctd-daily-fetch", "ctd-morning-sofr", "ctd-morning-databento", "ctd-morning-derive") {
    if (Get-ScheduledTask -TaskName $old -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $old -Confirm:$false
        "removed $old"
    }
}

$utf8 = "`$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'; "  # >> writes UTF-16 by default
$run = "$utf8& '$py' '$repo\scripts\morning.py'$notify *>> '$repo\data\morning.log'; exit `$LASTEXITCODE"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command `"$run`"" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "ctd-morning" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Previous business day's raw snapshot and derived tables for the CTD model (roadmap 1e.5)" `
    -Force | Out-Null
"ctd-morning at $At, log data\morning.log"
