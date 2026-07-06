"""
FastAPI web app for the pizza price dashboard.
  GET  /            -> dashboard.html
  GET  /data         -> current history (data/all_prices.json, pulled from blob if configured)
  POST /run-scrape    -> runs multi_scraper.py as a subprocess, streams stdout as text/plain

Also runs an in-process APScheduler job that fires the same scrape once a day
at 14:00 Asia/Jerusalem, skipping if today's row already exists (e.g. someone
already hit "refresh" manually today).

Run locally:   uvicorn app:app --host 0.0.0.0 --port 8000
"""

import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import multi_scraper

DIR = Path(__file__).parent
SCRAPER_SCRIPT = DIR / "multi_scraper.py"

app = FastAPI()


def _run_scraper_lines():
    """Run multi_scraper.py as a subprocess, yielding stdout lines as they arrive."""
    proc = subprocess.Popen(
        [sys.executable, str(SCRAPER_SCRIPT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(DIR),
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in proc.stdout:
        yield line
    proc.wait()
    yield f"\n__DONE__{'OK' if proc.returncode == 0 else f'ERROR (exit {proc.returncode})'}__\n"


@app.get("/")
def dashboard():
    return FileResponse(DIR / "dashboard.html")


@app.get("/data")
def data():
    return JSONResponse(multi_scraper.load_history())


@app.post("/run-scrape")
def run_scrape():
    return StreamingResponse(_run_scraper_lines(), media_type="text/plain; charset=utf-8")


def _scheduled_scrape():
    today = datetime.now().strftime("%Y-%m-%d")
    history = multi_scraper.load_history()
    if any(h.get("date") == today for h in history):
        print(f"[scheduler] {today} already scraped, skipping")
        return
    print(f"[scheduler] running daily 14:00 scrape for {today}")
    subprocess.run([sys.executable, str(SCRAPER_SCRIPT)], cwd=str(DIR))


scheduler = BackgroundScheduler(timezone="Asia/Jerusalem")
scheduler.add_job(_scheduled_scrape, CronTrigger(hour=14, minute=0, timezone="Asia/Jerusalem"))


@app.on_event("startup")
def start_scheduler():
    scheduler.start()
    print("[scheduler] started — daily scrape scheduled for 14:00 Asia/Jerusalem")


@app.on_event("shutdown")
def stop_scheduler():
    scheduler.shutdown(wait=False)
