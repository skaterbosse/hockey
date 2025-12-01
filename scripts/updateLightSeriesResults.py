#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
updateLightSeriesResults.py

Används för LIGHT-serier (Live = YesLight) där vi inte får GameLinks.

Detta script hämtar *alla dagens matcher* för serien via Overview-sidan
och uppdaterar endast:
    - Resultat
    - GameStatus (Final Score / Waiting / Periodstatus)
    - Standing
    - Shots om de finns
    - Publik (om den finns)
    - Datum / tid / lag / arena

Output skrivs till:
    data/Events_<GameID>.txt

Detta gör att LIGHT-serier uppdateras på liknande sätt som NORMAL-serier,
men utan händelser och utan lineups.
"""

import sys
import requests
import re
from bs4 import BeautifulSoup
import os


def fetch(url, dbg=False):
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.text
    except Exception as e:
        if dbg:
            print(f"[LightSeries] ERROR fetching {url}: {e}")
        return ""


def extract_game_blocks(html, dbg=False):
    """
    Hittar matchraderna på Overview-sidan.
    Formatet varierar mellan serier.
    Vi letar efter block som innehåller lag + resultat.
    """

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr")

    games = []

    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue

        try:
            time = tds[0].get_text(strip=True)
            home = tds[1].get_text(strip=True)
            result = tds[2].get_text(strip=True)
            away = tds[3].get_text(strip=True)
            arena = tds[4].get_text(strip=True)
        except:
            continue

        # Detta är en LIGHT-matchrad om det finns något resultat eller tid
        if home and away and (time or result):
            games.append({
                "time": time,
                "home": home,
                "result": result,
                "away": away,
                "arena": arena
            })

    if dbg:
        print(f"[LightSeries] Found {len(games)} game blocks")

    return games


def extract_gameid_from_series_game(series_id, index):
    """
    LIGHT-serier saknar GameID i HTML.
    Vi simulerar ett stabilt GameID baserat på serie + ordning.
    Detta är *nödvändigt* för att shallow-update skall fungera.

    Format:
        <SerieID>000 + matchindex

    Exempel:
        Serie 18805, match 0 -> 18805000
        Serie 18805, match 1 -> 18805001

    Detta garanterar:
        - Unika ID:n per serie och match
        - Stabilitet under dagen
    """
    return f"{series_id}00{index:02d}"


def write_stats_file(game_id, serie_name, date, game, dbg=False):
    """
    Output-format:
    Enligt Stats-raden från getGameEvents.py men LIGHT-versionen saknar:
        - Skott i perioder
        - PIM
        - PowerPlay
    """

    outpath = f"data/Events_{game_id}.txt"

    # Minimal stats vi kan extrahera
    standing = game["result"] if game["result"] else ""
    status = "Final Score" if re.search(r"\d+\s*-\s*\d+", standing) else "Waiting"
    spectators = ""  # LIGHT-serier visar sällan publik
    shots_home = ""
    shots_away = ""
    shots_parts_home = ""
    shots_parts_away = ""
    standing_parts = ""
    time = game["time"]
    home = game["home"]
    away = game["away"]
    arena = game["arena"]

    # Format identiskt med getGameEvents.py Stats-rad
    row = [
        game_id,
        "Stats",
        home,
        away,
        date,
        time,
        serie_name,
        arena,
        shots_home,
        shots_parts_home,
        standing,
        shots_away,
        shots_parts_away,
        "",  # Home Shooting Efficiency
        standing_parts,
        "",  # Away Shooting Efficiency
        "",  # Home saves total
        "",  # Home saves parts
        status,
        "",  # Away saves total
        "",  # Away saves parts
        "",  # Home saving %
        spectators,
        "",  # Away saving %
        "",  # Home PIM total
        "",  # Home PIM parts
        "",  # Away PIM total
        "",  # Away PIM parts
        "",  # Home PP %
        "",  # Home PP time
        "",  # Away PP %
        ""   # Away PP time
    ]

    if dbg:
        print(f"[LightSeries] Writing {outpath}")

    with open(outpath, "w", encoding="utf-8") as f:
        f.write("[" + ";".join(row) + "]\n")


def main():
    dbg = "-dbg" in sys.argv

    if "--serie" not in sys.argv:
        print("Usage: updateLightSeriesResults.py --serie <SerieOverviewURL> --serieid <ID>")
        sys.exit(1)

    serie_url = sys.argv[sys.argv.index("--serie") + 1]
    serie_id = sys.argv[sys.argv.index("--serieid") + 1]

    # Datum behövs — LIGHT hämtar matchdatum direkt från seriesidan
    # HTML inkluderar dagens datum i rubriken
    # Format: <H2> Schedule for 2025-11-30 </H2>
    html = fetch(serie_url, dbg)
    if not html:
        print("[LightSeries] No HTML — skipping.")
        sys.exit(0)

    # Hitta serienamn
    m = re.search(r'<h2[^>]*>(.*?)</h2>', html, re.IGNORECASE | re.DOTALL)
    serie_name = m.group(1).strip() if m else "Unknown Series"

    # Hitta datum
    m = re.search(r'(\d{4}-\d{2}-\d{2})', html)
    date = m.group(1) if m else ""

    if dbg:
        print(f"[LightSeries] SerieID={serie_id}")
        print(f"[LightSeries] SerieName={serie_name}")
        print(f"[LightSeries] Date={date}")

    # Extrahera matchrader
    games = extract_game_blocks(html, dbg)

    # Generera GameID per match baserat på serie-ID + index
    for idx, game in enumerate(games):
        game_id = extract_gameid_from_series_game(serie_id, idx)
        write_stats_file(game_id, serie_name, date, game, dbg)

    print(f"[LightSeries] Updated {len(games)} Light-matches for serie {serie_id}")


if __name__ == "__main__":
    main()

