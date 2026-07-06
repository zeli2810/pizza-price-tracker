@echo off
:: Creates a Windows Scheduled Task that runs dominos_scraper.py every day at 14:00.
:: Run this file as Administrator (right-click > Run as administrator).
echo === Domino's Price Tracker — Daily 14:00 ===
echo.

cd /d "%~dp0"
set SCRIPT_PATH=%~dp0dominos_scraper.py
set PYTHON_PATH=

for /f "delims=" %%i in ('where python 2^>nul') do (
    set PYTHON_PATH=%%i
    goto :found
)
echo ERROR: Python not found in PATH.
pause & exit /b 1

:found
echo Python : %PYTHON_PATH%
echo Script : %SCRIPT_PATH%
echo Schedule: every day at 14:00
echo.

schtasks /create /tn "DominosPriceTracker" ^
  /tr "\"%PYTHON_PATH%\" \"%SCRIPT_PATH%\"" ^
  /sc daily ^
  /st 14:00 ^
  /ru "%USERNAME%" ^
  /f

if errorlevel 1 (
    echo ERROR: Failed to create task. Run this file as Administrator.
    pause & exit /b 1
)

echo.
echo Task created! It will run every day at 14:00.
echo.
echo To run it right now (test):
echo   schtasks /run /tn "DominosPriceTracker"
echo.
echo To view/edit:  Task Scheduler ^> Task Scheduler Library ^> DominosPriceTracker
echo To delete:     schtasks /delete /tn "DominosPriceTracker" /f
echo.
pause
