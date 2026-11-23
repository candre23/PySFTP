Option Explicit
Dim shell, files, directory, pythonExe, script
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
directory = files.GetParentFolderName(WScript.ScriptFullName)
pythonExe = directory & "\.venv\Scripts\pythonw.exe"
script = directory & "\main.py"
If Not files.FileExists(pythonExe) Then
    MsgBox "Run setup.bat before launching PySFTP.", vbExclamation, "PySFTP"
    WScript.Quit 1
End If
If Not files.FileExists(directory & "\rclone\rclone.exe") Then
    MsgBox "Missing rclone\rclone.exe", vbExclamation, "PySFTP"
    WScript.Quit 1
End If
shell.CurrentDirectory = directory
shell.Run Chr(34) & pythonExe & Chr(34) & " " & Chr(34) & script & Chr(34), 0, False
