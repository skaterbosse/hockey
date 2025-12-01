#!/usr/bin/env python3
import csv
import argparse
from datetime import datetime, timedelta

GAMES_FILE = "data/games.csv"
NEW_FILE = "data/games_new.csv"

# Columns in games.csv
HEADER = [
    "date","time","series_name","link_to_series","admin_host","home_team","away_team",
    "result","result_link","arena","status","iteration_fetched","iterations_total",
    "home_club_list","away_club_list","arena_nbr","PreferedName","Lat","Long"
]

def load_csv(path):
    rows = []
    if not path or not path.endswith(".csv"):
        return rows
    try:
        with open(path, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            for r in reader:
                rows.append(r)
    except FileNotFoundError:
        return []
    return rows

def extract_game_id(result_link):
    import re
    m = re.search(r"/Game/(Events|LineUps)/(\d+)", result_link or "")
    return m.group(2) if m else ""

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Base date (YYYY-MM-DD)")
    parser.add_argument("--window", type=int, default=7)
    args = parser.parse_args()

    base = datetime.strptime(args.date, "%Y-%m-%d")

    # Load existing & new data
    old_games = load_csv(GAMES_FILE)
    new_games = load_csv(NEW_FILE)

    # Build index: gameID → row
    old_index = {}
    for r in old_games:
        gid = extract_game_id(r["result_link"])
        if gid:
            old_index[gid] = r

    new_index = {}
    for r in new_games:
        gid = extract_game_id(r["result_link"])
        if gid:
            new_index[gid] = r

    merged = []

    # Add/update rows for old games
    for gid, old_row in old_index.items():
        date = old_row["date"]
        dt = datetime.strptime(date, "%Y-%m-%d")

        if base <= dt <= base + timedelta(days=args.window):
            # This date is refreshed if we have new data
            if gid in new_index:
                merged.append(new_index[gid])
            else:
                merged.append(old_row)
        else:
            # Keep old data for dates outside the update window
            merged.append(old_row)

    # Add new games not in old
    for gid, new_row in new_index.items():
        if gid not in old_index:
            merged.append(new_row)

    # Sort merged
    def sort_key(r):
        try:
            return (
                datetime.strptime(r["date"], "%Y-%m-%d"),
                r["time"],
                extract_game_id(r["result_link"])
            )
        except:
            return (datetime.min, "00:00", "")
    merged = sorted(merged, key=sort_key)

    # Write merged result
    with open(GAMES_FILE, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(HEADER)
        for r in merged:
            writer.writerow([r.get(col, "") for col in HEADER])

    print(f"Merged {len(old_games)} + {len(new_games)} → {len(merged)} rows")


if __name__ == "__main__":
    main()

