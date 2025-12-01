#!/usr/bin/env python3
import argparse
import csv
import os
import sys

HEADER = [
    "date","time","series_name","link_to_series","admin_host","home_team","away_team",
    "result","result_link","arena","status","iteration_fetched","iterations_total",
    "home_club_list","away_club_list","arena_nbr","PreferedName","Lat","Long"
]

def debug(enabled, *args):
    if enabled:
        print("[createGamesFile]", *args, file=sys.stderr)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--outfile", required=True, help="Path to output CSV")
    parser.add_argument("-dbg", "--debug", action="store_true")
    args = parser.parse_args()

    dbg = args.debug
    date = args.date
    outfile = args.outfile

    os.makedirs(os.path.dirname(outfile), exist_ok=True)

    # Just nu: skriv endast header + 0 rader (säkert läge)
    # mergeGames.py kommer då att behålla alla gamla matcher.
    debug(dbg, f"Creating empty games file for date {date} at {outfile}")

    with open(outfile, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(HEADER)
        # inga rader ännu – vi lägger till riktig hämtlogik senare

    debug(dbg, "Done, wrote only header.")

if __name__ == "__main__":
    main()

