param(
    [switch]$Uninstall,
    [string]$TaskName = 'HealthAssistantPostWorkoutRelax'
)

$ErrorActionPreference = 'Stop'
$project = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$script = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'post_workout_recovery.py'))
if (-not $script.StartsWith($project, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The recovery script must be inside the health-assistant project.'
}
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
    throw "Recovery script not found: $script"
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Uninstall) {
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "Removed scheduled task: $TaskName"
    } else {
        Write-Output "Scheduled task is not installed: $TaskName"
    }
    exit 0
}

$pythonw = 'C:\Python314\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    $pythonw = (Get-Command pythonw -ErrorAction Stop).Source
}
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$script`"" -WorkingDirectory $project
# Runs after the 21:40 daily sync so today's Strava activities are already in the DB.
$trigger = New-ScheduledTaskTrigger -Daily -At '21:55'
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description 'Post-workout recovery reminder: if Strava shows an activity today, writes a Hypervolt recovery guide to output/recovery/ and pops a Windows notification pointing at the guided routine page. Silent on rest days. Logs to logs/post_workout_recovery.log.' `
    -Action $action `
    -Trigger @($trigger) `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Output "Installed scheduled task: $TaskName"
Write-Output "Recovery script: $script"
Write-Output "Schedule: daily 21:55 (after the 21:40 daily sync; StartWhenAvailable catches up missed runs)"
