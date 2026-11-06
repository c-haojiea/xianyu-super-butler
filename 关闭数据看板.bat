@echo off
chcp 65001 >nul
title Xianyu Dashboard - Stop
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8092" ^| findstr "LISTENING"') do (
  taskkill /f /pid %%a >nul 2>&1
  set FOUND=1
)
if "%FOUND%"=="1" (
  echo 数据看板已关闭，端口 8092 已释放
) else (
  echo 数据看板当前没有运行
)
timeout /t 2 >nul
