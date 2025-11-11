#!/usr/bin/env python3
"""
shallow_update_gatekeeper.py
Läser data/games.csv (;-separerad) och avgör om en shallow-uppdatering ska köras NU.

Villkor (svensk tid, Europe/Stockholm):
1)  matchstart - 1h45m  ≤  nu  ≤  matchstart
2)  matchstart ≤  nu  ≤  matchstart + 3h15m

Skriver RUN_SHALLOW=true/false till GITHUB_OUTPUT (för GitHub Actions).
Returnerar alltid exit code 0 (så workflow inte "failar" bara för att vi hoppar över).
"""

from __future__ import annotations
import csv
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import os
import sys

TZ_SE = ZoneInfo("Europe/Stockholm")
TZ_UTC = ZoneInfo("UTC")

REPO_ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = REPO_ROOT / "data" / "games.csv"

def parse_match_dt(date_str: str, time_str: str) -> datetime:
    # Antag: date = YYYY-MM-DD, time = HH:MM (lokal svensk tid)
    dt_naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    dt_local = dt_naive.replace(tzinfo=TZ_SE)
    return dt_local

def main():
    should_run = False

    if not CSV_PATH.exists():
        print(f"INFO: {CSV_PATH} saknas — kan inte bedöma, skippar shallow.")
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as f:
                f.write("RUN_SHALLOW=false\n")
        return 0

    now_utc = datetime.now(TZ_UTC)
    now_se = now_utc.astimezone(TZ_SE)
    today_se = now_se.date()

    # Läs CSV
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            date = (row.get("date") or "").strip()
            time = (row.get("time") or "").strip()
            if not date or not time:
                continue

            try:
                dt_local = parse_match_dt(date, time)
            except Exception:
                continue

            if dt_local.date() != today_se:
                continue  # Endast dagens matcher styr shallow

            start = dt_local
            pre_window = start - timedelta(hours=1, minutes=45)
            post_window = start + timedelta(hours=3, minutes=15)

            if pre_window <= now_se <= post_window:
                should_run = True
                break

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"RUN_SHALLOW={'true' if should_run else 'false'}\n")

    print(f"Gatekeeper: now(SE)={now_se.isoformat()}, run={should_run}")
    return 0

if __name__ == "__main__":
    sys.exit(main())

