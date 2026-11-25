[CmdletBinding()]
param(
    [switch]$SkipXiaomi,
    [switch]$SkipStrava,
    [switch]$ResetXiaomiLogin
)
$ErrorActionPreference = 'Stop'
if ($SkipXiaomi -and $ResetXiaomiLogin) { throw 'Cannot reset Xiaomi while skipping Xiaomi.' }
$Project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Project
$python = Join-Path $Project '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "找不到虚拟环境 Python：$python" }
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }

function Set-EnvValue([string]$Name, [string]$Value) {
    $lines = @(Get-Content -LiteralPath '.env' -Encoding UTF8)
    $found = $false
    $escaped = [regex]::Escape($Name)
    for ($i=0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^$escaped=") { $lines[$i] = "$Name=$Value"; $found = $true }
    }
    if (-not $found) { $lines += "$Name=$Value" }
    Set-Content -LiteralPath '.env' -Value $lines -Encoding UTF8
}

if (-not $SkipStrava) {
    Write-Host '正在打开 Strava API 应用设置页面。请查看或创建应用，并复制 Client ID / Client Secret。' -ForegroundColor Yellow
    $stravaApiUrl = ('https' + '://www.strava.com/settings/api')
    Start-Process $stravaApiUrl
    Write-Host ('Strava API 设置网址：' + $stravaApiUrl) -ForegroundColor Cyan
    Write-Host '授权回调域名请填写：127.0.0.1' -ForegroundColor Cyan
    $envText = Get-Content '.env' -Raw
    $clientId = [regex]::Match($envText, '(?m)^STRAVA_CLIENT_ID=(.*)$').Groups[1].Value.Trim()
    $clientSecret = [regex]::Match($envText, '(?m)^STRAVA_CLIENT_SECRET=(.*)$').Groups[1].Value.Trim()
    if ([string]::IsNullOrWhiteSpace($clientId)) { $clientId = Read-Host '请输入 Strava Client ID（只需首次输入）' }
    if ([string]::IsNullOrWhiteSpace($clientSecret)) { $clientSecret = Read-Host '请输入 Strava Client Secret（只需首次输入）' }
    if ([string]::IsNullOrWhiteSpace($clientId) -or [string]::IsNullOrWhiteSpace($clientSecret)) { throw 'Strava Client ID/Secret 不能为空。' }
    Set-EnvValue 'STRAVA_CLIENT_ID' $clientId
    Set-EnvValue 'STRAVA_CLIENT_SECRET' $clientSecret
}

# Restart only this project's uvicorn process so newly written .env is loaded.
$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*health-advisor-internal*uvicorn*" }
foreach ($p in $procs) { Stop-Process -Id ([int]$p.ProcessId) -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500
Start-Process -FilePath "$env:WINDIR\System32\wscript.exe" -ArgumentList "`"$Project\scripts\start-health-services-hidden.vbs`"" -WindowStyle Hidden
for ($i=0; $i -lt 30; $i++) {
    try { Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/health' -TimeoutSec 1 | Out-Null; break } catch { Start-Sleep -Seconds 1 }
}
if (-not $SkipXiaomi) {
    & $python -c "import importlib.util,sys; sys.exit(0 if all(importlib.util.find_spec(n) for n in ('mijiaAPI','qrcode')) else 1)"
    if ($LASTEXITCODE -ne 0) {
        Write-Host '正在安装小米登录组件，请稍候……' -ForegroundColor Yellow
        & $python -m pip install -e '.[xiaomi]'
        if ($LASTEXITCODE -ne 0) { throw '小米登录组件安装失败，请检查网络后重试。' }
    }
    & $python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('mi_fitness_mcp') else 1)"
    if ($LASTEXITCODE -ne 0) {
        $bridge = Join-Path (Split-Path -Parent $Project) 'mi_fitness_data_bridge'
        if (-not (Test-Path -LiteralPath (Join-Path $bridge 'pyproject.toml'))) {
            throw 'Missing mi_fitness_data_bridge: clone it alongside this project as described in README.'
        }
        & $python -m pip install -e $bridge
        if ($LASTEXITCODE -ne 0) { throw 'Health data connector installation failed.' }
    }
    & $python -c "import mijiaAPI,qrcode; from app.xiaomi_sync import _adapter_class; _adapter_class()"
    if ($LASTEXITCODE -ne 0) { throw 'Xiaomi dependency check failed.' }
    $auth = Join-Path $Project 'data\.mijia\auth.json' 
    $loginArgs = @('scripts\mijia_health_sync.py', 'login')
    if ($ResetXiaomiLogin) { $loginArgs += '--reset-login' }
    & $python @loginArgs
    if ($LASTEXITCODE -ne 0) { throw 'Xiaomi login failed. Sync was not started.' }
    Write-Host 'Xiaomi login succeeded. Syncing through the local service...'
    Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/sync/xiaomi' -TimeoutSec 600 | Out-Null
    Write-Host 'Xiaomi sync request succeeded. Check the recorded sync result.'

}
if (-not $SkipStrava) {
    Start-Process 'http://127.0.0.1:8000/connect/strava'
    Write-Host '已打开 Strava 授权页面；授权完成后返回健康顾问对话。' -ForegroundColor Green
}
Write-Host '初始化完成。日常同步由健康顾问定时任务执行。' -ForegroundColor Cyan
