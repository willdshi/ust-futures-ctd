# Register the three weekday-morning scheduled tasks (design section 10, phase 1b B7 and phase 1e item 5):
#
#   ctd-morning-sofr       09:15  scripts\morning_sofr.py: the previous business day's SOFR
#   ctd-morning-databento  09:15  ctd fetch --catch-up --source databento_daily: the previous business day's
#                                 CME futures and options, queryable from 09:00 Eastern (and any of the 4 days
#                                 before it still missing)
#   ctd-morning-derive     09:30  scripts\morning_derive.ps1: ctd derive --notify, once both have finished
#
#   powershell -ExecutionPolicy Bypass -File scripts\register_morning_tasks.ps1
#
# Times are local (Eastern). Collection output is appended to data\fetch.log, derive's to data\derive.log.
# A non-zero exit code means a gap (see data\gaps.log and `ctd check`) or a failed build.
# Remove with: Unregister-ScheduledTask -TaskName ctd-morning-sofr, ctd-morning-databento, ctd-morning-derive
param(
    [string]$CollectAt = "09:15",
    [string]$DeriveAt = "09:30"
)

$repo = Split-Path -Parent $PSScriptRoot
$py = "$env:USERPROFILE\miniconda3\envs\ctd\python.exe"
$fetchLog = "$repo\data\fetch.log"
$days = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"

function Register-Morning([string]$Name, [string]$At, [string]$Command, [string]$Description) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command `"$Command`"" -WorkingDirectory $repo
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $At
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings `
        -Description $Description -Force | Out-Null
    "$Name at $At"
}

Register-Morning "ctd-morning-sofr" $CollectAt `
    "& '$py' '$repo\scripts\morning_sofr.py' *>> '$fetchLog'; exit `$LASTEXITCODE" `
    "Previous day's SOFR for the CTD model (design section 10, phase 1b B7)"
Register-Morning "ctd-morning-databento" $CollectAt `
    "& '$py' -m ctd.cli fetch --catch-up --source databento_daily *>> '$fetchLog'; exit `$LASTEXITCODE" `
    "Previous day's CME futures and options from Databento (design section 10, phase 1e)"
Register-Morning "ctd-morning-derive" $DeriveAt `
    "& '$repo\scripts\morning_derive.ps1' *>> '$repo\data\derive.log'; exit `$LASTEXITCODE" `
    "ctd derive once the morning collection has finished (design section 10, phase 1e item 5)"
