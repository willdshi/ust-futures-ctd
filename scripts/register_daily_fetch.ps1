# Register a Windows scheduled task that runs `ctd fetch --catch-up` every weekday evening.
#
#   powershell -ExecutionPolicy Bypass -File scripts\register_daily_fetch.ps1 [-At 19:00]
#
# --catch-up also fills gaps in the previous 4 business days (CME's settlement pages show 5).
# A non-zero exit code means gaps; see data\gaps.log and `ctd check`. Output is appended to data\fetch.log.
# --notify shows a Windows notification for gaps on earlier dates that the catch-up couldn't fill (e.g. a
# missed bookmarklet click) and for manual files ingest refused; -NoNotify turns it off.
# Remove with: Unregister-ScheduledTask -TaskName ctd-daily-fetch
param(
    [string]$At = "19:00",
    [switch]$NoNotify
)

$repo = Split-Path -Parent $PSScriptRoot
$py = "$env:USERPROFILE\miniconda3\envs\ctd\python.exe"
$fetchArgs = "-m ctd.cli fetch --catch-up"
if (-not $NoNotify) { $fetchArgs += " --notify" }
$cmd = "& '$py' $fetchArgs *>> '$repo\data\fetch.log'; exit `$LASTEXITCODE"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -Command `"$cmd`"" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName "ctd-daily-fetch" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Daily raw data snapshot for the CTD model (design section 3.2)" -Force
