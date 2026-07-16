#!/usr/bin/env python
"""
Daily runner for the pizza tracker — runs ALL scrapers and pushes to Firestore.

Launched by Windows Task Scheduler as:  python.exe  run_daily.py
Using a Python runner (instead of a .bat) because the project lives under a
path with Hebrew characters, which cmd.exe / Task Scheduler mishandle. Python
handles Unicode paths natively, so this is reliable.

Run it manually with:  python run_daily.py   (or double-click run_daily.bat)
"""

import os
import sys
import subprocess
import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)

# Firebase service-account key (edit if you moved it).
os.environ.setdefault("FIREBASE_SERVICE_ACCOUNT_FILE", r"C:\Users\eli\serviceAccount.json")
os.environ["PYTHONIOENCODING"] = "utf-8"

LOG = HERE / "run_daily.log"
SCRAPERS = ["multi_scraper.py", "branch_scraper.py", "paisplus_scraper.py", "wolt_scraper.py"]


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def main():
    log(f"\n===== [{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] START daily run =====")
    if not Path(os.environ["FIREBASE_SERVICE_ACCOUNT_FILE"]).exists():
        log(f"  ⚠ service-account key not found at {os.environ['FIREBASE_SERVICE_ACCOUNT_FILE']} "
            f"— data will save locally but NOT push to Firestore.")
    for mod in SCRAPERS:
        log(f"[{datetime.datetime.now():%H:%M:%S}] running {mod} ...")
        try:
            r = subprocess.run([sys.executable, str(HERE / mod)], cwd=str(HERE),
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=900)
            if r.stdout:
                log(r.stdout.rstrip())
            if r.returncode != 0 and r.stderr:
                log("STDERR:\n" + r.stderr.rstrip())
        except Exception as e:
            log(f"  ERROR running {mod}: {e}")
    log(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] DONE")


if __name__ == "__main__":
    main()
