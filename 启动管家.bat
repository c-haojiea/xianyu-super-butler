@echo off
chcp 65001 >nul
title 闲鱼超级管家 v3.2.0 (端口8081)
cd /d "D:\software\2026_08_18_After\xianyu-super-butler-main"
echo 正在启动闲鱼超级管家（新版 v3.2.0，端口 8081）...
start "" http://localhost:8081
"E:\Cyuyan\Python\Python3.12\python.exe" Start.py
pause
