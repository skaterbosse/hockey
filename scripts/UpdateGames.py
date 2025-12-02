#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UpdateGames.py

Slår samman befintlig data/games.csv med ny data som skapats av createGamesFile.py.
Regler:
- games_new.csv innehåller matcher för antingen TODAY, PLUS7 eller båda.
- Endast rader som matchar de datum som finns i games_new.csv ska ersättas.
- Alla andra datum i games.csv ska sparas oförändrade.
"""

import csv
import sys
import os
from collections import defaultdict

INPUT_FILE = "data/games_new.csv"
OUTPUT_FILE = "data/games_new_merged.csv"
MASTER_GAMES_FILE = "data/games.csv"


def load_csv(path):
    """Hjälpfunktion för att läsa CSV till lista av dictar"""
    if not os.path.exists(path):
        return []

    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            rows.append(r)
    return rows


def write_csv(path, header, rows):
    """Skriv CSV med ; som separator"""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, delimiter=";", fieldnames=header)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def main():

    print("[UpdateGames] Loading old games.csv ...")
    old_games = load_csv(MASTER_GAMES_FILE)

    print("[UpdateGames] Loading new games (games_new.csv) ...")
    new_games = load_csv(INPUT_FILE)

    # Om inga nya matcher → behåll gamla CSV orörd
    if len(new_games) == 0:
        print("[UpdateGames] WARNING: No new games found → keeping games.csv unchanged")
        return

    # Läs header (från new_games eller old_games vid fallback)
    header = None
    if len(new_games) > 0:
        header = list(new_games[0].keys())
    elif len(old_games) > 0:
        header = list(old_games[0].keys())
    else:
        print("[UpdateGames] ERROR: No valid CSV data")
        sys.exit(1)

    # Gruppera nya matcher per datum
    new_by_date = defaultdict(list)
    for row in new_games:
        new_by_date[row["date"]].append(row)

    print(f"[UpdateGames] New dates found: {list(new_by_date.keys())}")

    # Bygg slutlistan
    merged = []

    # Behåll alla gamla matcher där datum INTE finns i new_games
    for row in old_games:
        d = row["date"]
        if d not in new_by_date:
            merged.append(row)

    # Lägg till alla nya matcher (ersätter gamla datum)
    for d in sorted(new_by_date.keys()):
        print(f"[UpdateGames] Inserting {len(new_by_date[d])} matches for {d}")
        for row in new_by_date[d]:
            merged.append(row)

    # Sortera resultat per date och time
    merged_sorted = sorted(merged, key=lambda r: (r["date"], r["time"]))

    # Skriv tillbaka till games.csv
    print(f"[UpdateGames] Writing merged result → {MASTER_GAMES_FILE}")
    write_csv(MASTER_GAMES_FILE, header, merged_sorted)

    # Rensa tempfil
    if os.path.exists(INPUT_FILE):
        os.remove(INPUT_FILE)

    print("[UpdateGames] Done.")


if __name__ == "__main__":
    main()

