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
  8: result_link   (GameLink, t.ex. /Game/Events/1087719)
  9: arena
  10: status       (Summary|Parts)
  11: iteration_fetched
  12: iterations_total
  13: home_club_list
  14: away_club_list
  15: arena_nbr
  16: PreferedName
  17: Lat
  18: Long
"""

from __future__ import annotations

import argparse
import hashlib
import html as ihtml
import json
import re
import sys
import time
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import urllib.request


# ---------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------
DEBUG_TIMING = os.getenv("LS_TIMING") == "1"

def _ts():
    return time.perf_counter()

def _dt_ms(t0):
    return int((time.perf_counter() - t0) * 1000)

def log(msg):
    print(msg, flush=True)

def dbg(msg):
    if DEBUG_TIMING:
        print(f"[TIMING] {msg}", flush=True)

def normalize_ws(s: str) -> str:
    if not s:
        return ""
    s = ihtml.unescape(s)

    # Replace strange spaces with regular space
    s = s.replace("\xa0", " ")      # NBSP
    s = s.replace("\u202f", " ")    # narrow NBSP
    s = s.replace("\u2007", " ")    # figure space

    s = re.sub(r"\s+", " ", s)
    return s.strip()


@dataclass
class LiveGame:
    home_team: str
    away_team: str
    result: str
    status_summary: str
    standing_parts: str = ""
    game_link: str = ""

@dataclass
class LiveGameStatus:
    home_team: str
    away_team: str
    game_link: Optional[str]
    status: Optional[str]
    has_gamelink: bool
    has_final_score: bool

def _is_final_score_status(status: Optional[str]) -> bool:
    if not status:
        return False
    return status.strip() == "Final Score"

def fetch_live_html(url: str, debug: bool = False) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (updateLightSeriesResults.py)"}
    req = urllib.request.Request(url, headers=headers)
    if debug:
        print(f"[DBG] Fetching live URL: {url}", file=sys.stderr)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    return data.decode("utf-8", errors="replace")

def build_live_series_status(games_rows: List[List[str]],
                             series_id: str) -> List[LiveGameStatus]:
    statuses: List[LiveGameStatus] = []

    for cols in games_rows:
        if len(cols) < 19:
            continue

        link_to_series = cols[COL_LINK_TO_SERIES]
        if series_id not in link_to_series:
            continue

        home = cols[COL_HOME_TEAM].strip()
        away = cols[COL_AWAY_TEAM].strip()

        game_link = cols[COL_RESULT_LINK].strip() or None

        status_field = cols[COL_STATUS].strip()
        summary = None
        if status_field:
            summary = status_field.split("|", 1)[0].strip() or None

        statuses.append(
            LiveGameStatus(
                home_team=home,
                away_team=away,
                game_link=game_link,
                status=summary,
                has_gamelink=bool(game_link),
                has_final_score=_is_final_score_status(summary),
            )
        )

    return statuses

def write_series_status_json(series_id: str,
                             statuses: List[LiveGameStatus],
                             output_path: str) -> None:
    payload = {
        "series_id": series_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "games": [
            {
                "home": s.home_team,
                "away": s.away_team,
                "game_link": s.game_link,
                "status": s.status,
                "has_gamelink": s.has_gamelink,
                "has_final_score": s.has_final_score,
            }
            for s in statuses
        ],
    }

    Path(output_path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

def load_live_html(html_file: Optional[str],
                   live_url: Optional[str],
                   debug: bool = False) -> str:
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


def compute_live_hash(live_games: List[LiveGame]) -> str:
    h = hashlib.sha256()
    for g in sorted(live_games, key=lambda x: (x.home_team.lower(), x.away_team.lower())):
        line = f"{g.home_team}|{g.away_team}|{g.result}|{g.status_summary}|{g.standing_parts}|{g.game_link}"
        h.update(line.encode("utf-8", errors="replace"))
        h.update(b"\n")
    return h.hexdigest()


def write_hash_file(hash_value: str,
                    hash_file: Optional[str],
                    series_id: Optional[str] = None,
                    debug: bool = False) -> None:
    if not hash_file:
        if not series_id:
            return
        hash_dir = Path("data")
        hash_dir.mkdir(parents=True, exist_ok=True)
        hash_file = str(hash_dir / f"series_live_{series_id}.hash")

    ts = int(time.time())
    path = Path(hash_file)
    if debug:
        print(f"[DBG] Wrote hash {hash_value} to {path}", file=sys.stderr)
    path.write_text(f"{ts};{hash_value}\n", encoding="utf-8")


# ---------------------------------------------------------
# Games.csv-hantering
# ---------------------------------------------------------
COL_DATE = 0
COL_TIME = 1
COL_SERIES_NAME = 2
COL_LINK_TO_SERIES = 3
COL_ADMIN_HOST = 4
COL_HOME_TEAM = 5
COL_AWAY_TEAM = 6
COL_RESULT = 7
COL_RESULT_LINK = 8   # GameLink
COL_ARENA = 9
COL_STATUS = 10       # Summary|Parts


def read_games_csv(path: str) -> Tuple[Optional[List[str]], List[List[str]]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"games file not found: {p}")

    lines = p.read_text(encoding="utf-8").splitlines()
    rows: List[List[str]] = []
    for ln in lines:
        ln = ln.rstrip("\r\n")
        if not ln:
            continue
        rows.append(ln.split(";"))

    if not rows:
        return None, []

    header: Optional[List[str]] = None
    if rows[0][0].strip().lower() == "date":
        header = rows[0]
        rows = rows[1:]

    return header, rows


def write_games_csv(path: str,
                    header: Optional[List[str]],
                    rows: List[List[str]]) -> None:
    out_lines: List[str] = []
    if header is not None:
        out_lines.append(";".join(header))
    for cols in rows:
        out_lines.append(";".join(cols))
    Path(path).write_text("\n".join(out_lines), encoding="utf-8")


# ---------------------------------------------------------
# Live-parsning per match (minimal men robust)
# ---------------------------------------------------------
_STATUS_MARKERS = [
    # period
    "1st period", "2nd period", "3rd period",
    # finals
    "Final Score", "Game Finished",
    # waiting
    "Waiting for 1st period", "Waiting for",
    # special states (håll flexibel)
    "Overtime", "OT",
    "GWS", "Shootout",
    # event-ish
    "Powerplay", "Four on Four",
]

_EVENT_MARKERS = [
    "Powerplay",
    "Four on Four",
    "Overtime",
    "OT",
    "GWS",
    "Shootout",
]


def _clean_summary(summary: str) -> str:
    """
    Tar bort skräp-prefix i TC3 (v5) där summary kan börja med t.ex:
      ' 1-0) IK Göta Powerplay (5 on 4) for NSK (04:54)'
      ' 2-0, 1-0) Brinkens IF Four on Four (05:55)'

    Vi letar efter första kända statusmarkör och klipper därifrån.
    Om ingen markör hittas lämnar vi strängen som den är (för flexibilitet).
    """
    if not summary:
        return ""

    s = summary.strip()

    # Hitta första förekomst av någon känd markör (case-insensitive)
    lower = s.lower()
    best_idx: Optional[int] = None
    for m in _STATUS_MARKERS:
        i = lower.find(m.lower())
        if i != -1 and (best_idx is None or i < best_idx):
            best_idx = i

    if best_idx is not None:
        s = s[best_idx:].strip()

    return s


def _extract_period_or_ot_status(plain: str) -> Optional[str]:
    """
    Returnerar status med tid om den finns i plain-text:
      - "1st period (00:00)", "3rd period (10:54)"
      - "Overtime (02:13)"  (vanlig OT)
      - "Overtime 1 (02:13)" / "Overtime 2 ..." (numrerad OT i matchserier)
    """
    if not plain:
        return None

    # Perioder
    m_period = re.search(r"(\d+(st|nd|rd|th))\s+period\s*\(\d{2}:\d{2}\)", plain)
    if m_period:
        return m_period.group(0)

    # Overtime (numrerad eller onumrerad)
    m_ot = re.search(r"Overtime(?:\s+(\d+))?\s*\(\d{2}:\d{2}\)", plain)
    if m_ot:
        # Behåll "Overtime 1" om numret finns, annars "Overtime"
        return m_ot.group(0)

    return None

def emit_games_json(live_games: List[LiveGame]) -> None:
    """
    Emit minimal JSON for wrapper scripts.

    Format:
    [
      {"gameLink": "/Game/Events/1087719", "status": "Final Score"},
      ...
    ]
    """
    out = []
    for g in live_games:
        if not g.game_link:
            continue
        out.append({
            "gameLink": g.game_link,
            "status": g.status_summary
        })

    print(json.dumps(out, ensure_ascii=False))

def extract_live_info_for_match(html_text: str,
                                home_team: str,
                                away_team: str,
                                debug: bool = False) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Returnerar (result, summary, parts, game_link) för matchen, eller (None,...)
    """
    text = ihtml.unescape(html_text).replace("\xa0", " ")

    start = 0
    home_norm = home_team
    away_norm = away_team

    while True:
        idx = text.find(home_norm, start)
        if idx == -1:
            return None, None, None, None

        window = text[max(0, idx - 250): idx + 1200]

        if away_norm in window:
            # välj första relevanta träffen
            break

        start = idx + len(home_norm)

    if debug:
        print("--- RAW WINDOW ---", file=sys.stderr)
        print(window[:400], file=sys.stderr)

    # Plocka GameLink (kan finnas även när resultat saknas)
    m_link = re.search(r"(/Game/Events/\d+)", window)
    game_link = m_link.group(1) if m_link else None

    # Gör plain text i fönstret
    plain = re.sub(r"<[^>]+>", "", window)
    plain = normalize_ws(plain)

    if debug:
        print("--- PLAIN WINDOW ---", file=sys.stderr)
        print(plain[:220], file=sys.stderr)

    h_idx = plain.find(home_norm)
    a_idx = plain.find(away_norm, h_idx + len(home_norm) if h_idx != -1 else 0)
    if h_idx == -1 or a_idx == -1:
        return None, None, None, game_link

    # Substring efter bortalag för status (där finns ofta "Final Score", "3rd period (..)", "Powerplay ... (..)")
    after = plain[a_idx + len(away_norm): a_idx + len(away_norm) + 220]
    after = after.strip()

    # Resultat: välj "huvudresultatet" mellan home och away om det finns.
    mid = plain[h_idx + len(home_norm): a_idx]
    result: Optional[str] = None
    m_res = re.search(r"\b(\d+)\s*-\s*(\d+)\b", mid)
    if m_res:
        result = f"{m_res.group(1)} - {m_res.group(2)}"
    else:
        # fallback: leta i början av after (om layouten är annorlunda)
        m_res2 = re.search(r"\b(\d+)\s*-\s*(\d+)\b", after)
        if m_res2:
            result = f"{m_res2.group(1)} - {m_res2.group(2)}"

    # Period-delar: "(0-0, 4-3, 1-1)" -> "0-0:4-3:1-1"
    parts: Optional[str] = None
    m_parts = re.search(r"\((\d+-\d+(?:,\s*\d+-\d+)*)\)", plain)
    if m_parts:
        raw = m_parts.group(1)
        ps = [p.strip() for p in raw.split(",") if p.strip()]
        parts = ":".join(ps) if ps else None

    # Summary:
    summary: Optional[str] = None

    # Hämta period/OT-status från hela plain (inte bara "after")
    period_or_ot_status = _extract_period_or_ot_status(
    normalize_ws(re.sub(r"<[^>]+>", "", window))
    )

    # 1) Absoluta statusar
    for key in ("Final Score", "Game Finished"):
        if key in after:
            summary = key
            break

    # 2) Waiting
    if not summary:
        for key in ("Waiting for 1st period", "Waiting for"):
            if key in after:
                summary = key
                break

    # 3) Eventstatus (powerplay/four-on-four) – bara om vi inte redan har summary
    if not summary:
        m_event = re.search(
            r"(Powerplay \(.*?\) for .*?\(\d{2}:\d{2}\)|Four on Four \(\d{2}:\d{2}\))",
            after
        )
        if m_event:
            summary = m_event.group(1)

    if summary:
        summary = _clean_summary(summary)

    # --- TC3 FIX: period/OT ska vinna över event om event är Powerplay/Four on Four ---
    # (då vill vi ha "3rd period (..)" istället för event-texten)
    # Period / OT ska ALLTID vinna över event
    if period_or_ot_status:
        if summary and re.match(r"^(Powerplay|Four on Four)\b", summary):
            summary = period_or_ot_status
        elif not summary:
            summary = period_or_ot_status

    # Om vi ännu inte har summary, använd period/OT-status (för fall där efter saknar den)
    if not summary and period_or_ot_status:
        summary = period_or_ot_status

    return result, summary, parts, game_link


def update_games_with_live(games_rows: List[List[str]],
                           html_text: str,
                           series_id: Optional[str],
                           debug: bool = False) -> Tuple[int, List[LiveGame]]:
    updated_count = 0
    live_games_for_hash: List[LiveGame] = []

    for cols in games_rows:
        if len(cols) < 19:
            cols.extend([""] * (19 - len(cols)))

        link_to_series = cols[COL_LINK_TO_SERIES]
        if series_id and series_id not in link_to_series:
            continue

        home = cols[COL_HOME_TEAM]
        away = cols[COL_AWAY_TEAM]

        res, summary, parts, game_link = extract_live_info_for_match(
            html_text, home, away, debug=debug
        )

        if debug:
            print(
                f"[DBG] Parsed: {home} - {away} | {res} | {summary or ''} | {parts or ''} | {game_link or 'None'}",
                file=sys.stderr
            )

        # Om vi inte hittade någonting relevant: hoppa
        if res is None and summary is None and parts is None and game_link is None:
            continue

        # GameLink (kol 9/result_link) – sätt om vi hittade en
        if game_link:
            cols[COL_RESULT_LINK] = game_link

        # Resultat (kol 8/result) – bara om det finns
        if res:
            cols[COL_RESULT] = res

        summary_s = (summary or "").strip()
        parts_s = (parts or "").strip()

        # Status (kol 11/status) – alltid summary|parts (summary kan vara tom)
        # Status skrivs BARA om GameLink finns
        if cols[COL_RESULT_LINK]:
            cols[COL_STATUS] = f"{summary_s}|{parts_s}" if parts_s else f"{summary_s}|"
        else:
            # Ingen GameLink → status ska vara tom
            cols[COL_STATUS] = ""
            summary_s = ""
            parts_s = ""

        live_games_for_hash.append(
            LiveGame(
                home_team=home,
                away_team=away,
                result=cols[COL_RESULT],
                status_summary=summary_s,
                standing_parts=parts_s,
                game_link=cols[COL_RESULT_LINK],
            )
        )

        updated_count += 1
        if debug:
            print(f"[DBG] Updated {home} - {away}", file=sys.stderr)

    return updated_count, live_games_for_hash


# ---------------------------------------------------------
# CLI
# ---------------------------------------------------------
def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update games.csv with live status/results from ScheduleAndResults/Live HTML."
    )
    p.add_argument("-i", "--input-games", required=True, help="Input games.csv file")
    p.add_argument("-o", "--output-games", help="Output games.csv file (default: overwrite input)")
    p.add_argument("--html-file", help="Offline HTML file for ScheduleAndResults/Live (for tests)")
    p.add_argument("--live-url", help="Live URL (e.g. https://stats.swehockey.se/ScheduleAndResults/Live/19863).")
    p.add_argument("--series-id", help="Series id (used to derive URL if needed and filter games rows).")
    p.add_argument("--hash-file", help="Optional file to write live hash+timestamp to.")
    p.add_argument("--emit-json", action="store_true", help="Emit JSON summary of updated games to stdout (for wrapper scripts)")
    p.add_argument("--json-status-out", help="Write JSON status for the series to this file")
    p.add_argument("-dbg", "--debug", action="store_true", help="Debug logging to stderr")

    args = p.parse_args(argv)

    if not args.html_file and not args.live_url and not args.series_id:
        p.error("You must provide either --html-file or (--live-url or --series-id).")

    if not args.live_url and args.series_id:
        args.live_url = f"https://stats.swehockey.se/ScheduleAndResults/Live/{args.series_id}"

    return args

def main(argv: List[str]) -> int:
    args = parse_args(argv)
    debug = bool(args.debug)

    html_text = load_live_html(args.html_file, args.live_url, debug=debug)

    header, rows = read_games_csv(args.input_games)

    updated_count, live_games_for_hash = update_games_with_live(
        rows, html_text, args.series_id, debug=debug
    )

    out_path = args.output_games or args.input_games
    write_games_csv(out_path, header, rows)

    if debug:
        print(f"[DBG] Updated {updated_count} rows", file=sys.stderr)

    if (args.series_id or args.hash_file) and live_games_for_hash:
        h = compute_live_hash(live_games_for_hash)
        write_hash_file(h, args.hash_file, series_id=args.series_id, debug=debug)

    if args.emit_json:
        emit_games_json(live_games_for_hash)

    if args.series_id and args.json_status_out:
        statuses = build_live_series_status(rows, args.series_id)
        write_series_status_json(
            series_id=args.series_id,
            statuses=statuses,
            output_path=args.json_status_out,
        )
 
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

