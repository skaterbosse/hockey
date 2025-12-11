#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
updateLightSeriesResults.py

Lättviktigt script för att uppdatera dagens matcher i games.csv med live-info
från en ScheduleAndResults/Live-sida.

- Input:  games.csv (semikolon-separerad)
- Output: uppdaterad games.csv (antingen overwrite eller separat fil)
- Live-källa: HTML-fil (--html-file) eller riktig URL (--live-url / --series-id)

Kolumnformat i games.csv (0-baserade index):

  0: date
  1: time
  2: series_name
  3: link_to_series
  4: admin_host
  5: home_team
  6: away_team
  7: result
  8: result_link
  9: arena
  10: status
  11: iteration_fetched
  12: iterations_total
  13: home_club_list
  14: away_club_list
  15: arena_nbr
  16: PreferedName
  17: Lat
  18: Long

Status-kolumnen fylls enligt:
    status = "<summary>|<standing_parts>"

Exempel:
    "Waiting for 1st period|"
    "3rd period (08:20)|1-1:1-1:0-2"
"""

from __future__ import annotations

import argparse
import hashlib
import html as ihtml
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import urllib.request
import urllib.error


# ---------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------
def normalize_ws(s: str) -> str:
    if not s:
        return ""

    # HTML decode
    s = ihtml.unescape(s)

    # Replace ALL strange spaces with regular
    s = s.replace("\xa0", " ")      # NBSP
    s = s.replace("\u202f", " ")    # narrow NBSP
    s = s.replace("\u2007", " ")    # figure space

    # Normalize regular whitespace
    s = re.sub(r"\s+", " ", s)
    return s.strip()


@dataclass
class LiveGame:
    home_team: str
    away_team: str
    result: str                 # "2 - 3" eller "" om okänt
    status_summary: str         # t.ex. "Waiting for 1st period", "Final Score"
    standing_parts: str = ""    # t.ex. "1-0:3-1:1-0" eller ""


def fetch_live_html(url: str, debug: bool = False) -> str:
    """Hämta HTML för live-sidan online (används i verklig körning, inte i tester)."""
    headers = {"User-Agent": "Mozilla/5.0 (updateLightSeriesResults.py)"}
    req = urllib.request.Request(url, headers=headers)
    if debug:
        print(f"[DBG] Fetching live URL: {url}", file=sys.stderr)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    return data.decode("utf-8", errors="replace")


def load_live_html(html_file: Optional[str],
                   live_url: Optional[str],
                   debug: bool = False) -> str:
    """Läs HTML antingen från fil (offline/test) eller via URL (online)."""
    if html_file:
        p = Path(html_file)
        if not p.exists():
            raise FileNotFoundError(f"HTML file not found: {p}")
        if debug:
            print(f"[DBG] Reading local live HTML: {p}", file=sys.stderr)
        return p.read_text(encoding="utf-8", errors="replace")

    if not live_url:
        raise ValueError("Either --html-file or --live-url/--series-id must be provided")

    return fetch_live_html(live_url, debug=debug)


# ---------------------------------------------------------
# (Gamla) generella live-parsningen – behålls för ev. framtida bruk,
# men används inte i den match-specifika uppdateringen nedan.
# ---------------------------------------------------------
def parse_live_games_from_html(html: str, debug: bool = False) -> List[LiveGame]:
    """
    Tidigare försök att generellt plocka ut matcher från Live-HTML.
    Lämnas kvar för ev. felsökning, men används inte i uppdateringslogiken.
    """
    games: List[LiveGame] = []

    text = html
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</tr>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = ihtml.unescape(text).replace("\xa0", " ")
    lines = [normalize_ws(ln) for ln in text.splitlines()]

    line_pat = re.compile(r"^(.+?)\s+-\s+(.+?):\s*(.+)$")

    for ln in lines:
        if not ln:
            continue
        m = line_pat.match(ln)
        if not m:
            continue

        home = normalize_ws(m.group(1))
        away = normalize_ws(m.group(2))
        rest = m.group(3).strip()

        standing_parts = ""
        m_sp = re.search(r"\(([0-9\-\s,]+)\)", rest)
        if m_sp:
            raw_sp = m_sp.group(1)
            parts = [p.strip() for p in raw_sp.split(",") if p.strip()]
            if parts:
                standing_parts = ":".join(parts)
            rest = (rest[:m_sp.start()] + rest[m_sp.end():]).strip()

        result = ""
        m_res = re.search(r"(\d+)\s*-\s*(\d+)", rest)
        if m_res:
            result = f"{m_res.group(1)} - {m_res.group(2)}"
            rest = re.sub(r"\d+\s*-\s*\d+", "", rest).strip(" ,;-")

        status_summary = rest

        if debug:
            print(f"[DBG] LiveRow: home={home!r}, away={away!r}, "
                  f"result={result!r}, status={status_summary!r}, standing={standing_parts!r}",
                  file=sys.stderr)

        games.append(LiveGame(
            home_team=home,
            away_team=away,
            result=result,
            status_summary=status_summary,
            standing_parts=standing_parts,
        ))

    return games


def compute_live_hash(live_games: List[LiveGame]) -> str:
    """
    Beräkna en stabil hash av live-snapshoten för serien.

    Vi sorterar alla matcher på (home, away) och hashar
    "home|away|result|status|standing_parts" för varje.
    """
    h = hashlib.sha256()
    for g in sorted(live_games,
                    key=lambda g: (g.home_team.lower(), g.away_team.lower())):
        line = f"{g.home_team}|{g.away_team}|{g.result}|{g.status_summary}|{g.standing_parts}"
        h.update(line.encode("utf-8", errors="replace"))
        h.update(b"\n")
    return h.hexdigest()


def write_hash_file(hash_value: str,
                    hash_file: Optional[str],
                    series_id: Optional[str] = None,
                    debug: bool = False) -> None:
    """
    Skriv hash + timestamp till en separat fil.

    Om explicit --hash-file angivits används den. Annars, om series-id finns,
    skrivs den till data/series_live_<series_id>.hash

    Format i filen (en rad):
        <epoch_seconds>;<hash>
    """
    if not hash_file:
        if not series_id:
            return
        hash_dir = Path("data")
        hash_dir.mkdir(parents=True, exist_ok=True)
        hash_file = str(hash_dir / f"series_live_{series_id}.hash")

    ts = int(time.time())
    path = Path(hash_file)
    if debug:
        print(f"[DBG] Writing hash {hash_value} to {path}", file=sys.stderr)

    path.write_text(f"{ts};{hash_value}\n", encoding="utf-8")


# ---------------------------------------------------------
# Games.csv-hantering
# ---------------------------------------------------------

# Kolumnindex enligt formatet du gav
COL_DATE = 0
COL_TIME = 1
COL_SERIES_NAME = 2
COL_LINK_TO_SERIES = 3
COL_ADMIN_HOST = 4
COL_HOME_TEAM = 5
COL_AWAY_TEAM = 6
COL_RESULT = 7
COL_RESULT_LINK = 8
COL_ARENA = 9
COL_STATUS = 10
# Resten används inte i detta script, men vi behåller dem oförändrade


def read_games_csv(path: str) -> Tuple[Optional[List[str]], List[List[str]]]:
    """
    Läs games.csv (semikolonseparerad).

    Returnerar (header, rows) där:
        - header är list[str] eller None om ingen header upptäcktes
        - rows är lista med kolumnlistor (utan headern).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"games file not found: {p}")

    lines = p.read_text(encoding="utf-8").splitlines()
    rows: List[List[str]] = []
    for ln in lines:
        ln = ln.rstrip("\r\n")
        if not ln:
            continue
        cols = ln.split(";")
        rows.append(cols)

    if not rows:
        return None, []

    header: Optional[List[str]] = None
    # En enkel heuristik: första raden börjar med "date" → header
    if rows[0][0].strip().lower() == "date":
        header = rows[0]
        rows = rows[1:]

    return header, rows


def write_games_csv(path: str,
                    header: Optional[List[str]],
                    rows: List[List[str]]) -> None:
    """Skriv tillbaka games.csv med semikolon-separering."""
    out_lines: List[str] = []
    if header is not None:
        out_lines.append(";".join(header))
    for cols in rows:
        out_lines.append(";".join(cols))
    Path(path).write_text("\n".join(out_lines), encoding="utf-8")


# ---------------------------------------------------------
# Match-specifik parsning direkt mot HTML, per rad i games.csv
# ---------------------------------------------------------
def extract_live_info_for_match(html_text: str,
                                home_team: str,
                                away_team: str,
                                debug: bool = False) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Hitta live-info för EN match (home_team, away_team) direkt i HTML:

      - letar upp ett fönster i HTML där både home_team och away_team förekommer
      - i detta fönster:
          * result:   första "X - Y"
          * standing: första "(a-b, c-d, ...)" → "a-b:c-d:..."
          * status:   "Final Score" eller fras med "(mm:ss)" efter bortalaget,
                      t.ex. "3rd period (14:18)" eller
                      "Powerplay (5 on 4) for NSK (04:54)"

    Returnerar (result, status_summary, standing_parts), eller (None, None, None)
    om matchen inte hittas.
    """
    text = ihtml.unescape(html_text).replace("\xa0", " ")

    start = 0
    home_norm = home_team
    away_norm = away_team

    while True:
        idx = text.find(home_norm, start)
        if idx == -1:
            return None, None, None

        # Ta ett fönster runt träffen
        window = text[max(0, idx - 200): idx + 800]

        if away_norm in window:
            break
        else:
            start = idx + len(home_norm)
            continue

    if debug:
        print("--- RAW WINDOW ---", file=sys.stderr)
        print(window[:400], file=sys.stderr)

    # Ta bort HTML-taggar i fönstret
    plain = re.sub(r"<[^>]+>", "", window)
    plain = ihtml.unescape(plain).replace("\xa0", " ")
    plain = re.sub(r"\s+", " ", plain)

    if debug:
        print("--- PLAIN WINDOW ---", file=sys.stderr)
        print(plain, file=sys.stderr)

    h_idx = plain.find(home_norm)
    a_idx = plain.find(away_norm, h_idx + len(home_norm) if h_idx != -1 else 0)

    if h_idx == -1 or a_idx == -1:
        return None, None, None

    # Litet fält efter bortalaget för status
    sub_after = plain[a_idx + len(away_norm): a_idx + len(away_norm) + 140]

    # Resultat: först mellan lagens namn, annars i sub_after
    mid = plain[h_idx + len(home_norm): a_idx]
    result = ""
    m_res = re.search(r"(\d+)\s*-\s*(\d+)", mid)
    if m_res:
        result = f"{m_res.group(1)} - {m_res.group(2)}"
    else:
        m_res = re.search(r"(\d+)\s*-\s*(\d+)", sub_after)
        if m_res:
            result = f"{m_res.group(1)} - {m_res.group(2)}"

    # Periodsiffror t.ex. "(0-0, 4-3, 1-1)"
    standing_parts = ""
    m_sp = re.search(r"\((\d+-\d+(?:,\s*\d+-\d+)*)\)", plain)
    if m_sp:
        raw_sp = m_sp.group(1)
        parts = [p.strip() for p in raw_sp.split(",") if p.strip()]
        standing_parts = ":".join(parts)

    # Status-summary
    status = ""
    after = sub_after

    if "Final Score" in after:
        status = "Final Score"
    else:
        # Försök hitta nåt som slutar med "(mm:ss)"
        m_st = re.search(r"([A-Za-z0-9 /()\-]+?\(\d{2}:\d{2}\))", after)
        if m_st:
            status = m_st.group(1)
        else:
            # fallback – mer generella texter
            for key in [
                "Waiting for 1st period",
                "Waiting for",
                "No GameLink available (not created yet)",
                "No GameLink available",
            ]:
                if key in plain:
                    status = key
                    break

    return (result or None), (status or None), (standing_parts or None)


def update_games_with_live(games_rows: List[List[str]],
                           html_text: str,
                           series_id: Optional[str],
                           debug: bool = False) -> Tuple[int, List[LiveGame]]:
    """
    Uppdatera games_rows in-place utifrån live-info i HTML.

    - För varje rad i games_rows:
        * filtrera på series_id (om angivet) via link_to_series
        * extrahera info med extract_live_info_for_match(...)
        * uppdatera kolumn RESULT (7) och STATUS (10)

    - Statuskolumnen får formatet:
        "<status_summary>|<standing_parts>"

      Exempel:
        "3rd period (14:18)|0-0:4-3:1-1"
        "Final Score|0-0:1-0:1-1"
        "Waiting for 1st period|"

    Returnerar: (antal uppdaterade rader, live_games_list för hash-beräkning).
    """
    updated_count = 0
    live_games_for_hash: List[LiveGame] = []

    for cols in games_rows:
        # Se till att vi har minst 19 kolumner
        if len(cols) < 19:
            cols.extend([""] * (19 - len(cols)))

        link = cols[COL_LINK_TO_SERIES]
        if series_id and series_id not in link:
            # annan serie
            continue

        home = cols[COL_HOME_TEAM]
        away = cols[COL_AWAY_TEAM]

        res, status, standing = extract_live_info_for_match(
            html_text, home, away, debug=debug
        )

        # Hittade inget alls för denna match → hoppa
        if res is None and status is None and standing is None:
            continue

        # Uppdatera resultat om vi har ett
        if res:
            if debug:
                print(f"[DBG] Updating result for {home} - {away} to {res}",
                      file=sys.stderr)
            cols[COL_RESULT] = res

        # Bygg status-strängen "summary|standing_parts"
        status_summary = (status or "").strip()
        standing_parts = (standing or "").strip()

        if standing_parts:
            status_full = f"{status_summary}|{standing_parts}"
        else:
            status_full = f"{status_summary}|"

        if debug:
            print(f"[DBG] Updating status for {home} - {away} to {status_full!r}",
                  file=sys.stderr)

        cols[COL_STATUS] = status_full

        live_games_for_hash.append(
            LiveGame(
                home_team=home,
                away_team=away,
                result=cols[COL_RESULT],
                status_summary=status_summary,
                standing_parts=standing_parts,
            )
        )

        updated_count += 1

    return updated_count, live_games_for_hash


# ---------------------------------------------------------
# CLI
# ---------------------------------------------------------

def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update games.csv with live status/results from "
                    "ScheduleAndResults/Live HTML."
    )
    p.add_argument(
        "-i", "--input-games",
        required=True,
        help="Input games.csv file"
    )
    p.add_argument(
        "-o", "--output-games",
        help="Output games.csv file (default: overwrite input)"
    )
    p.add_argument(
        "--html-file",
        help="Offline HTML file for ScheduleAndResults/Live (for tests)"
    )
    p.add_argument(
        "--live-url",
        help="Live URL (e.g. https://stats.swehockey.se/ScheduleAndResults/Live/19863). "
             "If omitted, derived from --series-id."
    )
    p.add_argument(
        "--series-id",
        help="Series id, used both to derive live URL (if needed) and to filter games.csv rows "
             "to the correct series. Example: 19863"
    )
    p.add_argument(
        "--hash-file",
        help="Optional file path to write live hash+timestamp to. "
             "Default: data/series_live_<series-id>.hash"
    )
    p.add_argument(
        "-dbg", "--debug",
        action="store_true",
        help="Debug logging to stderr"
    )
    args = p.parse_args(argv)

    if not args.html_file and not args.live_url and not args.series_id:
        p.error("You must provide either --html-file or (--live-url or --series-id).")

    # Derive live_url from series-id if needed
    if not args.live_url and args.series_id:
        args.live_url = f"https://stats.swehockey.se/ScheduleAndResults/Live/{args.series_id}"

    return args


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    debug = bool(args.debug)

    # 1) Läs live HTML (fil eller URL)
    html_text = load_live_html(args.html_file, args.live_url, debug=debug)

    # 2) Läs games.csv
    header, rows = read_games_csv(args.input_games)
    if debug:
        print(f"[DBG] Read {len(rows)} game rows from {args.input_games}", file=sys.stderr)

    # 3) Uppdatera games.csv-rows utifrån live-HTML
    updated_count, live_games_for_hash = update_games_with_live(
        rows, html_text, args.series_id, debug=debug
    )

    if debug:
        print(f"[DBG] Updated {updated_count} rows in games.csv", file=sys.stderr)
    else:
        print(f"Updated {updated_count} rows in games.csv.")

    # 4) Skriv tillbaka games.csv
    out_path = args.output_games or args.input_games
    write_games_csv(out_path, header, rows)
    if debug:
        print(f"[DBG] Wrote updated games.csv to {out_path}", file=sys.stderr)

    # 5) Beräkna och skriv hash på live-snapshoten (påverkar inte uppdateringen)
    if (args.series_id or args.hash_file) and live_games_for_hash:
        h = compute_live_hash(live_games_for_hash)
        write_hash_file(h, args.hash_file, series_id=args.series_id, debug=debug)

    return 0


if __name__ == "__main__":
    try:
        rc = main(sys.argv[1:])
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        rc = 1
    sys.exit(rc)

