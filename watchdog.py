"""Watches scheduler_loop.py and api_server.py, relaunches whichever has
died. Built because both have silently died mid-session at least twice
(2026-08-26) with no crash/traceback in their logs — plausibly Windows
suspending background console processes, but the exact cause wasn't
identified. This catches that failure mode.

What this does NOT cover, and can't: if the machine sleeps, reboots, or
this account logs off, everything including this watchdog stops, and
nothing local restarts it. Windows Task Scheduler (missing "log on as a
batch job") and a real Windows Service (needs admin) are both blocked on
this account — confirmed 2026-08-26. The only way to survive a reboot is
either getting one of those two privileges granted, or actually moving the
pipeline to run on AWS instead of this laptop.

Usage: python watchdog.py
Stop with Ctrl+C, or by killing the process.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
HEARTBEAT_FILE = PROJECT_DIR / "data" / "scheduler_heartbeat.txt"
API_PORT = 8420
CHECK_INTERVAL_S = 120
HEARTBEAT_STALE_AFTER_S = 12 * 60  # scheduler ticks every 6 min; 2 missed ticks = dead
PYTHON = sys.executable


def _log(msg: str) -> None:
    print(f"[watchdog {datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def _scheduler_is_alive() -> bool:
    if not HEARTBEAT_FILE.exists():
        return False
    age = time.time() - HEARTBEAT_FILE.stat().st_mtime
    return age < HEARTBEAT_STALE_AFTER_S


def _api_is_alive() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", API_PORT), timeout=3):
            return True
    except OSError:
        return False


def _relaunch(script: str, log_file: str) -> None:
    _log(f"relaunching {script}...")
    log_path = PROJECT_DIR / "data" / log_file
    with open(log_path, "a", encoding="utf-8") as f:
        subprocess.Popen(
            [PYTHON, script],
            cwd=str(PROJECT_DIR),
            stdout=f,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        )


def main() -> None:
    _log(f"starting, checking every {CHECK_INTERVAL_S}s. Ctrl+C to stop.")
    _log("NOTE: this does not survive machine sleep/reboot/logoff — see module docstring.")
    while True:
        if not _scheduler_is_alive():
            _log("scheduler_loop.py appears dead (heartbeat stale or missing)")
            _relaunch("scheduler_loop.py", "scheduler_loop.log")
        if not _api_is_alive():
            _log("api_server.py appears dead (port 8420 not responding)")
            _relaunch("api_server.py", "api_server.log")
        time.sleep(CHECK_INTERVAL_S)


if __name__ == "__main__":
    main()
