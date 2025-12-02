#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
updateLightSeriesResults.py

Syfte:
- Uppdatera RESULTAT (kolumnen "result") i data/games.csv för LIGHT-serier
  (där Live == "YesLight" i data/series.csv) för ett visst datum.

Strategi:
- Använd den beprövade pipelinen getGames.py + getClubs.py (samma som createGamesFile.py):
    * Hämta GamesByDate för given dag.
    * Förädla med klubbar/arenor.
- Filtrera ut matcher som hör till LIGHT-serier (baserat på series.csv).
- Slå in dessa uppdaterade rader i data/games.csv (ersätt bara matcherna
  som både:
    * har samma datum,
    * och ligger i LIGHT-seriernas link_to_series).

Detta script fokuserar enbart på resultat-fältet (och övriga game-fält från pipelinen)
och skapar INTE några Events/LineUps-filer.
"""

import csv
import sys
import os
from datetime import datetime
from typing import Dict, List, Set
import subprocess

SERIES_FILE = "data/series.csv"
GAMES_FILE = "data/games.csv"

BASE = os.path.dirname(os.path.abspath(__file__))


def debug_print(dbg: bool, *args):
    if dbg:
        print("[updateLightSeriesResults]", *args)


def load_light_series(dbg: bool = False) -> Set[str]:
    """
    Läser data/series.csv och returnerar en mängd av SerieLink
    för de serier som är LIGHT (Live == 'YesLight').
    """
    if not os.path.exists(SERIES_FILE):
        debug_print(dbg, f"{SERIES_FILE} not found, no light series.")
        return set()

    light_links: Set[str] = set()

    with open(SERIES_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            live = (row.get("Live") or "").strip()
            link = (row.get("SerieLink") or "").strip()
            if live == "YesLight" and link:
                light_links.add(link)

    debug_print(dbg, f"Found {len(light_links)} LIGHT series in {SERIES_FILE}")
    return light_links


def load_games(path: str, dbg: bool = False) -> List[dict]:
    """Läser en games-fil (CSV med ;) till lista med dictar."""
    if not os.path.exists(path):
        debug_print(dbg, f"{path} not found.")
        return []
    rows: List[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            rows.append(r)
    return rows


def write_games(path: str, header: List[str], rows: List[dict]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, delimiter=";", fieldnames=header)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    dbg = False
    target_date = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--date" and i + 1 < len(argv):
            target_date = argv[i + 1]
            i += 2
        elif arg == "-dbg":
            dbg = True
            i += 1
        else:
            i += 1

    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")

    debug_print(dbg, f"Updating LIGHT series results for date {target_date}")

    light_series_links = load_light_series(dbg=dbg)
    if not light_series_links:
        debug_print(dbg, "No LIGHT series configured → nothing to do.")
        return 0

    # 1) Kör samma pipeline som createGamesFile.py, men skriv till en separat tmp-fil
    os.makedirs("data", exist_ok=True)
    tmp_file = os.path.join("data", "games_light_tmp.csv")
    tmp_out = os.path.join("data", "games_light_new.csv")

    # Steg 1: getGames.py
    cmd1 = [
        "python3",
        os.path.join(BASE, "getGames.py"),
        "-sd", target_date,
        "-ed", target_date,
        "-ah", "null",
        "-f", tmp_file,
    ]
    if dbg:
        cmd1.append("-dbg")

    debug_print(dbg, "Running:", " ".join(cmd1))
    r1 = subprocess.run(cmd1)
    if r1.returncode != 0:
        print("[updateLightSeriesResults] ERROR: getGames.py failed")
        return r1.returncode

    # Steg 2: getClubs.py
    cmd2 = [
        "python3",
        os.path.join(BASE, "getClubs.py"),
        "-gf", tmp_file,
        "-cf", os.path.join(BASE, "Clubs.txt"),
        "-af", os.path.join(BASE, "Arenas.csv"),
        "-scf", os.path.join(BASE, "Combined_clubs_teams.txt"),
        "-ogf", tmp_out,
    ]
    debug_print(dbg, "Running:", " ".join(cmd2))
    r2 = subprocess.run(cmd2)
    if r2.returncode != 0:
        print("[updateLightSeriesResults] ERROR: getClubs.py failed")
        return r2.returncode

    # Nu finns tmp_out med ALLA matcher för dagen → filtrera LIGHT-serierna
    new_all = load_games(tmp_out, dbg=dbg)
    if not new_all:
        debug_print(dbg, f"No new games for {target_date} from pipeline.")
        # Städa tmp-filer
        for p in (tmp_file, tmp_out):
            if os.path.exists(p):
                os.remove(p)
        return 0

    # Header tas från nya filen
    header = list(new_all[0].keys())

    # Normalisera länkarna så att jämförelse mot series.csv fungerar
    def norm_link(link: str) -> str:
        link = (link or "").strip()
        # I games.csv är link_to_series normalt en full URL från createGamesFile/getGames.
        # Men om något avviker kan vi ändå jämföra på suffixet "/ScheduleAndResults/Overview/<id>".
        return link

    light_links_norm = {norm_link(l) for l in light_series_links}

    # Filtrera nya matcher → bara LIGHT-serier
    new_light_rows: List[dict] = []
    for row in new_all:
        if row.get("date") != target_date:
            continue
        link = norm_link(row.get("link_to_series", ""))
        if link in light_links_norm:
            new_light_rows.append(row)

    debug_print(dbg, f"Found {len(new_light_rows)} light-series games for {target_date}")

    if not new_light_rows:
        # Städa tmp-filer
        for p in (tmp_file, tmp_out):
            if os.path.exists(p):
                os.remove(p)
        debug_print(dbg, "No LIGHT games to merge.")
        return 0

    # 2) Läs in befintlig games.csv
    old_games = load_games(GAMES_FILE, dbg=dbg)
    if not old_games:
        # Om games.csv är tom/inte finns, kan vi lika gärna bara skriva våra LIGHT-matcher.
        debug_print(dbg, f"{GAMES_FILE} is empty or missing, writing only light games.")
        write_games(GAMES_FILE, header, new_light_rows)
        # Städa tmp-filer
        for p in (tmp_file, tmp_out):
            if os.path.exists(p):
                os.remove(p)
        return 0

    # 3) Bygg merged lista:
    merged: List[dict] = []

    for row in old_games:
        d = row.get("date")
        link = norm_link(row.get("link_to_series", ""))
        # Ta bort rader för (target_date, LIGHT-serier) – dessa ersätts
        if d == target_date and link in light_links_norm:
            continue
        merged.append(row)

    # Lägg till de nya light-raderna
    merged.extend(new_light_rows)

    # Sortera på date + time
    merged_sorted = sorted(merged, key=lambda r: (r.get("date", ""), r.get("time", "")))

    # Skriv tillbaka
    write_games(GAMES_FILE, header, merged_sorted)

    # Städa tmp-filer
    for p in (tmp_file, tmp_out):
            if os.path.exists(p):
                os.remove(p)

    debug_print(dbg, f"Updated LIGHT series results for {target_date} in {GAMES_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

