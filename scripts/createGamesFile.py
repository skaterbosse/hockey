#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
createGamesFile.py

Hämtar matcher för ett specifikt datum via GamesByDate.
Skriver output till: data/games_new.csv
"""

import sys
import csv
import requests
from bs4 import BeautifulSoup


def fetch_gamesbydate(date):
    url = f"https://stats.swehockey.se/GamesByDate/{date}/ByTime/null"
    print(f"[createGamesFile] Fetching URL: {url}")

    r = requests.get(url, timeout=20)
    if r.status_code != 200:
        raise Exception(f"Failed fetch: {r.status_code}")
    return r.text


def parse_games(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr")

    games = []
    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 8:
            continue

        # Extract columns
        time = tds[0].get_text(strip=True)
        series = tds[1].get_text(strip=True)
        link = tds[1].find("a", href=True)["href"]
        home = tds[2].get_text(strip=True)
        away = tds[4].get_text(strip=True)
        result = tds[5].get_text(strip=True)
        arena = tds[7].get_text(strip=True)

        games.append({
            "time": time,
            "series_name": series,
            "link_to_series": link,
            "home_team": home,
            "away_team": away,
            "result": result,
            "arena": arena,
        })

    return games


def main():
    if "--date" not in sys.argv:
        print("Usage: createGamesFile.py --date YYYY-MM-DD")
        sys.exit(1)

    date = sys.argv[sys.argv.index("--date") + 1]
    dbg = "-dbg" in sys.argv

    try:
        html = fetch_gamesbydate(date)
    except Exception as e:
        print(f"[createGamesFile] ERROR: {e}")
        html = ""

    if not html:
        print("[createGamesFile] WARNING: Empty HTML, writing empty file.")
        with open("data/games_new.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["date", "time", "series_name", "link_to_series",
                        "home_team", "away_team", "result", "arena"])
        sys.exit(0)

    games = parse_games(html)

    with open("data/games_new.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["date", "time", "series_name", "link_to_series",
                    "home_team", "away_team", "result", "arena"])

        for g in games:
            w.writerow([date, g["time"], g["series_name"],
                        g["link_to_series"], g["home_team"],
                        g["away_team"], g["result"], g["arena"]])

    print(f"[createGamesFile] Wrote {len(games)} matches → data/games_new.csv")


if __name__ == "__main__":
    main()

