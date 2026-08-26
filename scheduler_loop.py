"""Runs the pipeline forever, staggering source groups across a 6-minute
cadence instead of hitting every source in one batch every 30 minutes.

Why: with a single 30-minute batch, the site updates in one lump and then
sits static for 30 minutes — reads as obviously mechanical. Real news sites
feel alive because different outlets publish asynchronously. Splitting our
~14 sources into 5 groups and checking one group every 6 minutes (30÷5)
means something new shows up in a steady trickle instead, without changing
how often any single source is actually checked (still every 30 min).

This still replaces Windows Task Scheduler for the same reason as before —
this account lacks the "log on as a batch job" privilege — see the
2026-08-26 note in run_pipeline.py's design doc entry.

Usage: python scheduler_loop.py
Stop with Ctrl+C, or by killing the process.
"""
from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import run_pipeline
from fetch_news import FEEDS

GROUP_COUNT = 5
TICK_INTERVAL_S = (30 * 60) // GROUP_COUNT  # 360s = 6 min
HEARTBEAT_FILE = Path(__file__).parent / "data" / "scheduler_heartbeat.txt"


def _build_groups() -> list[list[str]]:
    """Round-robin split of feed names into GROUP_COUNT groups, so each
    group is a reasonably even mix of categories/outlets rather than one
    group being all-MARKET and another all-SPORTS."""
    names = list(FEEDS.keys())
    groups: list[list[str]] = [[] for _ in range(GROUP_COUNT)]
    for i, name in enumerate(names):
        groups[i % GROUP_COUNT].append(name)
    return groups


def main() -> None:
    groups = _build_groups()
    print(f"[scheduler] {len(FEEDS)} sources split into {GROUP_COUNT} groups, "
          f"one group every {TICK_INTERVAL_S}s (full cycle: {TICK_INTERVAL_S * GROUP_COUNT}s):")
    for i, g in enumerate(groups):
        print(f"  group {i}: {g}")
    print(f"[scheduler] starting. Ctrl+C to stop.")

    tick = 0
    while True:
        group = groups[tick % GROUP_COUNT]
        started = datetime.now(timezone.utc).isoformat()
        HEARTBEAT_FILE.parent.mkdir(exist_ok=True)
        HEARTBEAT_FILE.write_text(started)  # watchdog.py checks this to detect a dead process
        print(f"\n[scheduler] tick {tick} (group {tick % GROUP_COUNT} = {group}) starting at {started}")
        try:
            run_pipeline.run(sources=group)
        except Exception:  # noqa: BLE001 — a bad run must not kill the loop
            print("[scheduler] run failed with an exception:")
            traceback.print_exc()
        tick += 1
        print(f"[scheduler] sleeping {TICK_INTERVAL_S}s until next tick...")
        time.sleep(TICK_INTERVAL_S)


if __name__ == "__main__":
    main()
