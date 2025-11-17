#!/usr/bin/env python3
import argparse
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

# ----------------------------------------------------------
# Konfiguration
# ----------------------------------------------------------
GAMES_CSV = Path("data/games.csv")
CACHE_DIR = Path("cache/deep")
OUTPUT_FILE = Path("tmp_concat_deep.txt")
LOG_FILE = Path("logs/rolling_deep_fetch.log")


def log(msg: str) -> None:
    """Logga både till terminal och loggfil."""
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
# Läs datum och matcher från games.csv
# ----------------------------------------------------------
def read_games_by_date(path: Path) -> Dict[str, List[str]]:
    games_by_date: Dict[str, List[str]] = {}

    if not path.exists():
        log("games.csv saknas – börjar med tom struktur.")
        return games_by_date

    with path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue

            first = line.split(",", 1)[0].strip()

            # Skippa header
            if first.lower() == "date":
                continue

            # Endast giltiga datum (YYYY-MM-DD)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", first):
                continue

            games_by_date.setdefault(first, []).append(line)

    if games_by_date:
        dates = sorted(games_by_date.keys())
        log(f"Läste {len(dates)} datum från games.csv")
        log(f"Nuvarande intervall: {dates[0]} .. {dates[-1]}")
    else:
        log("games.csv innehåller inga giltiga datumrader.")

    return games_by_date


# ----------------------------------------------------------
# Deep-fetch för ett datum med getGames.py
# ----------------------------------------------------------
def deep_fetch_date(d: date) -> List[str]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    d_str = d.strftime("%Y-%m-%d")
    cache_file = CACHE_DIR / f"All_games_{d_str}_deep.txt"

    log(f"🔄 getGames.py för {d_str}")

    # Helt korrekt interface baserat på din hjälp-text:
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

    # Läs rader från cachefilen
    if cache_file.exists():
        lines = [ln.rstrip("\n") for ln in cache_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    else:
        lines = []

    log(f"✅ {len(lines)} rader fetched för {d_str}")
    return lines


# ----------------------------------------------------------
# MAIN
# ----------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=int, default=12)
    args = parser.parse_args(argv)

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("", encoding="utf-8")

    today = date.today()
    log(f"=== rolling_deep_fetch start (today={today}) ===")
    print(">>> TESTVERSION <<<")

    # 1. Läs befintliga matcher
    games_by_date = read_games_by_date(GAMES_CSV)
    known_dates = sorted(games_by_date.keys())

    if known_dates:
        min_date = datetime.strptime(known_dates[0], "%Y-%m-%d").date()
    else:
        # Om inga fasta datum finns → börja vid idag
        min_date = today
        log("games.csv saknas eller innehåller inga datum – startar vid idag.")

    # 2. Bygg fönstret
    window_start = min_date
    window_end = min_date + timedelta(days=args.window)

    window_dates = []
    d = window_start
    while d <= window_end:
        window_dates.append(d)
        d += timedelta(days=1)

    log(f"Fönster ({len(window_dates)} dagar): {window_dates[0]} .. {window_dates[-1]}")

    # 3. Loop över datum
    all_rows = []

    for d in window_dates:
        d_str = d.strftime("%Y-%m-%d")

        if d_str in games_by_date:
            rows = games_by_date[d_str]
            log(f"♻️ {d_str}: återanvänder {len(rows)} rader från games.csv")

            # Synka cache-filen
            cache_file = CACHE_DIR / f"All_games_{d_str}_deep.txt"
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text("\n".join(rows) + "\n", encoding="utf-8")

            all_rows.extend(rows)
        else:
            log(f"📡 {d_str}: tomt datum eller nytt datum → deep-fetch")
            fetched = deep_fetch_date(d)
            all_rows.extend(fetched)

    # 4. Skriv ut samlad concat-fil
    OUTPUT_FILE.write_text("\n".join(all_rows) + "\n", encoding="utf-8")

    log(f"💾 Skrev {len(all_rows)} rader till {OUTPUT_FILE.resolve()}")
    log("=== rolling_deep_fetch klar ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

