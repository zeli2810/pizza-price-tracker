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
import time
import subprocess
import datetime
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)

# Firebase service-account key (edit if you moved it).
os.environ.setdefault("FIREBASE_SERVICE_ACCOUNT_FILE", r"C:\Users\eli\serviceAccount.json")
os.environ["PYTHONIOENCODING"] = "utf-8"

# Anthropic API key for the marketing idea extractor: from env, else a key file.
if not os.environ.get("ANTHROPIC_API_KEY"):
    for kf in (r"C:\Users\eli\.pizza\anthropic_key.txt", str(HERE / "anthropic_key.txt")):
        try:
            if Path(kf).exists():
                os.environ["ANTHROPIC_API_KEY"] = Path(kf).read_text(encoding="utf-8").strip()
                break
        except Exception:
            pass

LOG = HERE / "run_daily.log"
SCRAPERS = ["multi_scraper.py", "offer_scraper.py", "branch_scraper.py",
            "paisplus_scraper.py", "paisplus_general_scraper.py", "wolt_scraper.py",
            "wolt_competitors_scraper.py",
            "tabit_scraper.py", "qsr_scraper.py", "press_scraper.py",
            "credit_card_purchases_scraper.py", "marketing_scraper.py"]


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


# Ollama used to auto-start at login and sit in the background all day eating
# RAM/CPU (llama-server). It's only needed for the ~15-60min marketing_scraper
# step, so we start it just before that step and stop it right after.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


def _ollama_up():
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3)
        return True
    except Exception:
        return False


def start_ollama():
    if _ollama_up():
        log("  Ollama already running.")
        return None
    try:
        proc = subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, cwd=str(HERE))
    except Exception as e:
        log(f"  ⚠ could not start Ollama: {e}")
        return None
    for _ in range(30):          # up to ~30s for the server to come up
        if _ollama_up():
            log("  Ollama started ✓")
            return proc
        time.sleep(1)
    log("  ⚠ Ollama did not respond in time.")
    return proc


def stop_ollama(proc):
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    log("  Ollama stopped.")


def main():
    log(f"\n===== [{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] START daily run =====")
    if not Path(os.environ["FIREBASE_SERVICE_ACCOUNT_FILE"]).exists():
        log(f"  ⚠ service-account key not found at {os.environ['FIREBASE_SERVICE_ACCOUNT_FILE']} "
            f"— data will save locally but NOT push to Firestore.")
    for mod in SCRAPERS:
        log(f"[{datetime.datetime.now():%H:%M:%S}] running {mod} ...")
        # Marketing (local LLM), QSR (chain pages through Cloudflare), and the
        # Wolt competitor scan (~50 cities, 2 searches each) are the slow ones —
        # don't time-limit them; the others finish in minutes.
        timeout = None if mod in ("marketing_scraper.py", "qsr_scraper.py",
                                   "wolt_competitors_scraper.py") else 900

        # Ollama only needs to run for the marketing step — start it fresh here
        # and stop it right after, instead of leaving it resident all day.
        ollama_proc = start_ollama() if mod == "marketing_scraper.py" else None
        try:
            r = subprocess.run([sys.executable, str(HERE / mod)], cwd=str(HERE),
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout)
            if r.stdout:
                log(r.stdout.rstrip())
            if r.returncode != 0 and r.stderr:
                log("STDERR:\n" + r.stderr.rstrip())
        except Exception as e:
            log(f"  ERROR running {mod}: {e}")
        finally:
            if mod == "marketing_scraper.py":
                stop_ollama(ollama_proc)
    log(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] DONE")


if __name__ == "__main__":
    main()
