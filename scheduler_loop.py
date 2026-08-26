"""Runs the pipeline every 30 minutes, forever, as a single long-lived
process — used instead of Windows Task Scheduler because this environment's
account lacks the "log on as a batch job" privilege Task Scheduler needs to
launch anything (confirmed 2026-08-26: even a trivial echo-to-file
diagnostic task silently failed to execute, both under the default
Interactive logon type and under S4U). This process just needs to stay
running; if the machine restarts, it needs to be started again manually
(or wired into a real startup mechanism later — see note in the design doc).

Usage: python scheduler_loop.py
Stop with Ctrl+C, or by killing the process.
"""
from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone

import run_pipeline

INTERVAL_S = 30 * 60


def main() -> None:
    print(f"[scheduler] starting, running every {INTERVAL_S}s. Ctrl+C to stop.")
    while True:
        started = datetime.now(timezone.utc).isoformat()
        print(f"\n[scheduler] run starting at {started}")
        try:
            run_pipeline.run()
        except Exception:  # noqa: BLE001 — a bad run must not kill the loop
            print("[scheduler] run failed with an exception:")
            traceback.print_exc()
        print(f"[scheduler] sleeping {INTERVAL_S}s until next run...")
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    main()
