#!/usr/bin/env python3
import csv
from datetime import datetime, timedelta
import os
import sys

GAMES_FILE = "data/games.csv"
OLD_GAMES_FILE = "data/oldGames.csv"

DATE_FORMAT = "%Y-%m-%d"

def log(msg):
    print(f"[ARCHIVE] {msg}")

def parse_date(d):
    try:
        return datetime.strptime(d, DATE_FORMAT).date()
    except:
        return None

def main():
    log("Startar arkivering av gamla matcher...")

    today = datetime.utcnow().date()
    expire_date = today - timedelta(days=5)

    log(f"Idag: {today}")
    log(f"EXPIRE_DATE = {expire_date}")

    # --- Steg 1: Läs games.csv ---
    if not os.path.exists(GAMES_FILE):
        log(f"Filen {GAMES_FILE} saknas! Ingenting att arkivera.")
        return 0  # OK

    with open(GAMES_FILE, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=';')
        games = list(reader)
        fieldnames = reader.fieldnames

    if not games:
        log("games.csv är tom – ingen arkivering behövs.")
        return 0

    # --- Steg 2: Hitta rader att flytta ---
    rows_for_expire = [g for g in games if parse_date(g["date"]) == expire_date]

    if not rows_for_expire:
        log(f"Inga matcher hittades i games.csv för {expire_date}. Ingenting att arkivera idag.")
        return 0  # Viktigt: detta är OK – andra körningen ska inte faila

    log(f"Hittade {len(rows_for_expire)} rader att arkivera från {expire_date}")

    # --- Steg 3: Skriv / uppdatera oldGames.csv ---
    existing_old = []
    if os.path.exists(OLD_GAMES_FILE):
        with open(OLD_GAMES_FILE, newline='', encoding="utf-8") as f:
            old_reader = csv.DictReader(f, delimiter=';')
            existing_old = list(old_reader)

    # Undvik dubblering
    existing_ids = {(g["date"], g["home_team"], g["away_team"], g["series_name"])
                    for g in existing_old}

    merged = list(existing_old)

    new_unique = []
    for row in rows_for_expire:
        key = (row["date"], row["home_team"], row["away_team"], row["series_name"])
        if key not in existing_ids:
            new_unique.append(row)

    log(f"Lägger till {len(new_unique)} NYA matcher i oldGames.csv")

    merged.extend(new_unique)

    # Sortera oldGames efter datum
    merged.sort(key=lambda g: parse_date(g["date"]))

    # Skriv tillbaka oldGames.csv
    with open(OLD_GAMES_FILE, "w", newline='', encoding="utf-8") as f:
        writer = csv.DictWriter(f, delimiter=';', fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged)

    log(f"oldGames.csv uppdaterad ({len(merged)} matcher totalt).")

    # --- Steg 4: Skriv tillbaka games.csv utan de arkiverade raderna ---
    remaining = [g for g in games if parse_date(g["date"]) != expire_date]

    with open(GAMES_FILE, "w", newline='', encoding="utf-8") as f:
        writer = csv.DictWriter(f, delimiter=';', fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(remaining)

    log(f"games.csv uppdaterad – {len(remaining)} rader kvar.")

    log("Arkivering klar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

