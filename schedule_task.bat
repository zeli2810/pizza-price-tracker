@echo off
:: Run as Administrator to create Windows Scheduled Task
echo === Creating Scheduled Task: Pizza Price Scraper ===
echo Requires Administrator privileges.
echo.

cd /d "%~dp0"
set SCRIPT_PATH=%~dp0scraper.py
set PYTHON_PATH=

:: Find python executable
for /f "delims=" %%i in ('where python 2^>nul') do (
    set PYTHON_PATH=%%i
    goto :found_python
)
echo ERROR: Python not found in PATH.
pause
exit /b 1

:found_python
echo Python: %PYTHON_PATH%
echo Script: %SCRIPT_PATH%
echo Schedule: Daily at 14:00
echo.

schtasks /create /tn "PizzaPriceScraper" ^
  /tr "\"%PYTHON_PATH%\" \"%SCRIPT_PATH%\"" ^
  /sc daily ^
  /st 14:00 ^
  /ru "%USERNAME%" ^
  /f

if errorlevel 1 (
    echo ERROR: Failed to create task. Try running as Administrator.
    pause
    exit /b 1
)

echo.
echo Task created successfully!
echo View in Task Scheduler under: Task Scheduler Library > PizzaPriceScraper
echo.
echo To run manually now:
echo   schtasks /run /tn "PizzaPriceScraper"
echo.
pause
