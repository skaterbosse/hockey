#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
updateSeriesFile.py

Uppdaterar data/series.csv baserat på dagens matcher i data/games.csv.

- Läser data/games.csv och hittar alla serier (link_to_series, series_name) för ett visst datum.
- Läser befintlig data/series.csv (om den finns).
- För varje ny serie som saknas i series.csv:
    * Hämtar serie-Overview-sidan.
    * Avgör om serien har en Live-sida (Live = No/Yes).
    * Om Live = Yes:
         - Hämtar Live-sidan.
         - Om den innehåller GameLinks (javascript:openonlinewindow('/Game/Events/…')):
               Live = "Yes"      (NORMAL serie)
           Annars:
               Live = "YesLight" (LIGHT serie – resultat men inga länkar)
    * Lägger till raden i series.csv med:
         SerieLink;SerieName;Live;DoneToday
         DoneToday sätts till "No" för nya serier.
- Befintliga serier ändras inte.
"""

import csv
import sys
import os
import re
from datetime import datetime
from typing import Dict, List

import requests


BASE_URL = "https://stats.swehockey.se"
SERIES_FILE = "data/series.csv"
SERIES_LIVE_FILE = "data/series_live.csv"
GAMES_FILE = "data/games.csv"


def debug_print(dbg: bool, *args):
    if dbg:
        print("[updateSeriesFile]", *args)

def extract_series_id(series_link: str) -> str:
    """
    Ex:
      https://stats.swehockey.se/ScheduleAndResults/Overview/19863
      -> 19863
    """
    m = re.search(r"/(\d+)$", series_link)
    return m.group(1) if m else ""

def read_games_for_date(target_date: str, dbg: bool = False) -> List[dict]:
    """Läser alla matcher i games.csv för ett visst datum."""
    if not os.path.exists(GAMES_FILE):
        debug_print(dbg, f"{GAMES_FILE} not found, nothing to do.")
        return []

    games = []
    with open(GAMES_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row.get("date") == target_date:
                games.append(row)

    debug_print(dbg, f"Found {len(games)} games for {target_date} in {GAMES_FILE}")
    return games

def load_existing_series(dbg: bool = False) -> Dict[str, dict]:
    """Läser befintlig series.csv som dict {SerieLink: row}."""
    series_map: Dict[str, dict] = {}

    if not os.path.exists(SERIES_FILE):
        debug_print(dbg, f"{SERIES_FILE} does not exist yet.")
        return series_map

    with open(SERIES_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            link = row.get("SerieLink")
            if link:
                series_map[link] = row

    debug_print(dbg, f"Loaded {len(series_map)} existing series from {SERIES_FILE}")
    return series_map

def ensure_absolute_url(link: str) -> str:
    """Säkerställ att en serienlänk är absolut."""
    if link.startswith("http://") or link.startswith("https://"):
        return link
    if link.startswith("/"):
        return BASE_URL + link
    # Om det är något annat konstigt, försök ändå
    return BASE_URL.rstrip("/") + "/" + link.lstrip("/")

def fetch_html(url: str, dbg: bool = False) -> str:
    try:
        debug_print(dbg, f"Fetching {url}")
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.text
    except Exception as e:
        debug_print(dbg, f"ERROR fetching {url}: {e}")
        return ""

def detect_live_type(overview_html: str, serie_link: str, dbg: bool = False) -> str:
    """
    Bestämmer Live-typ för en serie:
      - "No"       : ingen Live-sida
      - "Yes"      : NORMAL (Live med GameLinks)
      - "YesLight" : LIGHT (Live utan GameLinks)

    Logik:
      1) Sök efter /ScheduleAndResults/Live/<id> i overview_html
         → om inget hittas: "No"
      2) Om Live-länk hittas: hämta Live-sidan.
         - Om den innehåller "javascript:openonlinewindow('/Game/Events/"
           eller "/Game/LineUps/": returnera "Yes"
         - Annars: "YesLight"
    """
    # Försök hitta Live-länk i overview_html
    live_match = re.search(r"/ScheduleAndResults/Live/\d+", overview_html)
    if not live_match:
        debug_print(dbg, f"No Live link found for {serie_link} → Live=No")
        return "No"

    live_path = live_match.group(0)
    live_url = ensure_absolute_url(live_path)

    live_html = fetch_html(live_url, dbg=dbg)
    if not live_html:
        # Kan inte avgöra, men vi vet att en Live-länk fanns → anta NORMAL
        debug_print(dbg, f"Could not fetch Live page, assuming Live=Yes for {serie_link}")
        return "Yes"

    # GameLinks för Events eller LineUps
    if "javascript:openonlinewindow('/Game/Events/" in live_html or \
       "javascript:openonlinewindow('/Game/LineUps/" in live_html:
        debug_print(dbg, f"Live page has GameLinks → Live=Yes (NORMAL) for {serie_link}")
        return "Yes"

    # Live-sida utan länkar → LIGHT
    debug_print(dbg, f"Live page has NO gamelinks → Live=YesLight (LIGHT) for {serie_link}")
    return "YesLight"

def write_series_file(series_map: Dict[str, dict], dbg: bool = False) -> None:
    """Skriver tillbaka series.csv med givna rader."""
    os.makedirs(os.path.dirname(SERIES_FILE), exist_ok=True)

    # Se till att vi alltid har samma header
    fieldnames = ["SerieLink", "SerieName", "Live", "DoneToday"]

    with open(SERIES_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, delimiter=";", fieldnames=fieldnames)
        writer.writeheader()
        for link, row in series_map.items():
            out_row = {
                "SerieLink": row.get("SerieLink", link),
                "SerieName": row.get("SerieName", ""),
                "Live": row.get("Live", "No"),
                "DoneToday": row.get("DoneToday", "No"),
            }
            writer.writerow(out_row)

    debug_print(dbg, f"Written {len(series_map)} series rows to {SERIES_FILE}")



    """Skriver en ny series_live.csv file med dagens serier"""
    os.makedirs(os.path.dirname(SERIES_LIVE_FILE), exist_ok=True)

    # Se till att vi alltid har samma header
    fieldnames = ["SerieLink", "SerieName", "Live", "DoneToday"]

    with open(SERIES_LIVE_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, delimiter=";", fieldnames=fieldnames)
        writer.writeheader()
        for link, row in series_live_map.items():
            out_row = {
                "SerieLink": row.get("SerieLink", link),
                "SerieName": row.get("SerieName", ""),
                "Live": row.get("Live", "No"),
                "DoneToday": row.get("DoneToday", "No"),
            }
            writer.writerow(out_row)

    debug_print(dbg, f"Written {len(series_live_map)} series rows to {SERIES_LIVE_FILE}")

def write_series_live_file(series_ids: List[str], dbg: bool = False) -> None:
    os.makedirs(os.path.dirname(SERIES_LIVE_FILE), exist_ok=True)

    with open(SERIES_LIVE_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["series_id", "last_polled", "done_for_today"])

        for sid in sorted(series_ids):
            writer.writerow([sid, "", "No"])

    debug_print(dbg, f"Written {len(series_ids)} rows to {SERIES_LIVE_FILE}")

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    dbg = False
    target_date = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--date" and i + 1 < len(argv):
            target_date = argv[i + 1]
            i += 2
        elif arg == "-dbg":
            dbg = True
            i += 1
        else:
            i += 1

    if target_date is None:
        # Default: dagens datum i systemets timezone
        target_date = datetime.now().strftime("%Y-%m-%d")

    debug_print(dbg, f"Running updateSeriesFile for date {target_date}")

    games = read_games_for_date(target_date, dbg=dbg)
    if not games:
        debug_print(dbg, f"No games for {target_date}, nothing to update.")
        return 0

    # Samla serier från dagens matcher
    todays_series = {}
    for g in games:
        link = g.get("link_to_series", "").strip()
        name = g.get("series_name", "").strip()
        if not link or not name:
            continue
        # Normalisera länk: vi lagrar full URL i series.csv
        full_link = ensure_absolute_url(link)
        todays_series[full_link] = name

    debug_print(dbg, f"Found {len(todays_series)} unique series for {target_date}")

    # Läs befintlig series.csv
    series_map = load_existing_series(dbg=dbg)

    series_ids = []

    for full_link in todays_series.keys():
        sid = extract_series_id(full_link)
        if sid:
            series_ids.append(sid)

    write_series_live_file(series_ids, dbg=dbg)

    return 0

if __name__ == "__main__":
    sys.exit(main())

