#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
buildPollableGames.py

Version 2 – LIGHT-stöd:
Behåller både Events, LineUps och NoLinkLight.
Filtrerar bort Simple-serier (NoLink), som inte är Live.

Output: data/pollable_games.csv
"""

import csv
import os
import sys


INPUT_FILE = "data/live_games.csv"
OUTPUT_FILE = "data/pollable_games.csv"


def main():
    if not os.path.exists(INPUT_FILE):
        print(f"[buildPollableGames] ERROR: {INPUT_FILE} missing", file=sys.stderr)
        sys.exit(1)

    os.makedirs("data", exist_ok=True)

    with open(INPUT_FILE, newline="", encoding="utf-8") as fin, \
         open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as fout:

        reader = csv.DictReader(fin, delimiter=";")
        writer = csv.writer(fout, delimiter=";")

        writer.writerow(["SerieID", "GameID", "LinkType", "GameLink"])

        kept = 0
        for row in reader:
            link_type = row.get("LinkType", "")

            # Behåll: Events, LineUps, NoLinkLight
            if link_type not in ("Events", "LineUps", "NoLinkLight"):
                continue

            writer.writerow([
                row.get("SerieID", ""),
                row.get("GameID", ""),
                row.get("LinkType", ""),
                row.get("GameLink", ""),
            ])
            kept += 1

    print(f"[buildPollableGames] Kept {kept} pollable games → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

