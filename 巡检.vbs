Dim WshShell
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d D:\software\2026_08_18_After\xianyu-super-butler-main && E:\Cyuyan\Python\Python3.12\python.exe pending_rescue.py 1>nul 2>>logs\rescue.err", 0, True
