@echo off
echo === Pizza Tracker Setup ===
echo.

cd /d "%~dp0"

echo [1/3] Installing Python packages...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed. Make sure Python is installed.
    pause
    exit /b 1
)

echo.
echo [2/3] Installing Playwright browsers...
python -m playwright install chromium
if errorlevel 1 (
    echo ERROR: Playwright install failed.
    pause
    exit /b 1
)

echo.
echo [3/3] Running first scrape to test...
python scraper.py

echo.
echo === Setup complete! ===
echo.
echo To open the dashboard: run open_dashboard.bat
echo To scrape now manually: python scraper.py
echo To schedule daily 14:00: run schedule_task.bat (as Administrator)
echo.
pause
