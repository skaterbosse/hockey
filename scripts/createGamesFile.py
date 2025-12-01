#!/usr/bin/env python3
import argparse
import csv
import os
import sys
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://stats.swehockey.se/ScheduleAndResults/Date/"
OUTPUT_FILE = "data/games_new.csv"

# games.csv header specification
HEADER = [
    "date",
    "time",
    "series_name",
    "link_to_series",
    "admin_host",
    "home_team",
    "away_team",
    "result",
    "result_link",
    "arena",
    "status",
    "iteration_fetched",
    "iterations_total",
    "home_club_list",
    "away_club_list",
    "arena_nbr",
    "PreferedName",
    "Lat",
    "Long"
]

def debug(dbg, *args):
    if dbg:
        print("[createGamesFile]", *args, file=sys.stderr)


def fetch_html(url, dbg=False):
    try:
        debug(dbg, f"Fetching URL: {url}")
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"ERROR: Failed to fetch {url}: {e}", file=sys.stderr)
        return ""


def parse_matches(html, date, dbg=False):
    """Parse Swehockey date page and extract match rows."""
    soup = BeautifulSoup(html, "html.parser")

    rows = soup.select("tr")  # All table rows; matches are inside <tr>

    matches = []

    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue

        # Expected structure:
        # col 0: time
        # col 1: series (with link)
        # col 2: teams ("A - B")
        # col 3: arena
        # col 4: result (possibly with link)

        # Time
        time_text = tds[0].get_text(strip=True)

        # Series + link
        series_a = tds[1].find("a")
        if series_a:
            series_name = series_a.get_text(strip=True)
            link_to_series = "https://stats.swehockey.se" + series_a.get("href")
        else:
            series_name = ""
            link_to_series = ""

        # Teams
        teams_text = tds[2].get_text(" ", strip=True)
        if " - " in teams_text:
            home_team, away_team = teams_text.split(" - ", 1)
        else:
            home_team = teams_text
            away_team = ""

        # Arena
        arena_text = tds[3].get_text(" ", strip=True)

        # Result + link
        result = tds[4].get_text(strip=True)
        result_a = tds[4].find("a")
        if result_a and result_a.get("href", "").startswith("/Game"):
            result_link = "https://stats.swehockey.se" + result_a["href"]
        else:
            result_link = ""

        # Build row dict
        row = {
            "date": date,
            "time": time_text,
            "series_name": series_name,
            "link_to_series": link_to_series,
            "admin_host": "",
            "home_team": home_team,
            "away_team": away_team,
            "result": result,
            "result_link": result_link,
            "arena": arena_text,
            "status": "0",
            "iteration_fetched": "0",
            "iterations_total": "0",
            "home_club_list": "",
            "away_club_list": "",
            "arena_nbr": "",
            "PreferedName": arena_text,
            "Lat": "",
            "Long": "",
        }

        matches.append(row)

    debug(dbg, f"Found {len(matches)} matches")
    return matches


def write_output(matches, dbg=False):
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(HEADER)
        for m in matches:
            writer.writerow([m.get(col, "") for col in HEADER])

    debug(dbg, f"Wrote {len(matches)} rows to {OUTPUT_FILE}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Date YYYY-MM-DD")
    parser.add_argument("-dbg", "--debug", action="store_true")
    args = parser.parse_args()

    date = args.date
    dbg = args.debug

    url = BASE_URL + date
    html = fetch_html(url, dbg)

    if not html.strip():
        print("WARNING: No HTML returned, writing empty output file.", file=sys.stderr)
        write_output([], dbg)
        return

    matches = parse_matches(html, date, dbg)
    write_output(matches, dbg)


if __name__ == "__main__":

