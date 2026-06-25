@echo off
title 百约 BaiYue
set PYTHON=C:\Users\31549\AppData\Local\Programs\Python\Python312\python.exe
set BOT=d:\skill\baiyue\bot.py

echo ========================================
echo   BaiYue v1.0
echo ========================================
echo.

echo [1/2] Check NapCat...
powershell -Command "try {$r=Invoke-RestMethod 'http://127.0.0.1:3000/get_status' -TimeoutSec 5; if($r.data.online){Write-Host 'OK - QQ Online'}else{Write-Host 'WARN - QQ Offline'}}" 2>nul
if errorlevel 1 (
    echo [ERROR] NapCat not running!
    pause
    exit /b 1
)
echo.

echo [2/2] Start BaiYue...
echo.
%PYTHON% -u %BOT%
pause
