#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rolling_deep_fetch.py

Rebuilds tmp_concat_deep.txt for the active date window by combining:
- fresh deep fetches (getGames.py) for needed dates
- existing games.csv lines for dates that already have data and don't need refetch

Then getClubs.py will be run separately on tmp_concat_deep.txt.
"""

from __future__ import annotations
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Set

# --- Paths ---
REPO_ROOT      = Path(__file__).resolve().parent.parent
SCRIPTS_DIR    = REPO_ROOT / "scripts"
DATA_DIR       = REPO_ROOT / "data"
CACHE_DEEP_DIR = REPO_ROOT / "cache" / "deep"
LOG_DIR        = REPO_ROOT / "logs"

GAMES_CSV  = DATA_DIR / "games.csv"
TMP_CONCAT = REPO_ROOT / "tmp_concat_deep.txt"

# 12-kolumners "deep"-header som getClubs.py förväntar sig
HEADER_12 = (
    "date;time;series_name;link_to_series;admin_host;"
    "home_team;away_team;result;result_link;arena;"
    "iteration_fetched;iterations_total"
)


# --- Logging helper ---
def log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with (LOG_DIR / "rolling_deep_fetch.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# --- Read existing games.csv and reconstruct 12-col deep rows ---
def parse_existing_games(path: Path):
    """
    Läser data/games.csv (19 kolumner) och bygger:
      - existing_dates: set med datumsträngar
      - rows_by_date:   date -> list[str] i 12-kolumners deep-format
    """
    dates: Set[str] = set()
    rows_by_date: Dict[str, List[str]] = {}

    if not path.exists():
        log("games.csv saknas – initial körning, inget att återanvända.")
        return dates, rows_by_date

    with path.open(encoding="utf-8") as f:
        header = f.readline()  # hoppa över headern
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(";")
            # Vi förväntar oss 19 kolumner i nuvarande schema
            if len(parts) < 13:
                # För kort rad / fel format – hoppa över
                continue

            d = parts[0]
            dates.add(d)

            # Rekonstruera 12-kolumners 'deep'-format från 19-kolumners games.csv:
            # index: 0=date,1=time,2=series_name,3=link_to_series,4=admin_host,
            #        5=home_team,6=away_team,7=result,8=result_link,9=arena,
            #        11=iteration_fetched,12=iterations_total (hoppar över status på index 10)
            keep_idx = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12]
            try:
                trimmed = ";".join(parts[i] for i in keep_idx)
            except IndexError:
                # Om något är knas, hoppa raden
                continue

            rows_by_date.setdefault(d, []).append(trimmed)

    log(f"Läste {len(dates)} datum från games.csv")
    return dates, rows_by_date


# --- Date helpers ---
def daterange(start_date, end_date):
    d = start_date
    while d <= end_date:
        yield d
        d += timedelta(days=1)


# --- Run getGames.py for a single date ---
def run_getgames_for_date(date_str: str) -> List[str]:
    """
    Kör getGames.py för ett datum och returnerar rader i 12-kolumnersformat
    (utan header). Logg per datum skrivs till logs/deep_YYYY-MM-DD.log.
    """
    CACHE_DEEP_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"deep_{date_str}.log"
    out_txt  = CACHE_DEEP_DIR / f"All_games_{date_str}_deep.txt"

    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "getGames.py"),
        "-sd", date_str,
        "-ed", date_str,
        "-ah", "null",
        "-f", str(out_txt),
    ]

    log(f"🔄 Kör getGames.py för {date_str}")
    with log_file.open("a", encoding="utf-8") as lf:
        lf.write(f"===== Fetching {date_str} =====\n")
        lf.flush()
        proc = subprocess.run(cmd, text=True, stdout=lf, stderr=lf)
        rc = proc.returncode

    if rc != 0:
        log(f"❌ getGames.py misslyckades för {date_str} (rc={rc})")
        return []

    if not out_txt.exists():
        log(f"❌ Utdatafil saknas efter getGames för {date_str}: {out_txt}")
        return []

    lines: List[str] = []
    with out_txt.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("date;"):
                # hoppa över eventuell header
                continue
            lines.append(line)

    log(f"✅ {len(lines)} rader fetched för {date_str}")
    return lines


# --- Main ---
def main(argv=None) -> int:
    today = datetime.utcnow().date()
    log(f"=== rolling_deep_fetch start (today={today}) ===")

    existing_dates, existing_rows_by_date = parse_existing_games(GAMES_CSV)

    if existing_dates:
        sorted_dates = sorted(existing_dates)
        min_date = datetime.strptime(sorted_dates[0], "%Y-%m-%d").date()
        max_date = datetime.strptime(sorted_dates[-1], "%Y-%m-%d").date()
        log(f"Nuvarande datumintervall i games.csv: {min_date} .. {max_date}")

        # Nytt fönster: behåll min_date, förläng max_date en dag framåt
        window_start = min_date
        window_end   = max_date + timedelta(days=1)
    else:
        # Initial körning – bygg ett fönster runt idag
        # (4 dagar bakåt, idag, 7 dagar framåt)
        window_start = today - timedelta(days=4)
        window_end   = today + timedelta(days=7)
        log(f"Inga befintliga datum – initialt fönster: {window_start} .. {window_end}")

    window_dates = list(daterange(window_start, window_end))
    log(f"Planerat fönster ({len(window_dates)} datum): {window_start} .. {window_end}")

    all_lines: List[str] = []
    today_str = today.strftime("%Y-%m-%d")

    for d in window_dates:
        ds = d.strftime("%Y-%m-%d")

        # Vi deep-fetchar om:
        #  - det är dagens datum (alltid fräscha matcher), eller
        #  - datumet saknas i games.csv (ny dag i fönstret eller tidigare hål)
        must_refetch = (ds == today_str) or (ds not in existing_dates)

        if must_refetch:
            log(f"📡 Datum {ds}: deep-fetchar (ny dag eller idag).")
            lines = run_getgames_for_date(ds)
        else:
            reused = existing_rows_by_date.get(ds, [])
            log(f"♻️ Datum {ds}: återanvänder {len(reused)} rader från games.csv.")
            lines = list(reused)

        if not lines:
            log(f"⚠️ Datum {ds}: inga rader att lägga till (skippas i tmp_concat).")
            continue

        all_lines.extend(lines)

    if not all_lines:
        log("❌ Inga rader i hela fönstret – skriver inte tmp_concat_deep.txt")
        return 1

    # Skriv tmp_concat_deep.txt i 12-kolumners deep-format
    with TMP_CONCAT.open("w", encoding="utf-8") as f:
        f.write(HEADER_12 + "\n")
        for line in all_lines:
            f.write(line + "\n")

    log(f"💾 Skrev {len(all_lines)} matcher till {TMP_CONCAT}")
    log("=== rolling_deep_fetch klar ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

