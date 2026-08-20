' Launches scripts\healthboard.bat fully hidden (no console window).
' The healthboard:// protocol points here.
Set shell = CreateObject("Wscript.Shell")
shell.CurrentDirectory = "D:\AIWorkspace\projects\health-advisor-internal"
shell.Run "cmd /c scripts\healthboard.bat", 0, False
