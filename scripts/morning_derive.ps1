# Run `ctd derive --notify` once this morning's collection tasks have finished (design section 10, phase 1e item 5).
#
#   powershell -ExecutionPolicy Bypass -File scripts\morning_derive.ps1 [-TimeoutMinutes 60]
#
# Run by the scheduled task ctd-morning-derive at 09:30 (scripts\register_morning_tasks.ps1). Waits until each
# task in -WaitFor has started today and is no longer running, so it also waits when all of them start late
# together after the PC wakes; after -TimeoutMinutes it derives anyway and says which task it gave up on.
# Output is appended to data\derive.log by the scheduled task.
param(
    [string[]]$WaitFor = @("ctd-morning-sofr", "ctd-morning-databento"),
    [int]$TimeoutMinutes = 60
)

$repo = Split-Path -Parent $PSScriptRoot
$py = "$env:USERPROFILE\miniconda3\envs\ctd\python.exe"
$today = (Get-Date).Date
$deadline = (Get-Date).AddMinutes($TimeoutMinutes)

"$(Get-Date -Format s) morning derive: waiting for $($WaitFor -join ', ')"
foreach ($name in $WaitFor) {
    while ($true) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if (-not $task) { "$name is not registered; not waiting for it"; break }
        $info = $task | Get-ScheduledTaskInfo
        if ($task.State -ne "Running" -and $info.LastRunTime -ge $today) {
            "$name finished (started $($info.LastRunTime), exit code $($info.LastTaskResult))"
            break
        }
        if ((Get-Date) -gt $deadline) { "$name hasn't finished after $TimeoutMinutes minutes; deriving anyway"; break }
        Start-Sleep -Seconds 30
    }
}

& $py -m ctd.cli derive --notify
"$(Get-Date -Format s) morning derive: exit code $LASTEXITCODE"
exit $LASTEXITCODE
