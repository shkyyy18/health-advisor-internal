function Test-LocalPort([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        return $task.Wait(750) -and $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Get-ListeningPid([int]$Port) {
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($connection) { return $connection.OwningProcess }

    $pattern = '^\s*TCP\s+\S+:' + $Port + '\s+\S+\s+LISTENING\s+(\d+)\s*$'
    foreach ($line in (netstat -ano -p tcp)) {
        $match = [regex]::Match($line, $pattern)
        if ($match.Success) { return [int]$match.Groups[1].Value }
    }
    return $null
}

$appRunning = Test-LocalPort 8000
$ngrokRunning = Test-LocalPort 4040
$appPid = if ($appRunning) { Get-ListeningPid 8000 } else { $null }
$ngrokPid = if ($ngrokRunning) { Get-ListeningPid 4040 } else { $null }

[PSCustomObject]@{
    HealthAssistant = if ($appRunning) { "运行中 (PID $appPid)" } else { '未运行' }
    Ngrok = if ($ngrokRunning) { "运行中 (PID $ngrokPid)" } else { '未运行' }
    LocalDashboard = 'http://127.0.0.1:8000'
} | Format-List

if ($ngrokRunning) {
    try {
        (Invoke-RestMethod 'http://127.0.0.1:4040/api/tunnels').tunnels |
            Select-Object public_url, proto | Format-Table -AutoSize
    } catch {}
}
