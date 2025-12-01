#!/usr/bin/env python3
import argparse
import csv
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

DATA_DIR = "./data"
GAMES_FILE = os.path.join(DATA_DIR, "games.csv")

# Column names in games.csv
COL_DATE = "date"
COL_TIME = "time"
COL_RESULT = "result"
COL_RESULT_LINK = "result_link"
COL_STATUS = "status"
COL_ITER_FETCHED = "iteration_fetched"
COL_ITER_TOTAL = "iterations_total"


def debug(enabled: bool, *args):
    if enabled:
        print("[updateGamesShallow]", *args, file=sys.stderr)


def parse_game_id_from_link(link: str) -> str:
    m = re.search(r"/Game/(Events|LineUps)/(\d+)", link)
    if not m:
        return ""
    return m.group(2)


def call_get_game_events(game_id: str, dbg: bool = False) -> str:
    cmd = [sys.executable, "getGameEvents.py", "-gid", game_id]
    debug(dbg, "Calling:", " ".join(cmd))

    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return p.stdout
    except Exception as e:
        debug(dbg, f"Error executing getGameEvents.py: {e}")
        return ""


def extract_stats_line(output: str) -> str:
    for line in output.splitlines():
        if ";Stats;" in line:
            return line.strip()
    return ""


def parse_stats_line(stats_line: str):
    parts = stats_line.split(";")
    if len(parts) < 20:
        return {}

    return {
        "Standing": parts[10].strip(),
        "GameStatus": parts[18].strip(),
    }


def within_poll_window(date_str: str, time_str: str, now: datetime, dbg=False) -> bool:
    try:
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except:
        return False

    start_window = start_dt - timedelta(hours=2)
    end_window = start_dt + timedelta(hours=3)

    return start_window <= now <= end_window


def load_gid_list(args, dbg):
    """Returns a set of gameIDs this script should update."""
    gids = set()

    if args.gid_list:
        for part in args.gid_list.split(","):
            pid = part.strip()
            if pid.isdigit():
                gids.add(pid)

    if args.gid_file:
        try:
            with open(args.gid_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line.isdigit():
                        gids.add(line)
        except Exception as e:
            debug(dbg, f"Could not read gid-file: {e}")

    return gids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--date", help="Date (YYYY-MM-DD)")
    parser.add_argument("--gid-list", help="Comma-separated GameIDs to update")
    parser.add_argument("--gid-file", help="File with GameIDs to update")
    parser.add_argument("-dbg", "--debug", action="store_true")
    args = parser.parse_args()
    dbg = args.debug

    target_date = args.date or datetime.today().strftime("%Y-%m-%d")
    target_gids = load_gid_list(args, dbg)

    if target_gids:
        debug(dbg, f"Filtering for GameIDs: {sorted(target_gids)}")

    if not os.path.exists(GAMES_FILE):
        print(f"ERROR: {GAMES_FILE} missing", file=sys.stderr)
        sys.exit(1)

    # Load games.csv
    with open(GAMES_FILE, "r", encoding="utf-8") as fh:
        reader = csv.reader(fh, delimiter=";")
        rows = list(reader)

    header = rows[0]
    data_rows = rows[1:]

    col = {name: i for i, name in enumerate(header)}

    for c in [COL_DATE, COL_TIME, COL_RESULT_LINK, COL_STATUS, COL_ITER_FETCHED, COL_ITER_TOTAL]:
        if c not in col:
            print(f"ERROR: Missing column {c} in games.csv", file=sys.stderr)
            sys.exit(1)

    now = datetime.now()
    updated = False

    for row in data_rows:
        # Fix uneven rows
        if len(row) < len(header):
            row.extend([""] * (len(header) - len(row)))

        date = row[col[COL_DATE]].strip()
        time = row

