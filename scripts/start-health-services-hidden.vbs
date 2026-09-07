' Auto-generated launcher for the HealthAssistant scheduled task.
' Project and log paths are resolved from this checkout so the repository can be moved or cloned elsewhere.
Option Explicit
Const TASK_NAME = "HealthAssistant"
Const EXPECT_OUTPUT = 0
Const ASYNC_LAUNCH = 0
Dim shell, fso, projectDir, stateDir, resDir, logDir, logFile, cmd, exitCode, logSize, suspicious, ts, json, outFile, Q
Q = Chr(34)
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
stateDir = projectDir & "\logs"
resDir = stateDir & "\task-results"
logDir = stateDir
If Not fso.FolderExists(stateDir) Then fso.CreateFolder(stateDir)
If Not fso.FolderExists(resDir) Then fso.CreateFolder(resDir)
logFile = logDir & "\HealthAssistant.last.log"
shell.CurrentDirectory = projectDir
cmd = "cmd.exe /c pythonw.exe -m scripts.start_health_services > " & Q & logFile & Q & " 2>&1"
If ASYNC_LAUNCH = 1 Then
    shell.Run cmd, 0, False
    exitCode = 0
Else
    exitCode = shell.Run(cmd, 0, True)
End If

logSize = 0
If fso.FileExists(logFile) Then logSize = fso.GetFile(logFile).Size
suspicious = "false"
If ASYNC_LAUNCH = 0 And exitCode = 0 And EXPECT_OUTPUT = 1 And logSize = 0 Then suspicious = "true"
ts = Year(Now) & "-" & Right("0" & Month(Now), 2) & "-" & Right("0" & Day(Now), 2) & "T" & Right("0" & Hour(Now), 2) & ":" & Right("0" & Minute(Now), 2) & ":" & Right("0" & Second(Now), 2)
json = "{" & Q & "task" & Q & ":" & Q & TASK_NAME & Q & "," & Q & "finished_at" & Q & ":" & Q & ts & Q & "," & Q & "exit_code" & Q & ":" & exitCode & "," & Q & "async_launch" & Q & ":" & LCase(CStr(ASYNC_LAUNCH = 1)) & "," & Q & "console_log" & Q & ":" & Q & Replace(logFile, "\", "\\") & Q & "," & Q & "console_bytes" & Q & ":" & logSize & "," & Q & "suspicious_zero_output" & Q & ":" & suspicious & "}"
Set outFile = fso.CreateTextFile(resDir & "\" & TASK_NAME & ".json", True, False)
outFile.Write json
outFile.Close
If ASYNC_LAUNCH = 1 Then
    WScript.Quit 0
Else
    WScript.Quit exitCode
End If
