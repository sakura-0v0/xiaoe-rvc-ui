' Launch launcher.py via pythonw (no console window, errors shown as dialogs).
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws = CreateObject("WScript.Shell")
script_dir = fso.GetParentFolderName(WScript.ScriptFullName)
rvc_root = fso.GetParentFolderName(script_dir)
pyw = rvc_root & "\runtime\pythonw.exe"

If Not fso.FileExists(pyw) Then
    MsgBox "RVC runtime not found: " & pyw & vbCrLf & _
           "Please download and extract the original RVC first, then place this folder into its root directory." & vbCrLf & _
           "RVC: https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI", _
           16, "xiaoe_rvc_ui"
    WScript.Quit
End If

ws.Run """" & pyw & """ -I """ & script_dir & "\launcher.py""", 0, False
