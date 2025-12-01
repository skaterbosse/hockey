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
        print("[updateSeriesFile]", *args, file=sys.stderr)


def read_games_for_date(date, dbg=False):
    """Return a list of (SerieLink, SerieName) for all games on given date."""
    if not os.path.exists(GAMES_FILE):
        print(f"ERROR: {GAMES_FILE} missing", file=sys.stderr)
        return []

    result = []
    with open(GAMES_FILE, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for row in reader:
            if row.get("date") == date:
                link = row.get("link_to_series", "")
                name = row.get("series_name", "")
                if link:
                    result.append((link, name))
    return result


def detect_live_status(serie_link, dbg=False):
    """
    Determine Live=Yes/No by checking if the Overview page contains a Live-link.
    """
    m = re.search(r"/Overview/([0-9]+)", serie_link)
    if not m:
        return "No"

    sid = m.group(1)
    url = f"https://stats.swehockey.se/ScheduleAndResults/Overview/{sid}"

    cmd = f"curl -L -s {url} | egrep '/ScheduleAndResults/Live/{sid}' | wc -l"
    try:
        out = subprocess.check_output(cmd, shell=True, text=True).strip()
        return "Yes" if out != "0" else "No"
    except Exception as e:
        debug(dbg, f"detect_live_status failed for {serie_link}: {e}")
        return "No"


def load_existing_series(dbg=False):
    """
    Load existing series.csv if it exists and has expected columns.
    Otherwise return empty dict.
    """
    if not os.path.exists(SERIES_FILE):
        debug(dbg, "No existing series.csv found, starting fresh.")
        return {}

    with open(SERIES_FILE, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        fieldnames = reader.fieldnames or []
        fieldnames = [f.strip() for f in fieldnames]

        # Require at least SerieLink & SerieName to consider this usable
        if "SerieLink" not in fieldnames or "SerieName" not in fieldnames:
            debug(dbg, f"Existing series.csv has unsupported header {fieldnames}, ignoring previous content.")
            return {}

        result = {}
        for row in reader:
            link = row.get("SerieLink", "").strip()
            if not link:
                continue
            result[link] = {
                "SerieName": row.get("SerieName", ""),
                "Live": row.get("Live", "No"),
                # If DoneToday missing in old file, treat as "No"
                "DoneToday": row.get("DoneToday", "No")
            }

    debug(dbg, f"Loaded {len(result)} existing series from series.csv.")
    return result


def write_series_file(series_dict, dbg=False):
    os.makedirs(os.path.dirname(SERIES_FILE), exist_ok=True)
    with open(SERIES_FILE, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(HEADER)
        for link, data in sorted(series_dict.items()):
            writer.writerow([
                link,
                data.get("SerieName", ""),
                data.get("Live", "No"),
                data.get("DoneToday", "No")
            ])
    debug(dbg, f"Wrote {len(series_dict)} series rows to {SERIES_FILE}.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--reset-done", action="store_true",
                        help="Reset DoneToday=No for all series")
    parser.add_argument("-dbg", "--debug", action="store_true")
    args = parser.parse_args()

    dbg = args.debug
    date = args.date

    # 1) Load existing series (if usable)
    existing = load_existing_series(dbg)

    # 2) Extract series from today's games
    todays_series = read_games_for_date(date, dbg)
    debug(dbg, f"Found {len(todays_series)} series from games on {date}")

    # Start from existing and update/add
    result = existing.copy()

    for link, name in todays_series:
        if link not in result:
            # New serie -> detect Live, set DoneToday=No
            debug(dbg, f"NEW serie: {link}")
            live = detect_live_status(link, dbg)
            result[link] = {
                "SerieName": name,
                "Live": live,
                "DoneToday": "No"
            }
        else:
            # Existing serie -> refresh name (if changed)
            result[link]["SerieName"] = name

    # 3) Optionally reset DoneToday for ALL series
    if args.reset_done:
        debug(dbg, "Resetting DoneToday=No for all series.")
        for link in result:
            result[link]["DoneToday"] = "No"

    # 4) Write back to CSV
    write_series_file(result, dbg)


if __name__ == "__main__":
    main()

