@echo off
chcp 65001 >nul
title 数据看板 - 关闭此窗口即停止服务
cd /d "%~dp0dashboard"
echo ==========================================================
echo   小店经营看板    http://localhost:8092
echo   关闭这个黑色窗口 = 停止服务
echo ==========================================================
E:\Cyuyan\Python\Python3.12\python.exe server.py --open
echo.
echo 服务已停止（若是启动失败，请查看上方提示）
pause
