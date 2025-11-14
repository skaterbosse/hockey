#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
archive_old_games.py
Flyttar matcher som faller ut ur rullande datumfönstret från games.csv till oldGames.csv.
Körs som första steg i update-deep.

Krav:
- oldGames.csv måste redan finnas (vi rör den bara).
- games.csv måste finnas.
- Skriptet är idempotent: körningar under samma datum gör ingen skada.
"""

import csv
from pathlib import Path
from datetime import datetime, timedelta

GAMES = Path("data/games.csv")
OLD = Path("data/oldGames.csv")
STATE_FILE = Path("data/archive_state.txt")   # håller reda på senaste arkiverade datum


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def main():
    today = datetime.now().date()

    # Räkna ut vilket datum som ska arkiveras
    # Aktivt fönster: -4 bakåt → +7 framåt
    oldest_active = today - timedelta(days=4)
    date_to_archive = oldest_active - timedelta(days=1)

    # Idempotens: om vi redan arkiverat detta datum, gör ingenting
    if STATE_FILE.exists():
        last = STATE_FILE.read_text().strip()
        if last == str(date_to_archive):
            print(f"[archive] Redan arkiverat {date_to_archive}, gör ingenting.")
            return

    print(f"[archive] Arkiverar matcher från datum: {date_to_archive}")

    # Läs games.csv
    if not GAMES.exists():
        print("[archive] games.csv saknas – kan inte arkivera.")
        return

    with GAMES.open() as f:
        reader = csv.reader(f, delimiter=";")
        rows = list(reader)

    archive_rows = [r for r in rows if r and r[0] == str(date_to_archive)]

    if not archive_rows:
        print(f"[archive] Inga matcher att arkivera för {date_to_archive}.")
    else:
        # Se till att oldGames.csv finns
        OLD.parent.mkdir(parents=True, exist_ok=True)
        if not OLD.exists():
            OLD.write_text("")

        # Läs befintliga oldGames
        with OLD.open() as f:
            existing = {tuple(r) for r in csv.reader(f, delimiter=";")}

        # Appendera nya rader som inte finns
        with OLD.open("a") as f:
            w = csv.writer(f, delimiter=";")
            added = 0
            for r in archive_rows:
                t = tuple(r)
                if t not in existing:
                    w.writerow(r)
                    added += 1

        print(f"[archive] La till {added} nya matcher i oldGames.csv")

    # Uppdatera state
    STATE_FILE.write_text(str(date_to_archive))


if __name__ == "__main__":
    main()

