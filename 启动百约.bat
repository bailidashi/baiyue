@echo off
chcp 65001 >nul
title 百约 BaiYue

echo ========================================
echo   百约 · BaiYue
echo ========================================
echo.

echo [检查] NapCat...
powershell -Command "try {$r=Invoke-RestMethod 'http://127.0.0.1:3000/get_status' -TimeoutSec 5; if($r.data.online){Write-Host 'OK'}else{Write-Host 'QQ未登录'}}" 2>nul
if errorlevel 1 (
    echo [错误] NapCat 没启动！请先启动 NapCatQQ
    pause
    exit /b 1
)
echo.

echo [启动] 百约...
echo.
python -u bot.py
pause
