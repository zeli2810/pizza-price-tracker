#!/bin/bash
set -e

Xvfb :99 -screen 0 1440x900x24 &
XVFB_PID=$!

cleanup() {
  kill "$XVFB_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Give Xvfb a moment to bind the display before Chrome starts using it.
sleep 1

exec uvicorn app:app --host 0.0.0.0 --port 8000
