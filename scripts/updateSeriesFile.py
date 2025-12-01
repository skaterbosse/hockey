#!/usr/bin/env python3
import argparse
import csv
import os
import re
import subprocess
import sys

SERIES_FILE = "data/series.csv"
GAMES_FILE = "data/games.csv"

HEADER = ["SerieLink", "SerieName", "Live", "DoneToday"]


def debug(enabled, *args):
    if enabled:
        print("[updateSeriesFile]", *args)


def read_games_for_date(date, dbg=False):
    """Returns a list of (SerieLink, SerieName) for today's matches."""
    if not os.path.exists(GAMES_FILE):
        print(f"ERROR: {GAMES_FILE} missing", file=sys.stderr)
        return []

    result = []
    with open(GAMES_FILE, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for row in reader:
            if row["date"] == date:
                link = row["link_to_series"]
                name = row["series_name"]
                result.append((link, name))
    return result


def detect_live_status(serie_link, dbg=False):
    """
    Determine Live=Yes/No by checking if the Live page exists.
    Live page derived by replacing 'Overview' with 'Live'.
    """
    m = re.search(r"/Overview/([0-9]+)", serie_link)
    if not m:
        return "No"

    sid = m.group(1)
    url = f"https://stats.swehockey.se/ScheduleAndResults/Overview/{sid}"

    # Curl command
    cmd = f"curl -L -s {url} | egrep '/ScheduleAndResults/Live/{sid}' | wc -l"
    try:
        output = subprocess.check_output(cmd, shell=True, text=True).strip()
        return "Yes" if output != "0" else "No"
    except Exception:
        return "No"


def load_existing_series(dbg=False):
    if not os.path.exists(SERIES_FILE):
        return {}

    with open(SERIES_FILE, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        result = {}
        for row in reader:
            link = row["SerieLink"]
            result[link] = {
                "SerieName": row["SerieName"],
                "Live": row["Live"],
                "DoneToday": row["DoneToday"]
            }
        return result


def write_series_file(series_dict, dbg=False):
    with open(SERIES_FILE, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(HEADER)
        for link, data in sorted(series_dict.items()):
            writer.writerow([
                link,
                data["SerieName"],
                data["Live"],
                data["DoneToday"]
            ])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--reset-done", action="store_true",
                        help="Reset DoneToday=No for all series")
    parser.add_argument("-dbg", "--debug", action="store_true")
    args = parser.parse_args()

    dbg = args.debug
    date = args.date

    # ----------------------------------------------------------
    # STEP 1: Load existing series
    # ----------------------------------------------------------
    existing = load_existing_series(dbg)
    debug(dbg, f"Loaded {len(existing)} existing series")

    # ----------------------------------------------------------
    # STEP 2: Extract series from today's matches
    # ----------------------------------------------------------
    todays_series = read_games_for_date(date, dbg)
    debug(dbg, f"Found {len(todays_series)} series in todays games")

    # Build a result map
    result = existing.copy()

    for (link, name) in todays_series:
        if link not in result:
            # New serie → detect Live and initialize DoneToday=No
            debug(dbg, f"NEW serie detected: {link}")
            live = detect_live_status(link, dbg)
            result[link] = {
                "SerieName": name,
                "Live": live,
                "DoneToday": "No"
            }
        else:
            # Existing serie → update name (safeguard)
            result[link]["SerieName"] = name

    # ----------------------------------------------------------
    # STEP 3: Reset DoneToday values if requested
    # ----------------------------------------------------------
    if args.reset_done:
        debug(dbg, "Resetting DoneToday for all series to No")
        for link in result:
            result[link]["DoneToday"] = "No"

    # ----------------------------------------------------------
    # STEP 4: Write updated series.csv
    # ----------------------------------------------------------
    write_series_file(result, dbg)
    debug(dbg, "series.csv updated.")


if __name__ == "__main__":
    main()

