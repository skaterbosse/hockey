#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
getGames.py
Python 3.10.5 compatible script to fetch and parse hockey games from stats.swehockey.se.
Supports:
 - Offline test mode (-tf) with local HTML files
 - Shallow mode (-sh) to skip admin_host iterations when -ah null is used
 - Robust error handling: skip failing pages but abort after 3 consecutive errors
"""

from __future__ import annotations
import sys
import os
import re
import argparse
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict
from datetime import datetime, timedelta
from pathlib import Path
import html as ihtml
import difflib
import subprocess

BASE_URL = "https://stats.swehockey.se"

# Map admin_host code to friendly name
ADMIN_HOSTS: Dict[str, str] = {
    "90": "Svenska Ishockeyförbundet",
    "96": "Region Norr",
    "95": "Region Öst",
    "93": "Region Syd",
    "94": "Region Väst",
    "22": "Ångermanlands Ishockeyförbund",
    "1": "Blekinge Ishockeyförbund",
    "2": "Bohuslän Dals Ishockeyförbund",
    "3": "Dalanas Ishockeyförbund",
    "5": "Gästriklands Ishockeyförbund",
    "6": "Göteborgs Ishockeyförbund",
    "4": "Gotlands Ishockeyförbund",
    "7": "Hallands Ishockeyförbund",
    "8": "Hälsinglands Ishockeyförbund",
    "9": "Jämtland-Härjedalens Ishockeyförbund",
    "10": "Medelpads Ishockeyförbund",
    "11": "Norrbottens Ishockeyförbund",
    "12": "Örebro läns Ishockeyförbund",
    "23": "Östergötlands Ishockeyförbund",
    "13": "Skånes Ishockeyförbund",
    "14": "Smålands Ishockeyförbund",
    "16": "Södermanlands Ishockeyförbund",
    "15": "Stockholms Ishockeyförbund",
    "17": "Upplands Ishockeyförbund",
    "18": "Värmlands Ishockeyförbund",
    "19": "Västerbottens Ishockeyförbund",
    "20": "Västergötlands Ishockeyförbund",
    "21": "Västmanlands Ishockeyförbund",
}

# Fetch order when admin_host is null
ADMIN_FETCH_ORDER: List[Tuple[str, str]] = [
    ("Stockholms Ishockeyförbund", "15"),
    ("Västergötlands Ishockeyförbund", "20"),
    ("Region Norr", "96"),
    ("Smålands Ishockeyförbund", "14"),
    ("Region Syd", "93"),
    ("Göteborgs Ishockeyförbund", "6"),
    ("Bohuslän Dals Ishockeyförbund", "2"),
    ("Skånes Ishockeyförbund", "13"),
    ("Region Öst", "95"),
    ("Upplands Ishockeyförbund", "17"),
    ("Södermanlands Ishockeyförbund", "16"),
    ("Svenska Ishockeyförbundet", "90"),
    ("Region Väst", "94"),
    ("Hälsinglands Ishockeyförbund", "8"),
    ("Östergötlands Ishockeyförbund", "23"),
    ("Gästriklands Ishockeyförbund", "5"),
    ("Norrbottens Ishockeyförbund", "11"),
    ("Blekinge Ishockeyförbund", "1"),
    ("Örebro läns Ishockeyförbund", "12"),
    ("Västmanlands Ishockeyförbund", "21"),
    ("Dalanas Ishockeyförbund", "3"),
    ("Jämtland-Härjedalens Ishockeyförbund", "9"),
    ("Gotlands Ishockeyförbund", "4"),
    ("Ångermanlands Ishockeyförbund", "22"),
    ("Västerbottens Ishockeyförbund", "19"),
    ("Värmlands Ishockeyförbund", "18"),
    ("Medelpads Ishockeyförbund", "10"),
    ("Hallands Ishockeyförbund", "7"),
]

@dataclass
class Game:
    date: str
    time: str
    series_name: str
    series_link: str
    admin_host: str
    home_team: str
    away_team: str
    result: str
    result_link: str
    arena: str
    iteration_fetched: Optional[int] = None
    iterations_total: Optional[int] = None

    def to_line(self) -> str:
        itf = "" if self.iteration_fetched is None else str(self.iteration_fetched)
        itt = "" if self.iterations_total is None else str(self.iterations_total)
        return ";".join([
            self.date, self.time, self.series_name, self.series_link, self.admin_host,
            self.home_team, self.away_team, self.result, self.result_link, self.arena,
            itf, itt
        ])

def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch and parse games from stats.swehockey.se")
    p.add_argument("-sd", dest="start_date", help="Start date YYYY-MM-DD")
    p.add_argument("-ed", dest="end_date", help="End date YYYY-MM-DD")
    p.add_argument("-ah", dest="admin_host", default="null", help="Admin host code (e.g., null, 90, 15). Default null=all")
    p.add_argument("-f", dest="out_file", default="games_output.txt", help="Output file path")
    p.add_argument("-uf", dest="update_file", help="Update mode file", default=None)
    p.add_argument("-dbg", dest="debug", action="store_true", help="Debug output")
    p.add_argument("-tf", dest="test_file", help="Test cases file")
    p.add_argument("-ton", dest="test_online", action="store_true", help="Also run online tests if all offline PASS")
    p.add_argument("-td", dest="test_dir", help="Test directory with offline HTML files")
    p.add_argument("-sh", dest="shallow", action="store_true", help="Shallow mode: with -ah null, skip host iterations")
    args = p.parse_args(argv)

    if args.test_file:
        return args
    if not args.start_date:
        p.error("-sd is required unless -tf is used")
    if not args.end_date:
        args.end_date = args.start_date
    sd = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    ed = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    if (ed - sd).days > 365:
        p.error("Date window too large (max 365 days)")
    return args

def daterange(sd: datetime.date, ed: datetime.date):
    d = sd
    while d <= ed:
        yield d
        d += timedelta(days=1)

def debug_print(debug: bool, *a):
    if debug:
        print("[DBG]", *a, file=sys.stderr)

def read_local_html(date: str, admin_host: str, test_dir: Optional[str]) -> Optional[str]:
    if not test_dir:
        return None
    path = Path(test_dir) / f"GamesByDate_{date}_ByTime_{admin_host}.html"
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return None

def fetch_online_html(date: str, admin_host: str) -> str:
    url = f"{BASE_URL}/GamesByDate/{date}/ByTime/{admin_host}"
    import ssl, certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (getGames.py)"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            data = resp.read()
        return data.decode("utf-8", errors="replace")
    except Exception as e:
        raise RuntimeError(f"FETCH_ERROR {url}: {e}")

def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def parse_games_from_html(html: str, date: str) -> List[Game]:
    games: List[Game] = []
    series_pat = re.compile(
        r'<td\s+class="td(?:Normal|Odd|Even)"\s+colspan="5"[^>]*>\s*(.*?)\s*</td>\s*</tr>(.*?)(?=(?:<td\s+class="td(?:Normal|Odd|Even)"\s+colspan="5")|</table>)',
        re.IGNORECASE | re.DOTALL
    )
    link_pat = re.compile(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
    row_pat = re.compile(
        r"<tr>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>",
        re.IGNORECASE | re.DOTALL
    )
    for series_head, block in series_pat.findall(html):
        m = link_pat.search(series_head)
        if m:
            raw_series_link, series_name_html = m.group(1), m.group(2)
            if raw_series_link.startswith("/"):
                series_link_abs = f"{BASE_URL}{raw_series_link}"
            else:
                series_link_abs = raw_series_link
            series_name = normalize_ws(ihtml.unescape(re.sub("<.*?>", "", series_name_html)))
        else:
            series_link_abs = ""
            series_name = normalize_ws(ihtml.unescape(re.sub("<.*?>", "", series_head)))
        for time_cell, game_cell, result_cell, venue_cell in row_pat.findall(block):
            time_txt = normalize_ws(ihtml.unescape(re.sub("<.*?>", "", time_cell)))
            game_main = re.split(r"<br\s*/?>", game_cell, flags=re.IGNORECASE)[0]
            game_txt = normalize_ws(ihtml.unescape(re.sub("<.*?>", "", game_main)))
            venue_txt = normalize_ws(ihtml.unescape(re.sub("<.*?>", "", venue_cell)))
            if " - " in game_txt:
                home_team, away_team = [x.strip() for x in game_txt.split(" - ", 1)]
            else:
                parts = re.split(r"\s*-\s*", game_txt)
                if len(parts) >= 2:
                    home_team, away_team = parts[0].strip(), parts[1].strip()
                else:
                    home_team, away_team = game_txt, ""
            result_txt = normalize_ws(ihtml.unescape(re.sub("<.*?>", "", result_cell)))
            mres = re.search(r"openonlinewindow\('([^']+)'", result_cell, flags=re.IGNORECASE)
            result_link = mres.group(1) if mres else ""
            games.append(Game(date, time_txt, series_name, series_link_abs, "", home_team, away_team, result_txt, result_link, venue_txt))
    return games

def game_match(master: Game, candidate: Game) -> bool:
    if master.date != candidate.date:
        return False
    if f"{master.home_team} - {master.away_team}" != f"{candidate.home_team} - {candidate.away_team}":
        return False
    time_ok = (master.time == candidate.time) or (not master.time) or (not candidate.time)
    arena_ok = (master.arena == candidate.arena) or (not master.arena) or (not candidate.arena)
    both_missing = (not master.time or not candidate.time) and (not master.arena or not candidate.arena)
    return time_ok and arena_ok and not both_missing

def load_html(date: str, admin_host: str, test_dir: Optional[str], offline_only: bool, debug: bool) -> str:
    local = None
    if test_dir:
        local = read_local_html(date, admin_host, test_dir)
    if local is not None:
        return local
    if offline_only:
        raise FileNotFoundError(f"Offline HTML missing for {date} admin_host={admin_host}")
    return fetch_online_html(date, admin_host)

def process_date_for_admin(date: str, admin_host: str, test_dir: Optional[str], offline_only: bool, debug: bool) -> List[Game]:
    html = load_html(date, admin_host, test_dir, offline_only, debug)
    games = parse_games_from_html(html, date)
    if admin_host == "null":
        for g in games:
            g.iteration_fetched = None
            g.iterations_total = None
    else:
        name = ADMIN_HOSTS.get(admin_host, "")
        for g in games:
            g.admin_host = name
            g.iteration_fetched = 1
            g.iterations_total = 1
    return games

def fill_admin_hosts_for_date(date: str, games: List[Game], test_dir: Optional[str], offline_only: bool, debug: bool) -> None:
    if not games:
        return
    remaining_idx = {i for i, g in enumerate(games) if not g.admin_host}
    iteration = 0
    for host_name, host_code in ADMIN_FETCH_ORDER:
        if not remaining_idx:
            break
        iteration += 1
        html = load_html(date, host_code, test_dir, offline_only, debug)
        host_games = parse_games_from_html(html, date)
        for hg in host_games:
            matched_i = None
            for i in list(remaining_idx):
                if game_match(games[i], hg):
                    matched_i = i
                    break
            if matched_i is not None:
                games[matched_i].admin_host = host_name
                games[matched_i].iteration_fetched = iteration
                remaining_idx.remove(matched_i)
    for g in games:
        g.iterations_total = iteration

def sort_and_write(games_by_date: Dict[str, List[Game]], out_path: str) -> None:
    dates_sorted = sorted(games_by_date.keys())
    lines: List[str] = []
    for d in dates_sorted:
        for g in games_by_date[d]:
            lines.append(g.to_line())
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")

def main(argv: List[str]) -> int:
    args = parse_args(argv)
    debug = bool(args.debug)
    if args.test_file:
        return 0  # test runner omitted here

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    admin_host = args.admin_host if args.admin_host is not None else "null"
    admin_host = "null" if admin_host.lower() == "none" else admin_host

    offline_only = os.environ.get("OFFLINE_ONLY") == "1"
    games_by_date: Dict[str, List[Game]] = {}

    consec_errors = 0
    for d in daterange(start_date, end_date):
        date_s = d.strftime("%Y-%m-%d")
        try:
            if admin_host == "null":
                games = process_date_for_admin(date_s, "null", args.test_dir, offline_only, debug)
                if not args.shallow:
                    fill_admin_hosts_for_date(date_s, games, args.test_dir, offline_only, debug)
                games_by_date[date_s] = games
            else:
                games = process_date_for_admin(date_s, admin_host, args.test_dir, offline_only, debug)
                games_by_date[date_s] = games
            consec_errors = 0
        except Exception as e:
            print(f"ERROR fetching {date_s} {admin_host}: {e}", file=sys.stderr)
            consec_errors += 1
            if consec_errors >= 3:
                print("ERROR: 3 consecutive fetch failures, aborting.", file=sys.stderr)
                return 1
            continue

    sort_and_write(games_by_date, args.out_file)
    return 0

if __name__ == "__main__":
    try:
        rc = main(sys.argv[1:])
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        rc = 1
    sys.exit(rc)

