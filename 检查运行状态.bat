@echo off
chcp 65001 >nul
title Xianyu Butler Status Check
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check_status.ps1"
pause
