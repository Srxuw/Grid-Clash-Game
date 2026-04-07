@echo off
title Grid Clash Protocol - Baseline Test
echo ==========================================
echo Starting Grid Clash Protocol (DOMX v1)
echo ==========================================

REM Navigate to project directory
cd "C:\Users\Aser\Desktop\Drive\ASU\5th Term FALL 2025\CSE361 - Computer Networking\Grid Clash Protocol\My Try"

REM Start the server
start "Server" python server.py
timeout /t 2 >nul

REM Start four clients
start "Client 1" python client.py
timeout /t 1 >nul
start "Client 2" python client.py
timeout /t 1 >nul
start "Client 3" python client.py
timeout /t 1 >nul
start "Client 4" python client.py

echo ==========================================
echo Baseline setup complete.
echo Server + 4 clients are now running.
echo ==========================================
pause
