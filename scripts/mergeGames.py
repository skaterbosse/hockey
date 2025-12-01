#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
mergeGames.py

Säkerställer att games.csv växer korrekt.
Lägger till/uppdaterar dagens matcher utan att ta bort andra datum.
"""

import csv
import os


def main():
    base = "data/games.csv"
    newf = "data/games_new.csv"

    if not os.path.exists(newf):
        print("ERROR: games_new.csv missing")
        return

    existing = {}

    # Read existing games
    if os.path.exists(base):
        with open(base, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f, delimiter=";")
            for row in r:
                key = (row["date"], row["time"], row["home_team"], row["away_team"])
                existing[key] = row

    # Merge new games
    with open(newf, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            key = (row["date"], row["time"], row["home_team"], row["away_team"])
            existing[key] = row

    # Write full file back
    with open(base, "w", newline="", encoding="utf-8") as f:
        if not existing:
            return

        header = list(next(iter(existing.values())).keys())
        w = csv.DictWriter(f, fieldnames=header, delimiter=";")
        w.writeheader()
        for row in existing.values():
            w.writerow(row)

    print(f"[mergeGames] Wrote {len(existing)} matches → data/games.csv")


if __name__ == "__main__":
    main()

