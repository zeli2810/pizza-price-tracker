@echo off
cd /d "%~dp0"

rem Start the local server only if it isn't already listening on 8765
netstat -ano | findstr /r /c:":8765 .*LISTENING" >nul 2>&1
if errorlevel 1 (
    echo Starting pizza dashboard server...
    start "pizza-server" /min python server.py
    timeout /t 2 /nobreak >nul
)

start "" http://localhost:8765/paisplus_dashboard.html
