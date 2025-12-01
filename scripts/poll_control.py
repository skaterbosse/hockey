#!/usr/bin/env python3
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta

GAMES_FILE = "./data/games.csv"
LIVE_FILE = "./data/live_games.csv"
SERIES_FILE = "./data/series.csv"


def parse_game_id(link):
    if not link:
        return ""
    m = re.search(r"/Game/(Events|LineUps)/(\d+)", link)
    return m.group(2) if m else ""


def load_series():
    """Returns dict of serieID → {link,name,live,done_today,row,index}"""
    result = {}

    if not os.path.exists(SERIES_FILE):
        return result

    with open(SERIES_FILE, "r", encoding="utf-8") as fh:
        reader = csv.reader(fh, delimiter=";")
        rows = list(reader)
        header = rows[0]
        data = rows[1:]

    # expected columns
    col = {name: i for i, name in enumerate(header)}
    if "SerieLink" not in col or "Live" not in col or "DoneToday" not in col:
        raise Exception("series.csv missing required columns")

    for idx, row in enumerate(data):
        link = row[col["SerieLink"]]
        live = row[col["Live"]].lower() == "yes"
        done = row[col["DoneToday"]].lower() == "yes"

        m = re.search(r"/Overview/([0-9]+)", link)
        if not m:
            continue

        sid = m.group(1)
        result[sid] = {
            "index": idx + 1,
            "row": row,
            "link": link,
            "live": live,
            "done": done,
        }
    return result, header


def save_series(series_map, header):
    """Writes modified DoneToday values back."""
    with open(SERIES_FILE, "r", encoding="utf-8") as fh:
        reader = csv.reader(fh, delimiter=";")
        rows = list(reader)

    col = {name: i for i, name in enumerate(rows[0])}

    for sid, info in series_map.items():
        idx = info["index"]
        row = rows[idx]
        row[col["DoneToday"]] = "Yes" if info["done"] else "No"

    with open(SERIES_FILE, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerows(rows)


def load_live_games():
    live_games = {}
    if not os.path.exists(LIVE_FILE):
        return live_games

    with open(LIVE_FILE, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for r in reader:
            sid = r["SerieID"]
            gid = r["GameID"]
            has_link = r["GameLink"] != "NoLink" and gid != ""
            live_games.setdefault(sid, []).append({
                "gid": gid,
                "has_link": has_link
            })
    return live_games


def load_games_for_date(date):
    games = []
    if not os.path.exists(GAMES_FILE):
        return games

    with open(GAMES_FILE, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for row in reader:
            if row["date"] == date:
                games.append(row)
    return games


def within_gamelink_window(start_dt, now):
    return (start_dt - timedelta(hours=2)) <= now <= (start_dt + timedelta(minutes=30))


def within_live_window(start_dt, now):
    return now <= (start_dt + timedelta(hours=3))


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.today().strftime("%Y-%m-%d")
    now = datetime.now()

    series_map, series_header = load_series()
    live_games = load_live_games()
    todays_games = load_games_for_date(date)

    series_to_poll_gl = set()
    matches_lineup = set()
    matches_live = set()
    matches_done = set()

    # ----- Evaluate series/matches -----
    for g in todays_games:
        time = g["time"]
        try:
            start_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        except:
            continue

        # Extract serieID
        m = re.search(r"/Overview/([0-9]+)", g["link_to_series"])
        if not m:
            continue
        sid = m.group(1)

        # Serie must exist in series.csv
        if sid not in series_map:
            continue

        serie = series_map[sid]

        # ❗ If serie is DoneToday → skip everything
        if serie["done"]:
            continue

        # Only poll Live series
        if not serie["live"]:
            continue

        # Extract GameID from result_link
        gid = parse_game_id(g["result_link"])
        status = g["status"].strip()

        # Game-ready set from live_games.csv
        serie_glinks = live_games.get(sid, [])

        has_any_gamelink = any(x["has_link"] for x in serie_glinks)
        missing_gamelink = any((not x["has_link"]) for x in serie_glinks)

        # ----- Decide GameLink polling -----
        if missing_gamelink and within_gamelink_window(start_dt, now):
            series_to_poll_gl.add(sid)

        # ----- Lineup polling -----
        if gid and "Waiting for 1st period" not in status and now < start_dt:
            matches_lineup.add(gid)

        # ----- Live polling -----
        if gid and "Waiting for 1st period" not in status and status != "Final Score":
            if start_dt <= now and within_live_window(start_dt, now):
                matches_live.add(gid)

        # ----- Done -----
        if status == "Final Score" or now > (start_dt + timedelta(hours=3)):
            matches_done.add(gid)

    # ----- Determine series DoneToday -----
    for sid, serie in series_map.items():
        if serie["done"]:
            continue  # Skip already done

        # Get all today's games for the serie
        serie_games = [g for g in todays_games
                       if re.search(r"/Overview/({})".format(sid), g["link_to_series"])]

        if not serie_games:
            continue

        all_done = True
        for g in serie_games:
            status = g["status"].strip()
            time = g["time"]
            start_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
            if not (status == "Final Score" or now > (start_dt + timedelta(hours=3))):
                all_done = False
                break

        if all_done:
            serie["done"] = True

    # Write updates back to series.csv
    save_series(series_map, series_header)

    # Output JSON
    print(json.dumps({
        "series_to_poll_for_gamelinks": sorted(series_to_poll_gl),
        "matches_to_poll_for_lineups": sorted(matches_lineup),
        "matches_to_poll_live": sorted(matches_live),
        "matches_done": sorted(matches_done)
    }, indent=2))


if __name__ == "__main__":
    main()

