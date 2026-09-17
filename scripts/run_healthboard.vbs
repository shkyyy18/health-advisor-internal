' Launches scripts\healthboard.bat fully hidden (no console window).
' The healthboard:// protocol points here.
Dim shell, fso, projectDir, batchFile
Set shell = CreateObject("Wscript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
batchFile = projectDir & "\scripts\healthboard.bat"
shell.CurrentDirectory = projectDir
shell.Run "cmd /c """ & batchFile & """", 0, False
