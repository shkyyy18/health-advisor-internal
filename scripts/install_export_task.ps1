param(
    [switch]$Uninstall,
    [string]$TaskName = 'HealthAssistantCloudDigestExport'
)

$ErrorActionPreference = 'Stop'
$project = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$exportScript = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'export_cloud_digest.py'))
if (-not $exportScript.StartsWith($project, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The export script must be inside the health-assistant project.'
}
if (-not (Test-Path -LiteralPath $exportScript -PathType Leaf)) {
    throw "Export script not found: $exportScript"
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

# pythonw.exe keeps the run hidden (no console window), per workspace rule.
$python = 'C:\Python314\pythonw.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = (Get-Command pythonw -ErrorAction Stop).Source
}
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $python -Argument "`"$exportScript`"" -WorkingDirectory $project
# Weekly refresh: Sunday evening, so the digest is fresh before the new week.
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '21:05'
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description 'Weekly export of the health-data digest (Desktop/健康顾问-云端复刻/健康数据摘要.md) for manual upload to the cloud Kimi health advisor. Runs hidden via pythonw.' `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Output "Installed scheduled task: $TaskName"
Write-Output "Export script: $exportScript"
Write-Output "Schedule: weekly Sunday 21:05 (StartWhenAvailable catches up missed runs)"
