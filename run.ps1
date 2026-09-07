param([switch]$Reload)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
    Write-Host '已创建 .env，请先填写 STRAVA_CLIENT_ID、STRAVA_CLIENT_SECRET 和 APP_SECRET。' -ForegroundColor Yellow
    exit 1
}

$argsList = @('app.main:app', '--host', '0.0.0.0', '--port', '8000')
if ($Reload) { $argsList += '--reload' }
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}
& $python -m uvicorn @argsList
exit $LASTEXITCODE
