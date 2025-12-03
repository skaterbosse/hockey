#!/usr/bin/env python3
import csv
import sys
import os
from datetime import datetime, timedelta
import subprocess
import pytz

GAMES_FILE = "data/games.csv"
LIVE_FILE = "data/live_games.csv"
TZ = pytz.timezone("Europe/Stockholm")

def load_games(date_str):
    games = []
    with open(GAMES_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row["date"] == date_str:
                games.append(row)
    return games


def load_live_links():
    links = {}
    with open(LIVE_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            gid = row.get("GameID", "")
            if gid:
                links[gid] = row
    return links


def parse_time(date_str, time_str):
    dt_str = f"{date_str} {time_str}"
    return TZ.localize(datetime.strptime(dt_str, "%Y-%m-%d %H:%M"))


def should_poll(now, start):
    """Returns True only when within allowed window:
       - 1h45m before start
       - until 3h15m after start
    """
    pre = start - timedelta(hours=1, minutes=45)
    post = start + timedelta(hours=3, minutes=15)
    return pre <= now <= post


def main():
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    now = datetime.now(TZ)

    print(f"[pollNormalSeries] Today = {today}")
    print(f"[pollNormalSeries] Now(SE) = {now}")

    games = load_games(today)
    links = load_live_links()

    poll_count = 0

    for row in games:
        # Extract GameID from result_link (format: /Game/Events/<ID>)
        result_link = row.get("result_link", "")
        if not result_link.startswith("/Game/Events/"):
            continue
        game_id = result_link.replace("/Game/Events/", "").strip()

        if game_id not in links:
            continue

        linkinfo = links[game_id]
        if linkinfo.get("LinkType") != "Events":
            continue

        # Parse match start
        try:
            start = parse_time(today, row["time"])
        except Exception as e:
            print(f"[pollNormalSeries] Skipping game {game_id}, invalid time: {e}")
            continue

        # Check Poll Control
        if not should_poll(now, start):
            continue

        # Skip if already Final
        status = row.get("status", "")
        if "Final Score" in status:
            continue

        print(f"[pollNormalSeries] Polling GAME {game_id}")

        # Run getGameEvents for this match ID
        cmd = ["python3", "scripts/getGameEvents.py", "-gid", game_id, "-dbg"]
        try:
            subprocess.run(cmd, check=False)
        except Exception as e:
            print(f"[pollNormalSeries] ERROR polling {game_id}: {e}")

        poll_count += 1

    print(f"[pollNormalSeries] Total matches polled: {poll_count}")


if __name__ == "__main__":
    main()

