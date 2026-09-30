# Register TRUSTCAST jobs in Windows Task Scheduler (current user, runs while logged on).
# Re-run to update; remove with scripts\ops\unregister_tasks.ps1. Times are local (IST).
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$runner = Join-Path $repo "scripts\ops\run_job.cmd"
$path = "\TRUSTCAST\"

function Register-Job($name, $triggers, $limitHours) {
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$runner`" $name" -WorkingDirectory $repo
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours $limitHours)
    Register-ScheduledTask -TaskName $name -TaskPath $path -Action $action -Trigger $triggers `
        -Settings $settings -Description "TRUSTCAST $name (decision-support prototype)" -Force | Out-Null
    Write-Output "registered $path$name"
}

$archive = @("03:00", "09:00", "15:00", "21:00") | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
Register-Job "archive" $archive 2
Register-Job "backfill_prev" (New-ScheduledTaskTrigger -Daily -At "05:45") 20
Register-Job "backfill_dyn" (New-ScheduledTaskTrigger -Daily -At "06:00") 23
Register-Job "backfill_gefs" (New-ScheduledTaskTrigger -Daily -At "06:05") 23
Register-Job "truth" (New-ScheduledTaskTrigger -Daily -At "12:00") 3
if (Test-Path (Join-Path $repo "scripts\run_forecast.py")) {
    Register-Job "forecast" (New-ScheduledTaskTrigger -Daily -At "14:30") 3
}
