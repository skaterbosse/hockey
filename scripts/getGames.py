#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
getGames.py
Python 3.10.5 compatible script to fetch and parse hockey games from stats.swehockey.se.
Supports:
 - Offline test mode (-tf) with local HTML files
 - Shallow mode (-sh) to skip admin_host iterations when -ah null is used
 - Robust error handling: skip failing pages but abort after 3 consecutive errors
 - Förstärkt loggning till ./logs/

Alt A-kolumnformat:
- ALLTID 13 kolumner:
  1:  date
  2:  time
  3:  series_name
  4:  series_link
  5:  admin_host (namn, tomt i null-shallow)
  6:  home_team
  7:  away_team
  8:  result
  9:  result_link
  10: arena
  11: iteration_fetched (tom i shallow)
  12: iterations_total (tom i shallow)
  13: shallow_flag (ALLTID '1' i våra tester)
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

# Fetch order när admin_host är null
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

# === Enkel fil-loggning ===
LOG_FH = None  # type: Optional[object]


def init_logger(start_date: str, end_date: str, admin_host: str, shallow: bool, out_file: str):
    """Initiera loggfil i ./logs/."""
    global LOG_FH
    try:
        logs_dir = Path("logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        mode = "shallow" if shallow else "deep"
        safe_ah = admin_host.replace("/", "_")
        log_name = f"getGames_{start_date}_{end_date}_{safe_ah}_{mode}_{ts}.log"
        log_path = logs_dir / log_name
        LOG_FH = log_path.open("a", encoding="utf-8")
        log(f"=== getGames.py start ===")
        log(f"start_date={start_date}, end_date={end_date}, admin_host={admin_host}, mode={mode}, out_file={out_file}")
    except Exception as e:
        # Om loggfilen mot förmodan inte kan skapas loggar vi bara till stderr
        print(f"[{datetime.now().isoformat()}] ⚠️ Kunde inte initiera loggfil: {e}", file=sys.stderr)


def close_logger():
    global LOG_FH
    if LOG_FH:
        try:
            log("=== getGames.py end ===")
            LOG_FH.close()
        except Exception:
            pass
    LOG_FH = None


def log(msg: str):
    """Logga både till stderr (Actions) och till fil om den finns."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, file=sys.stderr)
    if LOG_FH is not None:
        try:
            print(line, file=LOG_FH)
            LOG_FH.flush()
        except Exception:
            pass


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
    shallow_flag: int = 1  # Alltid '1' i våra tester

    def to_line(self) -> str:
        """
        Alt A: alltid 13 kolumner.
        - iteration_fetched: tom i shallow
        - iterations_total: tom i shallow
        - shallow_flag: '1'
        """
        itf = "" if self.iteration_fetched is None else str(self.iteration_fetched)
        itt = "" if self.iterations_total is None else str(self.iterations_total)
        flag = "" if self.shallow_flag is None else str(self.shallow_flag)
        return ";".join([
            self.date,
            self.time,
            self.series_name,
            self.series_link,
            self.admin_host,
            self.home_team,
            self.away_team,
            self.result,
            self.result_link,
            self.arena,
            itf,
            itt,
            flag,
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
        log(f"📄 Läser lokal HTML-fil: {path}")
        return path.read_text(encoding="utf-8", errors="replace")
    return None


def fetch_online_html(date: str, admin_host: str) -> str:
    """
    Hämtar HTML från stats.swehockey.se/GamesByDate/{date}/ByTime/{admin_host}
    med upp till 3 försök vid temporära fel.
    """
    import ssl
    import certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
    url = f"{BASE_URL}/GamesByDate/{date}/ByTime/{admin_host}"
    headers = {"User-Agent": "Mozilla/5.0 (getGames.py)"}

    last_err = None
    for attempt in range(1, 4):
        try:
            log(f"📡 Hämtar {url} (försök {attempt}/3)")
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                data = resp.read()
                log(f"✅ Lyckad fetch {url} (bytes={len(data)})")
                return data.decode("utf-8", errors="replace")
        except Exception as e:
            last_err = e
            log(f"⚠️ Fetch-fel (försök {attempt}/3) för {url}: {e}")
    log(f"❌ Permanent fetch-fel efter 3 försök för {url}")
    raise RuntimeError(f"FETCH_ERROR {url}: {last_err}")


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
            # Replace postponed/inställd match times with "PPD"
            time_clean = time_txt.lower()
            if time_clean in ["postponed", "inställd", "inst", "ppd"]:
                time_txt = "PPD"
            elif any(k in time_clean for k in ["postponed", "instäl", "ppd"]):
                time_txt = "PPD"

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

            games.append(Game(
                date=date,
                time=time_txt,
                series_name=series_name,
                series_link=series_link_abs,
                admin_host="",
                home_team=home_team,
                away_team=away_team,
                result=result_txt,
                result_link=result_link,
                arena=venue_txt
            ))
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


def load_html(date: str, admin_host: str, test_dir: Optional[str], offline_only: bool, debug: bool) -> Optional[str]:
    """
    Returnerar:
       - HTML-text (str) om fil hittas lokalt eller online
       - None om offline-läge + fil saknas => tolkas som '0 matcher'
    """

    # 1) Offline testmode? Försök läsa lokal HTML
    if test_dir:
        local_path = Path(test_dir) / f"GamesByDate_{date}_ByTime_{admin_host}.html"
        if local_path.exists():
            log(f"📄 Läser lokal HTML-fil: {local_path}")
            return local_path.read_text(encoding="utf-8", errors="replace")
        else:
            if offline_only:
                # Offline => saknad fil = 0 matcher
                log(f"ℹ️ Offline-läge: ingen HTML för admin_host={admin_host}, tolkar som 0 matcher")
                return None
            # Annars fortsätt till online fetch

    # 2) Online fetch (endast om offline_only = False)
    if offline_only:
        msg = f"Offline-läge och ingen lokal HTML för {date} admin_host={admin_host}"
        log(f"❌ {msg}")
        raise FileNotFoundError(msg)

    # Online fetch
    return fetch_online_html(date, admin_host)


def process_date_for_admin(date: str, admin_host: str, test_dir: Optional[str], offline_only: bool, debug: bool) -> List[Game]:
    log(f"➡️  Bearbetar datum {date} (admin_host={admin_host})")
    html = load_html(date, admin_host, test_dir, offline_only, debug)

    if html is None:
        # Offline deep-mode: saknad HTML => inga matcher
        games = []
    else:
        games = parse_games_from_html(html, date)

    # Admin_host = null → inga iterationer här
    if admin_host == "null":
        for g in games:
            g.iteration_fetched = None
            g.iterations_total = None
            g.shallow_flag = 1
    else:
        host_name = ADMIN_HOSTS.get(admin_host, "")
        for g in games:
            g.admin_host = host_name
            g.iteration_fetched = 1
            g.iterations_total = 1
            g.shallow_flag = 1

    log(f"📊 Parsed {len(games)} matcher för {date} (admin_host={admin_host})")
    return games


def fill_admin_hosts_for_date(date: str, games: List[Game], test_dir: Optional[str], offline_only: bool, debug: bool) -> None:
    if not games:
        log(f"ℹ️ Hoppar över admin_host-fyllnad för {date} – inga master-matcher")
        return

    remaining_idx = {i for i, g in enumerate(games) if not g.admin_host}
    iteration = 0

    log(f"🔍 Startar admin_host-fyllnad för {date}, matcher utan host={len(remaining_idx)}")

    for host_name, host_code in ADMIN_FETCH_ORDER:
        if not remaining_idx:
            break

        iteration += 1
        log(f"📡 Iteration {iteration}: admin_host={host_code} ({host_name})")

        html = load_html(date, host_code, test_dir, offline_only, debug)

        if html is None:
            # Offline deep-mode: ingen fil => inga matcher för denna host
            host_games = []
            log(f"ℹ️ Offline-läge: ingen HTML → 0 matcher för admin_host={host_code}")
        else:
            host_games = parse_games_from_html(html, date)

        # Matchning mot master-listan
        matched = 0
        for hg in host_games:
            for i in list(remaining_idx):
                if game_match(games[i], hg):
                    games[i].admin_host = host_name
                    games[i].iteration_fetched = iteration
                    games[i].shallow_flag = 1
                    matched += 1
                    remaining_idx.remove(i)
                    break

        log(f"   🔎 Matchade {matched} matcher")

    # Efter alla iterationer
    for g in games:
        g.iterations_total = iteration
        if g.shallow_flag is None:
            g.shallow_flag = 1

    if remaining_idx:
        log(f"⚠️ {len(remaining_idx)} matcher saknar fortfarande admin_host efter {iteration} iterationer")


def offline_fill_admin_hosts_for_date(date: str, games: List[Game], base_html_dir: Path) -> None:
    """
    Offline-variant av fill_admin_hosts_for_date, som bara använder lokala HTML-filer
    och INTE fetchar något online. Saknade HTML-filer för en admin_host ignoreras tyst.
    """
    if not games:
        return

    remaining_idx = {i for i, g in enumerate(games) if not g.admin_host}
    iteration = 0

    for host_name, host_code in ADMIN_FETCH_ORDER:
        if not remaining_idx:
            break
        iteration += 1

        html = read_local_html(date, host_code, str(base_html_dir))
        if html is None:
            # Ingen lokal HTML för denna admin_host → inga matcher här
            continue

        host_games = parse_games_from_html(html, date)
        matches_this_host = 0

        for hg in host_games:
            matched_i = None
            for i in list(remaining_idx):
                if game_match(games[i], hg):
                    matched_i = i
                    break
            if matched_i is not None:
                games[matched_i].admin_host = host_name
                games[matched_i].iteration_fetched = iteration
                games[matched_i].shallow_flag = 1
                remaining_idx.remove(matched_i)
                matches_this_host += 1

    # Sätt iterations_total till antal iterationer vi faktiskt gjorde
    for g in games:
        g.iterations_total = iteration
        if g.shallow_flag is None:
            g.shallow_flag = 1


def sort_and_write(games_by_date: Dict[str, List[Game]], out_path: str) -> None:
    dates_sorted = sorted(games_by_date.keys())
    lines: List[str] = []
    total_games = 0
    for d in dates_sorted:
        for g in games_by_date[d]:
            lines.append(g.to_line())
            total_games += 1
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    log(f"💾 Skrev totalt {total_games} matcher till {out_path}")


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    debug = bool(args.debug)

    # -----------------------------------------------------------
    # TEST MODE (-tf test_cases.txt)
    # -----------------------------------------------------------
    if args.test_file:
        test_file = args.test_file
        base_html_dir = Path(args.test_dir or "tests/html")
        tmp_dir = Path("tests/tmp")
        tmp_dir.mkdir(parents=True, exist_ok=True)

        print(f"[TEST] Running test cases from: {test_file}")

        test_cases = []

        with open(test_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(";")
                if len(parts) < 8:
                    print(f"[TEST] Skipping malformed line ({len(parts)} cols): {line}")
                    continue

                cid, case_name, mode = parts[0], parts[1], parts[2]

                if mode == "offline":
                    # Format:
                    # id;name;offline;sd;ed;admin_host;depth;expected[;PASS]
                    sd, ed, admin_host, depth, expected_file = parts[3:8]
                    expected_status = parts[8] if len(parts) > 8 else ""
                    test_cases.append({
                        "id": cid,
                        "name": case_name,
                        "mode": "offline",
                        "start_date": sd,
                        "end_date": ed,
                        "admin_host": admin_host,
                        "depth": depth,  # "shallow" eller "deep"
                        "expected": expected_file,
                        "expected_status": expected_status,
                    })
                elif mode == "offline-update":
                    # Format:
                    # id;name;offline-update;sd;ed;admin_host;before_file;expected[;PASS]
                    sd, ed, admin_host, before_file, expected_file = parts[3:8]
                    expected_status = parts[8] if len(parts) > 8 else ""
                    test_cases.append({
                        "id": cid,
                        "name": case_name,
                        "mode": "offline-update",
                        "start_date": sd,
                        "end_date": ed,
                        "admin_host": admin_host,
                        "before_file": before_file,
                        "expected": expected_file,
                        "expected_status": expected_status,
                    })
                else:
                    print(f"[TEST] Unknown mode '{mode}' in line: {line}")

        if not test_cases:
            print("[TEST] No valid test cases found.")
            return 1

        def sorted_text(path: Path) -> str:
            if not path.exists():
                return ""
            lines = path.read_text(encoding="utf-8").splitlines()
            # Ta bort helt tomma rader och normalisera radslut
            lines = [ln.rstrip("\r\n") for ln in lines if ln.strip() != ""]
            lines_sorted = sorted(lines)
            return "\n".join(lines_sorted)

        all_passed = True

                # ==== Kör alla testfall ====
        results = []  # <-- för sammanfattning

        for tc in test_cases:
            print(f"\n[TEST] === CASE {tc['id']} : {tc['name']} ({tc['mode']}) ===")
            case_result = {"id": tc["id"], "name": tc["name"], "mode": tc["mode"], "status": "ERROR"}

            try:
                # -----------------------------------------------------------
                # A) offline shallow/deep (null eller specifik admin_host)
                # -----------------------------------------------------------
                if tc["mode"] == "offline":
                    sd = datetime.strptime(tc["start_date"], "%Y-%m-%d").date()
                    ed = datetime.strptime(tc["end_date"], "%Y-%m-%d").date()
                    admin_host = tc["admin_host"]
                    depth = tc["depth"]

                    games_by_date: Dict[str, List[Game]] = {}

                    for d in daterange(sd, ed):
                        date_s = d.strftime("%Y-%m-%d")

                        html = read_local_html(date_s, admin_host, str(base_html_dir))
                        if html is None:
                            raise FileNotFoundError(
                                f"[TEST] Missing offline HTML file for {date_s} admin_host={admin_host}"
                            )

                        games = parse_games_from_html(html, date_s)

                        if depth == "deep" and admin_host == "null":
                            offline_fill_admin_hosts_for_date(date_s, games, base_html_dir)

                        games_by_date[date_s] = games

                    tmp_out = tmp_dir / f"{tc['name']}_output.txt"
                    with tmp_out.open("w", encoding="utf-8") as f_out:
                        for d in sorted(games_by_date.keys()):
                            for g in games_by_date[d]:
                                f_out.write(g.to_line() + "\n")

                # -----------------------------------------------------------
                # B) offline-update
                # -----------------------------------------------------------
                elif tc["mode"] == "offline-update":
                    sd = datetime.strptime(tc["start_date"], "%Y-%m-%d").date()
                    ed = datetime.strptime(tc["end_date"], "%Y-%m-%d").date()
                    if sd != ed:
                        raise ValueError("[TEST] offline-update supports only one date")

                    date_s = sd.strftime("%Y-%m-%d")

                    new_html_dir = base_html_dir / "new"
                    html = read_local_html(date_s, "null", str(new_html_dir))
                    if html is None:
                        raise FileNotFoundError(
                            f"[TEST] Missing NEW offline HTML file for {date_s} admin_host=null in {new_html_dir}"
                        )

                    new_games = parse_games_from_html(html, date_s)

                    before_path = Path("tests/input") / tc["before_file"]
                    if not before_path.exists():
                        raise FileNotFoundError(f"[TEST] Before-file missing: {before_path}")

                    before_lines = before_path.read_text(encoding="utf-8").splitlines()

                    @dataclass
                    class BeforeKey:
                        date: str
                        time: str
                        series_name: str
                        home_team: str
                        away_team: str
                        arena: str

                    def key_from_line(line: str) -> BeforeKey:
                        cols = [c.strip() for c in line.split(";")]
                        return BeforeKey(
                            cols[0] if len(cols) > 0 else "",
                            cols[1] if len(cols) > 1 else "",
                            cols[2] if len(cols) > 2 else "",
                            cols[5] if len(cols) > 5 else "",
                            cols[6] if len(cols) > 6 else "",
                            cols[9] if len(cols) > 9 else "",
                        )

                    def update_match(bk: BeforeKey, g: Game) -> bool:
                        if bk.date != g.date:
                            return False
                        if bk.series_name != g.series_name:
                            return False
                        if f"{bk.home_team} - {bk.away_team}" != f"{g.home_team} - {g.away_team}":
                            return False
                        time_ok = (bk.time == g.time) or (not bk.time) or (not g.time)
                        arena_ok = (bk.arena == g.arena) or (not bk.arena) or (not g.arena)
                        both_missing = (not bk.time or not g.time) and (not bk.arena or not g.arena)
                        return time_ok and arena_ok and not both_missing

                    updated_lines: List[str] = []

                    for raw in before_lines:
                        if not raw.strip():
                            updated_lines.append(raw)
                            continue

                        bk = key_from_line(raw)
                        match_game = None

                        for g in new_games:
                            if update_match(bk, g):
                                match_game = g
                                break

                        if match_game is None:
                            updated_lines.append(raw)
                        else:
                            cols = raw.split(";")
                            while len(cols) <= 8:
                                cols.append("")
                            cols[7] = match_game.result
                            cols[8] = match_game.result_link
                            updated_lines.append(";".join(cols))

                    tmp_out = tmp_dir / f"{tc['name']}_output.txt"
                    tmp_out.write_text("\n".join(updated_lines), encoding="utf-8")

                print(f"[TEST] Wrote tmp output → {tmp_out}")

                # === Compare sorted output ===
                expected_path = Path("tests/expected") / tc["expected"]
                if not expected_path.exists():
                    print(f"[TEST] Expected file missing: {expected_path}")
                    case_result["status"] = "FAIL"
                    results.append(case_result)
                    all_passed = False
                    continue

                expected_sorted = sorted_text(expected_path)
                actual_sorted = sorted_text(tmp_out)

                if expected_sorted == actual_sorted:
                    print(f"[TEST] PASS ✓ {tc['name']}")
                    case_result["status"] = "PASS"
                else:
                    print(f"[TEST] FAIL ✗ {tc['name']}")
                    case_result["status"] = "FAIL"
                    all_passed = False
                    diff = difflib.unified_diff(
                        expected_sorted.splitlines(),
                        actual_sorted.splitlines(),
                        fromfile="expected(sorted)",
                        tofile="actual(sorted)",
                        lineterm=""
                    )
                    for line in diff:
                        print(line)

            except Exception as e:
                print(f"[TEST] ERROR in test case {tc['name']}: {e}")
                case_result["status"] = "ERROR"
                all_passed = False

            results.append(case_result)

        # ============================================================
        # NEW SUMMARY SECTION
        # ============================================================
        print("\n[TEST] ===============================")
        print("[TEST] SUMMARY OF ALL TEST CASES")
        print("================================")

        passes = 0
        fails = 0
        errors = 0

        for r in results:
            st = r["status"]
            if st == "PASS": passes += 1
            elif st == "FAIL": fails += 1
            else: errors += 1

            print(f"  • {r['id']:>3}  {r['name']:<40}  →  {st}")

        print("--------------------------------")
        print(f"TOTAL: {len(results)} tests")
        print(f"PASS : {passes}")
        print(f"FAIL : {fails}")
        print(f"ERROR: {errors}")
        print("--------------------------------")

        if fails == 0 and errors == 0:
            print("[TEST] ALL TESTS PASSED ✓")
            return 0
        else:
            print("[TEST] SOME TESTS FAILED ✗")
            return 1

    # ===== Normal körning (ej -tf) =====
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    admin_host = args.admin_host if args.admin_host is not None else "null"
    admin_host = "null" if admin_host.lower() == "none" else admin_host

    # Initiera logg
    init_logger(args.start_date, args.end_date, admin_host, args.shallow, args.out_file)

    offline_only = os.environ.get("OFFLINE_ONLY") == "1"
    if offline_only:
        log("🌐 OFFLINE_ONLY=1 – försöker ENDAST använda lokala HTML-filer")

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
            log(f"❌ ERROR fetching {date_s} admin_host={admin_host}: {e}")
            consec_errors += 1
            if consec_errors >= 3:
                log("❌ 3 konsekutiva fetch-fel – avbryter.")
                return 1
            continue

    sort_and_write(games_by_date, args.out_file)
    return 0


if __name__ == "__main__":
    try:
        rc = main(sys.argv[1:])
    except Exception as e:
        # Sista försvarslinje – fångar oväntade exceptions
        print(f"ERROR: {e}", file=sys.stderr)
        log(f"💥 Oväntat fel i main: {e}")
        rc = 1
    finally:
        close_logger()
    sys.exit(rc)

