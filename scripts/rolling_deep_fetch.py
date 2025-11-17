#!/usr/bin/env python3
import argparse
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

# ----------------------------------------------------------
# Paths
# ----------------------------------------------------------
GAMES_CSV = Path("data/games.csv")
CACHE_DIR = Path("cache/deep")
OUTPUT_FILE = Path("tmp_concat_deep.txt")
LOG_FILE = Path("logs/rolling_deep_fetch.log")


# ----------------------------------------------------------
# Logging
# ----------------------------------------------------------
def log(msg: str) -> None:
    """Log to stdout and a file."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full = f"[{ts}] {msg}"
    print(full, flush=True)

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(full + "\n")
    except Exception:
        pass


# ----------------------------------------------------------
# Read games.csv → dict(date → [rows])
# ----------------------------------------------------------
def read_games_by_date(path: Path) -> Dict[str, List[str]]:
    games: Dict[str, List[str]] = {}

    if not path.exists():
        log("games.csv saknas – använder tom struktur.")
        return games

    with path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue

            first = line.split(",", 1)[0].strip()

            # Skip header
            if first.lower() == "date":
                continue

            # Accept only YYYY-MM-DD
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", first):
                continue

            games.setdefault(first, []).append(line)

    if games:
        dates = sorted(games.keys())
        log(f"Läste {len(dates)} datum från games.csv")
        log(f"Intervall i games.csv: {dates[0]} .. {dates[-1]}")
    else:
        log("games.csv innehåller inga giltiga datum.")

    return games


# ----------------------------------------------------------
# Deep fetch with getGames.py
# ----------------------------------------------------------
def deep_fetch_date(d: date) -> List[str]:
    d_str = d.strftime("%Y-%m-%d")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"All_games_{d_str}_deep.txt"

    log(f"🔄 Deep-fetch {d_str}")

    cmd = [
        sys.executable,
        "scripts/getGames.py",
        "-sd", d_str,
        "-ed", d_str,
        "-f", str(cache_file),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)

    if res.returncode != 0:
        log(f"❌ getGames.py misslyckades (exit={res.returncode})")
        if res.stderr:
            log("STDERR:\n" + res.stderr)
        raise SystemExit(res.returncode)

    if cache_file.exists():
        rows = [
            ln.rstrip("\n")
            for ln in cache_file.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
    else:
        rows = []

    log(f"✅ {len(rows)} fetched för {d_str}")
    return rows


# ----------------------------------------------------------
# MAIN
# ----------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=int, default=12)  # Ignored now
    args = parser.parse_args(argv)

    # Reset log file
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("", encoding="utf-8")

    today = date.today()
    log(f"=== rolling_deep_fetch start (today={today}) ===")
    print(">>> TESTVERSION <<<")

    # 1. Read games.csv
    games = read_games_by_date(GAMES_CSV)

    # 2. Define the correct window
    window_start = today - timedelta(days=4)
    window_end   = today + timedelta(days=7)

    window_dates: List[date] = []
    d = window_start
    while d <= window_end:
        window_dates.append(d)
        d += timedelta(days=1)

    log(f"Fönster {len(window_dates)} dagar: {window_dates[0]} .. {window_dates[-1]}")

    special_today     = today
    special_future    = today + timedelta(days=7)

    all_rows: List[str] = []

    # 3. Process each date in window
    for d in window_dates:
        d_str = d.strftime("%Y-%m-%d")
        is_special = (d == special_today or d == special_future)

        if d_str in games:
            rows = games[d_str]

            if is_special:
                log(f"♻️ {d_str}: finns i games.csv men är specialdag → deep-fetch istället")
                fetched = deep_fetch_date(d)
                all_rows.extend(fetched)
            else:
                log(f"♻️ {d_str}: återanvänder {len(rows)} rader från games.csv")

                # Sync cache
                cache_file = CACHE_DIR / f"All_games_{d_str}_deep.txt"
                cache_file.write_text("\n".join(rows) + "\n", encoding="utf-8")

                all_rows.extend(rows)

        else:
            # Missing in games.csv
            if is_special:
                log(f"📡 {d_str}: saknas → deep-fetch (specialdag)")
                fetched = deep_fetch_date(d)
                all_rows.extend(fetched)
            else:
                log(f"⭕ {d_str}: tom matchdag → 0 rader")
                cache_file = CACHE_DIR / f"All_games_{d_str}_deep.txt"
                cache_file.write_text("", encoding="utf-8")
                # Add no lines

    # 4. Write output
    OUTPUT_FILE.write_text("\n".join(all_rows) + "\n", encoding="utf-8")

    log(f"💾 Skrev {len(all_rows)} rader till {OUTPUT_FILE.resolve()}")
    log("=== rolling_deep_fetch klar ===")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

