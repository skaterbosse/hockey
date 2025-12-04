#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
fetchLiveGameLinks.py
---------------------

Hämtar GameLinks (Events/LineUps) från SweHockey Live-sidor.
Hantera tre situationer:

1) NORMAL-serier:
   - Har riktiga GameLinks i Live-sidan.
   - Vi skriver en rad per GameLink.

2) LIGHT-serier:
   - Har Live-länk i serien.
   - Saknar ALLTID GameLinks.
   - MEN Overview-sidan visar resultat (t.ex "(1-1, 0-2)").
   - Dessa markeras som: NoLinkLight

3) SIMPLE-serier:
   - Saknar både GameLinks OCH resultat.
   - Dessa markeras som: NoLink

Output:
data/live_games.csv
Kolumner:
SerieID;GameID;LinkType;GameLink
"""

import sys
import csv
import re
import requests
from urllib.parse import urljoin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_url(url: str, timeout: int = 20) -> str:
    """
    Fetch a URL and return HTML text or empty string on error.
    """
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"[fetchLiveGameLinks] ERROR fetching {url}: {e}")
        return ""


def extract_gamelinks_from_live(html: str):
    """
    Return a list of (relative_link, linktype).
    Examples of relative links found in Live pages:
      javascript:openonlinewindow('/Game/Events/1017493','')
      javascript:openonlinewindow('/Game/LineUps/1010123','')
    """
    links = []
    # EVENTS
    for m in re.finditer(r"openonlinewindow\('(/Game/Events/(\d+))'", html):
        rel = m.group(1)   # /Game/Events/12345
        links.append((rel, "Events"))
    # LINEUPS
    for m in re.finditer(r"openonlinewindow\('(/Game/LineUps/(\d+))'", html):
        rel = m.group(1)
        links.append((rel, "LineUps"))
    return links


def is_light_series(overview_html: str) -> bool:
    """
    LIGHT-serier har period-siffror '(1-1, 0-2)' på Overview-sidan
    men saknar GameLinks från Live.
    """
    return bool(re.search(r"\(\s*\d+\s*-\s*\d+", overview_html))


def count_games_in_overview(overview_html: str) -> int:
    """
    Räknar antal matcher genom förekomst av class="dateLink".
    Detta är stabilt i SweHockeys HTML.
    """
    return overview_html.count('class="dateLink"')


def ensure_unique(rows):
    """
    Tar bort dubbletter av rader (utan att ändra ordningen).
    Varje rad är en tuple.
    """
    seen = set()
    out = []
    for r in rows:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():

    # -------------------------------------------------------------
    # NEW DEFAULT BEHAVIOR:
    #   If no argument → use data/series.csv
    # -------------------------------------------------------------
    if len(sys.argv) < 2:
        series_file = "data/series.csv"
        print("[fetchLiveGameLinks] No argument provided → using data/series.csv")
    else:
        series_file = sys.argv[1]

    out_file = "data/live_games.csv"

    print(f"[fetchLiveGameLinks] Reading series from: {series_file}")

    # Load series.csv
    series = []
    with open(series_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            series.append(row)

    all_rows = []   # rows for live_games.csv

    for s in series:
        serie_link = s["SerieLink"].strip()
        serie_id = serie_link.rstrip("/").split("/")[-1]
        live_flag = s.get("Live", "").strip().lower()

        # Skip serier som inte har Live = Yes
        if live_flag != "yes":
            continue

        live_url = serie_link.replace("/Overview/", "/Live/")
        print(f"[fetchLiveGameLinks] Serie {serie_id}: fetching Live page {live_url}")

        live_html = fetch_url(live_url)

        # Extract gamelinks
        gamelinks = extract_gamelinks_from_live(live_html)

        if gamelinks:
            # NORMAL-serie
            for rel, typ in gamelinks:
                gid = rel.split("/")[-1]
                full_url = urljoin("https://stats.swehockey.se", rel)
                all_rows.append((serie_id, gid, typ, full_url))
        else:
            # No GameLinks → kan vara SIMPLE eller LIGHT
            print(f"[fetchLiveGameLinks] Serie {serie_id}: no gamelinks, checking Overview…")

            overview_html = fetch_url(serie_link)
            n = count_games_in_overview(overview_html)

            if is_light_series(overview_html):
                linktype = "NoLinkLight"
            else:
                linktype = "NoLink"

            if n == 0:
                all_rows.append((serie_id, "", "", linktype))
            else:
                for _ in range(n):
                    all_rows.append((serie_id, "", "", linktype))

    # Deduplicera
    all_rows = ensure_unique(all_rows)

    # Skriv output
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["SerieID", "GameID", "LinkType", "GameLink"])
        for row in all_rows:
            w.writerow(row)

    print(f"[fetchLiveGameLinks] Wrote {len(all_rows)} rows → {out_file}")


if __name__ == "__main__":
    main()

