#!/usr/bin/env python3
import sys
import argparse
import requests
from bs4 import BeautifulSoup
import csv
import re
import os

DATA_FILE = "./data/series.csv"
OUTPUT_FILE = "./data/live_games.csv"

def extract_game_id(js):
    """
    Extract GameID from javascript:openonlinewindow('/Game/Events/123456','')
    """
    m = re.search(r"/Game/(Events|LineUps)/(\d+)", js)
    if not m:
        return "", ""
    link_type = m.group(1)
    game_id = m.group(2)
    return link_type, game_id


def get_live_page(serie_id):
    url = f"https://stats.swehockey.se/ScheduleAndResults/Live/{serie_id}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.text


def parse_live_page(html, serie_id):
    soup = BeautifulSoup(html, "html.parser")

    matches = soup.find_all("td", class_="TodaysGamesGame")

    results = []
    seen = set()

    for m in matches:
        # Try to find a GameLink in <a> tag
        alink = m.find("a", href=True)
        game_id = ""
        link_type = ""
        link_url = ""

        if alink and "openonlinewindow" in alink["href"]:
            link_type, game_id = extract_game_id(alink["href"])
            if game_id:
                link_url = f"https://stats.swehockey.se/Game/{link_type}/{game_id}"

        # Deduplicate
        key = (serie_id, game_id if game_id else f"NOLINK-{len(results)}")
        if key in seen:
            continue
        seen.add(key)

        if game_id:
            results.append([serie_id, game_id, link_type, link_url])
        else:
            results.append([serie_id, "", "", "NoLink"])

    return results


def load_series_ids():
    if not os.path.exists(DATA_FILE):
        print(f"ERROR: {DATA_FILE} not found", file=sys.stderr)
        return []

    serie_ids = []
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for row in reader:
            if row.get("Live", "").strip().lower() == "yes":
                link = row["SerieLink"]
                m = re.search(r"/ScheduleAndResults/Overview/(\d+)", link)
                if m:
                    serie_ids.append(m.group(1))
    return serie_ids


def write_output(rows):
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["SerieID", "GameID", "LinkType", "GameLink"])
        w.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sid", help="Fetch only for specific SerieID")
    args = parser.parse_args()

    if args.sid:
        series = [args.sid]
    else:
        series = load_series_ids()

    all_rows = []

    for sid in series:
        try:
            html = get_live_page(sid)
            rows = parse_live_page(html, sid)
            all_rows.extend(rows)
        except Exception as e:
            print(f"Error fetching SerieID={sid}: {e}", file=sys.stderr)

    write_output(all_rows)


if __name__ == "__main__":
    main()

