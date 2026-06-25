@echo off
chcp 65001 >nul
title 百约 BaiYue
set PYTHON=C:\Users\31549\AppData\Local\Programs\Python\Python312\python.exe

echo ========================================
echo   百约 · BaiYue
echo   "我是 AI，但我懂你"
echo ========================================
echo.

:: 先杀掉旧的百约进程（避免端口冲突）
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001.*LISTENING"') do (
    echo [清理] 关闭旧的百约进程 PID=%%a
    taskkill /PID %%a /F >nul 2>&1
)
echo.

:: 检查 NapCat
echo [1/2] 检查 NapCat...
powershell -Command "try {$r=Invoke-RestMethod 'http://127.0.0.1:3000/get_status' -TimeoutSec 5; if($r.data.online){Write-Host '[OK] NapCat在线'}else{Write-Host '[警告] QQ未登录'}}" 2>nul
if errorlevel 1 (
    echo [错误] NapCat 没启动！请先启动 NapCatQQ
    echo.
    pause
    exit /b 1
)
echo.

:: 启动百约
echo [2/2] 百约启动中...
echo.
"%PYTHON%" -u "d:\skill\baiyue\bot.py"

echo.
echo 百约已退出。
pause
