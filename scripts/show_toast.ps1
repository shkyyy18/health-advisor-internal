# Show a Windows balloon notification with text read from a UTF-8 file.
# Keep this file ASCII-only: cmd/PowerShell 5.1 parse non-ASCII ps1 as GBK.
param(
    [Parameter(Mandatory = $true)][string]$MessageFile,
    [string]$Title = "Health Assistant"
)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$text = [System.IO.File]::ReadAllText($MessageFile, [System.Text.Encoding]::UTF8)
$ni = New-Object System.Windows.Forms.NotifyIcon
$ni.Icon = [System.Drawing.SystemIcons]::Information
$ni.Visible = $true
$ni.BalloonTipTitle = $Title
$ni.BalloonTipText = $text
$ni.ShowBalloonTip(8000)
Start-Sleep -Seconds 9
$ni.Dispose()
