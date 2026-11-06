@echo off
chcp 65001 >nul
title Xianyu Dashboard - Stop
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c=Get-NetTCPConnection -LocalPort 8092 -State Listen -ErrorAction SilentlyContinue; if($c){ $c.OwningProcess | Select-Object -Unique | ForEach-Object { Stop-Process -Id $_ -Force }; Write-Host '数据看板已关闭（8092 已释放）' } else { Write-Host '数据看板当前没有运行' }; Start-Sleep -Seconds 2"
