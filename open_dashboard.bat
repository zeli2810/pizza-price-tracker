@echo off
cd /d "%~dp0"
echo Starting pizza dashboard server...
start "" python server.py
timeout /t 2 /nobreak >nul
start "" http://localhost:8765/dashboard.html
