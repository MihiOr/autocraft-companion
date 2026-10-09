Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
python = folder & "\.venv\Scripts\pythonw.exe"
If fso.FileExists(python) Then
    shell.Run """" & python & """ """ & folder & "\src\app.py""", 0, False
Else
    shell.Run "pyw -3 """ & folder & "\src\app.py""", 0, False
End If
