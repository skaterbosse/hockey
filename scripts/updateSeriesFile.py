#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
updateSeriesFile.py

Uppdaterar data/series.csv genom att lägga till serier som spelar IDAG.
Avgör automatiskt typ:

  SIMPLE     → ingen Live-sida
  NORMAL     → Live-sida + GameLinks existerar
  LIGHT      → Live-sida + inga GameLinks men resultat visas

Format:
SerieLink;SerieName;Live;DoneToday
där Live ∈ { No, YesLight, Yes }
"""

import sys
import os
import csv
import re
import requests
from bs4 import BeautifulSoup


SERIES_FILE = "data/series.csv"


def fetch_url(url):
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.text
    except:
        return ""


def has_live_link(html):
    return '/ScheduleAndResults/Live/' in html


def overview_has_results(html):
    return bool(re.search(r"\(\s*\d+\s*-\s*\d+", html))


def live_page_has_gamelinks(html):
    return bool(re.search(r"openonlinewindow\('(/Game/(Events|LineUps)/\d+)", html))


def main():
    if "--date" not in sys.argv:
        print("Usage: updateSeriesFile.py --date YYYY-MM-DD")
        sys.exit(1)

    date = sys.argv[sys.argv.index("--date") + 1]
    print(f"[updateSeriesFile] Updating series info for {date}")

    os.makedirs("data", exist_ok=True)

    # Load today's matches
    games_today = []
    with open("data/games.csv", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            if row["date"] == date:
                games_today.append(row)

    print(f"[updateSeriesFile] Found {len(games_today)} matches today")

    # Load existing series
    existing = {}
    if os.path.exists(SERIES_FILE):
        with open(SERIES_FILE, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f, delimiter=";")
            for row in r:
                existing[row["SerieLink"]] = row

    updated = dict(existing)

    for g in games_today:
        serie_link = g["link_to_series"]
        serie_name = g["series_name"]

        if serie_link in updated:
            continue

        ov_html = fetch_url(serie_link)

        if not has_live_link(ov_html):
            live_flag = "No"      # SIMPLE
        else:
            live_url = serie_link.replace("/Overview/", "/Live/")
            live_html = fetch_url(live_url)

            if live_page_has_gamelinks(live_html):
                live_flag = "Yes"         # NORMAL
            else:
                if overview_has_results(ov_html):
                    live_flag = "YesLight"  # LIGHT
                else:
                    live_flag = "No"        # fallback

        updated[serie_link] = {
            "SerieLink": serie_link,
            "SerieName": serie_name,
            "Live": live_flag,
            "DoneToday": "No"
        }

        print(f"[updateSeriesFile] Added: {serie_name} → {live_flag}")

    with open(SERIES_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["SerieLink", "SerieName", "Live", "DoneToday"])
        for row in updated.values():
            w.writerow([row["SerieLink"], row["SerieName"], row["Live"], row["DoneToday"]])

    print(f"[updateSeriesFile] Wrote {len(updated)} series to {SERIES_FILE}")


if __name__ == "__main__":
    main()

