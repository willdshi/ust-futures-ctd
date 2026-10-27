# Register the four weekday-morning scheduled tasks that collect the previous business day D and derive it
# (design section 10, phase 1b B7 and phase 1e item 5):
#
#   ctd-daily-fetch        09:00  ctd fetch --catch-up --notify --skip-source databento_daily: every daily
#                                 source for D (end-of-day TreasuryDirect prices, never the provisional
#                                 same-evening file) and the 4 business days before it still missing
#   ctd-morning-sofr       09:15  scripts\morning_sofr.py: D's SOFR, published about 08:00
#   ctd-morning-databento  09:15  ctd fetch --catch-up --source databento_daily: D's CME futures and options,
#                                 queryable from 09:00 (and any of the 4 days before still missing)
#   ctd-morning-derive     09:30  scripts\morning_derive.py: ctd derive --notify once D's data is stored
#
#   powershell -ExecutionPolicy Bypass -File scripts\register_morning_tasks.ps1
#
# Times are local (Eastern). Each task appends to its own log in data\, as UTF-8: fetch.log, sofr.log,
# databento.log and derive.log. Two tasks starting together can't append to one file: Windows PowerShell
# can't open a file another process is writing, and the second task's command then never runs (2026-10-27,
# both started at 10:11 after the PC woke). A non-zero exit code means a gap (see data\gaps.log and
# `ctd check`), a failed build, or a derive skipped for missing data (with a desktop alert).
# Remove with: Unregister-ScheduledTask -TaskName ctd-daily-fetch, ctd-morning-sofr, ctd-morning-databento,
#   ctd-morning-derive
param(
    [string]$FetchAt = "09:00",
    [string]$CollectAt = "09:15",
    [string]$DeriveAt = "09:30",
    [switch]$NoNotify
)

$repo = Split-Path -Parent $PSScriptRoot
$py = "$env:USERPROFILE\miniconda3\envs\ctd\python.exe"
$days = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
$notify = if ($NoNotify) { "" } else { " --notify" }

function Register-Morning([string]$Name, [string]$At, [string]$Command, [string]$Log, [string]$Description) {
    $utf8 = "`$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'; "  # >> writes UTF-16 by default
    $run = "$utf8$Command *>> '$repo\data\$Log'; exit `$LASTEXITCODE"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command `"$run`"" -WorkingDirectory $repo
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $At
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings `
        -Description $Description -Force | Out-Null
    "$Name at $At, log data\$Log"
}

Register-Morning "ctd-daily-fetch" $FetchAt `
    "& '$py' -m ctd.cli fetch --catch-up$notify --skip-source databento_daily" "fetch.log" `
    "Previous business day's raw snapshot for the CTD model (design section 3.2)"
Register-Morning "ctd-morning-sofr" $CollectAt "& '$py' '$repo\scripts\morning_sofr.py'" "sofr.log" `
    "Previous business day's SOFR (design section 10, phase 1b B7)"
Register-Morning "ctd-morning-databento" $CollectAt `
    "& '$py' -m ctd.cli fetch --catch-up --source databento_daily" "databento.log" `
    "Previous business day's CME futures and options from Databento (design section 10, phase 1e)"
Register-Morning "ctd-morning-derive" $DeriveAt "& '$py' '$repo\scripts\morning_derive.py'" "derive.log" `
    "ctd derive once the previous business day's data is stored (design section 10, phase 1e item 5)"
