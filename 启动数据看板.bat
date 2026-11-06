@echo off
chcp 65001 >nul
title Xianyu Dashboard
cd /d "%~dp0dashboard"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$l=Get-NetTCPConnection -LocalPort 8092 -ErrorAction SilentlyContinue | Where-Object State -eq Listen; if(-not $l){ Start-Process -WindowStyle Hidden 'E:\Cyuyan\Python\Python3.12\python.exe' -ArgumentList 'server.py' -WorkingDirectory (Get-Location).Path; Start-Sleep -Milliseconds 900 }; Start-Process 'http://localhost:8092'"
