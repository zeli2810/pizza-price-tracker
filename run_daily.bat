@echo off
REM =====================================================================
REM  Pizza Tracker - daily scrape from THIS (Israeli-IP) machine.
REM  Runs all scrapers and pushes results to Firebase Firestore.
REM  Schedule it once a day (see SETUP_LOCAL.md) - avoid running it
REM  repeatedly, or Wolt may rate-limit and return a partial list.
REM =====================================================================

REM Run from the folder this .bat lives in.
cd /d "%~dp0"

REM ---- EDIT THIS: full path to your Firebase service-account JSON key ----
set "FIREBASE_SERVICE_ACCOUNT_FILE=C:\Users\eli\.pizza\serviceAccount.json"

set "PYTHONIOENCODING=utf-8"
set "LOG=%~dp0run_daily.log"

echo ================================================= >> "%LOG%"
echo [%date% %time%] START daily scrape >> "%LOG%"

echo [%date% %time%] multi_scraper (prices)... >> "%LOG%"
python multi_scraper.py   >> "%LOG%" 2>&1

echo [%date% %time%] branch_scraper (branch counts)... >> "%LOG%"
python branch_scraper.py  >> "%LOG%" 2>&1

echo [%date% %time%] paisplus_scraper... >> "%LOG%"
python paisplus_scraper.py >> "%LOG%" 2>&1

echo [%date% %time%] wolt_scraper... >> "%LOG%"
python wolt_scraper.py    >> "%LOG%" 2>&1

echo [%date% %time%] DONE >> "%LOG%"
