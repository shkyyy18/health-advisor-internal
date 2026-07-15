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
        Write-Output '健康助手和 ngrok 已检查并启动。'
    }
} finally {
    Pop-Location
}
