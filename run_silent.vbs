' Orvo Silent Background Launcher
' Launches pythonw.exe with window style 0 (hidden) so no command prompt window appears.

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

strScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
strPythonW = strScriptDir & "\.venv\Scripts\pythonw.exe"
strMainPy = strScriptDir & "\main.py"

If Not fso.FileExists(strPythonW) Then
    MsgBox "Orvo environment not found!" & vbCrLf & _
           "Please run setup_windows.bat first to configure Python and install dependencies.", _
           vbCritical, "Orvo Error"
    WScript.Quit 1
End If

' Run pythonw.exe main.py with window style 0 (completely hidden) without waiting
WshShell.CurrentDirectory = strScriptDir
WshShell.Run """" & strPythonW & """ """ & strMainPy & """", 0, False
