#!/usr/bin/env python3
import csv
import argparse
import os
from datetime import datetime, timedelta

GAMES_FILE = "data/games.csv"
NEW_FILE = "data/games_new.csv"

HEADER = [
    "date","time","series_name","link_to_series","admin_host","home_team","away_team",
    "result","result_link","arena","status","iteration_fetched","iterations_total",
    "home_club_list","away_club_list","arena_nbr","PreferedName","Lat","Long"
]


def load_csv(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for r in reader:
            rows.append(r)
    return rows


def game_key(row):
    """Nyckel som identifierar en match oberoende av GameLink."""
    return (
        row.get("date", ""),
        row.get("time", ""),
        row.get("series_name", ""),
        row.get("link_to_series", ""),
        row.get("home_team", ""),
        row.get("away_team", ""),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Base date (YYYY-MM-DD)")
    parser.add_argument("--window", type=int, default=7)
    args = parser.parse_args()

    base = datetime.strptime(args.date, "%Y-%m-%d")

    old_games = load_csv(GAMES_FILE)
    new_games = load_csv(NEW_FILE)

    # Bygg index på game_key
    old_index = {}
    for r in old_games:
        k = game_key(r)
        if any(k):  # åtminstone något ifyllt
            old_index[k] = r

    new_index = {}
    for r in new_games:
        k = game_key(r)
        if any(k):
            new_index[k] = r

    merged = []

    # 1) Gå igenom gamla matcher och uppdatera inom datumfönster
    for k, old_row in old_index.items():
        date_str = old_row.get("date", "")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            # Om datumet är konstigt, behåll raden
            merged.append(old_row)
            continue

        if base <= dt <= base + timedelta(days=args.window):
            # Datum inom fönster – uppdatera om vi har en ny rad, annars behåll
            if k in new_index:
                merged.append(new_index[k])
            else:
                merged.append(old_row)
        else:
            # Datum utanför fönster – behåll alltid gammal rad
            merged.append(old_row)

    # 2) Lägg till matcher som bara finns i new_index (helt nya matcher)
    for k, new_row in new_index.items():
        if k not in old_index:
            merged.append(new_row)

    # 3) Sortera
    def sort_key(r):
        try:
            d = datetime.strptime(r.get("date", "1900-01-01"), "%Y-%m-%d")
        except Exception:
            d = datetime(1900, 1, 1)
        t = r.get("time", "")
        return (
            d,
            t,
            r.get("series_name", ""),
            r.get("home_team", ""),
            r.get("away_team", ""),
        )

    merged_sorted = sorted(merged, key=sort_key)

    # 4) Skriv tillbaka till games.csv
    os.makedirs(os.path.dirname(GAMES_FILE), exist_ok=True)
    with open(GAMES_FILE, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(HEADER)
        for r in merged_sorted:
            writer.writerow([r.get(col, "") for col in HEADER])

    print(f"Merged {len(old_games)} (old) + {len(new_games)} (new) → {len(merged_sorted)} rows")


if __name__ == "__main__":
    main()

