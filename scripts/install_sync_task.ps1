param(
    [switch]$Uninstall,
    [string]$TaskName = 'HealthAssistantDailySync'
)

$ErrorActionPreference = 'Stop'
$project = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$syncScript = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'daily_sync.py'))
if (-not $syncScript.StartsWith($project, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The sync script must be inside the health-assistant project.'
}
if (-not (Test-Path -LiteralPath $syncScript -PathType Leaf)) {
    throw "Sync script not found: $syncScript"
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

$python = 'C:\Python314\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $python -Argument "`"$syncScript`"" -WorkingDirectory $project
# Morning run picks up last night's sleep and the morning weigh-in;
# evening run picks up daytime activities and steps.
$triggerMorning = New-ScheduledTaskTrigger -Daily -At '08:10'
$triggerEvening = New-ScheduledTaskTrigger -Daily -At '21:40'
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description 'Daily automatic sync for the local health assistant: pulls Xiaomi Mi Fitness (sleep, body composition, daily metrics) and Strava activities via the local service endpoints. Logs to logs/daily_sync.log.' `
    -Action $action `
    -Trigger @($triggerMorning, $triggerEvening) `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Output "Installed scheduled task: $TaskName"
Write-Output "Sync script: $syncScript"
Write-Output "Schedule: daily 08:10 and 21:40 (StartWhenAvailable catches up missed runs)"
