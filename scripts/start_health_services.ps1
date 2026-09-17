param(
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$project = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python = (Get-Command python -ErrorAction Stop).Source
Push-Location $project
try {
    & $python -m scripts.start_health_services
    if ($LASTEXITCODE -ne 0) {
        throw "Health service launcher exited with code $LASTEXITCODE."
    }
    if (-not $Quiet) {
        Write-Output 'Health Assistant checked; ngrok is allowed only with HEALTH_ENABLE_NGROK=true.'
    }
} finally {
    Pop-Location
}
