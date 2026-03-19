#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import datetime as _dt
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_SEASON = "2026-2027"
SEASON_RE = re.compile(r"\b20\d{2}-20\d{2}\b")

POSITION_TOKEN = r"(?:G|D|LD|RD|C|F|W|LW|RW)(?:/(?:G|D|LD|RD|C|F|W|LW|RW))*"

# Variant 1: current/offline raw HTML where position is rendered near the player row
PLAYER_ROW_CAPTURE_RE = re.compile(r'<tr class="SortTable_tr__L9yVC">(.*?)</tr>', re.S)
PLAYER_ROW_PARSE_RE = re.compile(
    rf'href="(?P<player_path>/player/[^"]+)">'
    rf'(?P<name>[^<]+).*?\((?P<position>{POSITION_TOKEN})\)</a>'
    rf'.*?<span title="(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{2}}/\d{{2}}/\d{{4}})">(?P<birthyear>\d{{4}})<',
    re.S,
)

# Variant 2: server-rendered HTML/text-like page where name+position are in same link text
WHOLE_SEGMENT_PARSE_RE = re.compile(
    rf'href="(?P<player_path>/player/[^"]+)">(?P<name>[^<(][^<]*?)\s+\((?P<position>{POSITION_TOKEN})\)</a>'
    rf'.*?(?:^|>| )\d{{1,2}}\s+(?P<birthyear>\d{{4}})(?:<| )',
    re.S,
)


def debug(msg: str, enabled: bool) -> None:
    if enabled:
        print(f"[DEBUG] {msg}", file=sys.stderr)


def replace_season(text: str, season: str) -> str:
    return SEASON_RE.sub(season, text)


def backup_if_exists(path: Path, dbg: bool) -> Path | None:
    if not path.exists():
        debug(f"Ingen backup skapad, fil saknas: {path}", dbg)
        return None
    old_path = path.with_name(path.stem + "_old" + path.suffix)
    shutil.copy2(path, old_path)
    debug(f"Backup skapad: {old_path}", dbg)
    return old_path


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def parse_offline_mapping(path: Path, season: str, dbg: bool) -> Dict[str, Path]:
    mapping: Dict[str, Path] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 2:
            raise ValueError(f"Fel format i OFFLINE FILE rad {lineno}: {raw}")
        online_url = replace_season(parts[0], season)
        offline_file = Path(replace_season(parts[1], season))
        mapping[online_url] = offline_file
        debug(f"Offline-map: {online_url} -> {offline_file}", dbg)
    return mapping


def fetch_html(url: str, season: str, dbg: bool, dbg_raw_input: bool) -> str:
    debug(f"Hämtar HTML: {url}", dbg)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        )
    }

    current_url = url
    max_redirects = 10

    def _norm(u: str) -> str:
        return u.rstrip("/")

    for redirect_count in range(max_redirects + 1):
        req = urllib.request.Request(current_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                final_url = resp.geturl()
                charset = resp.headers.get_content_charset() or "utf-8"
                data = resp.read()
                html_text = data.decode(charset, errors="replace")
                debug(f"Hämtade {len(data)} bytes från {final_url}", dbg)

                if _norm(final_url) != _norm(url) and season not in _norm(final_url):
                    debug(
                        f"Svarade med annan URL än begärt: {url} -> {final_url}; "
                        f"säsongen {season} saknas i slutlig URL, tolkar som tom roster",
                        dbg,
                    )
                    return ""

                if dbg_raw_input:
                    print("DEBUG_RAW_INPUT_START", file=sys.stderr)
                    print(html_text, file=sys.stderr, end="" if html_text.endswith("\n") else "\n")
                    print("DEBUG_RAW_INPUT_END", file=sys.stderr)
                return html_text
        except urllib.error.HTTPError as e:
            if e.code == 308:
                location = e.headers.get("Location")
                new_url = urllib.parse.urljoin(current_url, location) if location else "(okänd)"
                debug(f"308 Permanent Redirect för {current_url} -> {new_url}; tolkar som tom roster", dbg)
                return ""
            raise RuntimeError(f"HTTP-fel vid hämtning av {current_url}: {e.code} {e.reason}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Nätverksfel vid hämtning av {current_url}: {e}") from e

    raise RuntimeError(f"För många redirects vid hämtning av {url}")


def read_offline_html(url: str, offline_map: Dict[str, Path], dbg: bool, dbg_raw_input: bool) -> str:
    if url not in offline_map:
        raise RuntimeError(f"URL saknas i OFFLINE FILE: {url}")
    offline_file = offline_map[url]
    if not offline_file.exists():
        raise RuntimeError(f"Offline-fil saknas för {url}: {offline_file}")
    debug(f"Läser offline HTML för {url}: {offline_file}", dbg)
    html_text = offline_file.read_text(encoding="utf-8", errors="replace")
    if dbg_raw_input:
        print("DEBUG_RAW_INPUT_START", file=sys.stderr)
        print(html_text, file=sys.stderr, end="" if html_text.endswith("\n") else "\n")
        print("DEBUG_RAW_INPUT_END", file=sys.stderr)
    return html_text


def extract_roster_segment(html_text: str, season: str, dbg: bool) -> str:
    if season not in html_text:
        debug(f"Säsongsträngen {season} hittades inte direkt i HTML", dbg)

    start_candidates = [
        html_text.find("GOALTENDERS"),
        html_text.find("Jersey Number"),
        html_text.find("Roster</h2>"),
    ]
    start_candidates = [x for x in start_candidates if x != -1]
    if not start_candidates:
        debug("Kunde inte hitta roster-start, använder hela HTML-dokumentet", dbg)
        start_idx = 0
    else:
        start_idx = min(start_candidates)

    end_candidates = []
    for token in [
        "Position: G:",
        "Compare with other teams",
        "<!-- --> Staff</h2>",
        "Staff</h2>",
        "## " + season + " ",
    ]:
        idx = html_text.find(token, start_idx + 1)
        if idx != -1:
            end_candidates.append(idx)

    if end_candidates:
        end_idx = min(end_candidates)
    else:
        debug("Kunde inte hitta roster-slut, använder resten av HTML-dokumentet", dbg)
        end_idx = len(html_text)

    segment = html_text[start_idx:end_idx]
    debug(f"Roster-segmentets längd: {len(segment)} tecken", dbg)
    return segment


def parse_roster_from_rows(segment: str, dbg: bool) -> List[str]:
    roster_lines: List[str] = []
    seen_urls: set[str] = set()

    rows = PLAYER_ROW_CAPTURE_RE.findall(segment)
    debug(f"Antal HTML-rader funna i roster-segment: {len(rows)}", dbg)

    for row_html in rows:
        match = PLAYER_ROW_PARSE_RE.search(row_html)
        if not match:
            continue

        player_url = f"https://www.eliteprospects.com{match.group('player_path').strip()}"
        if player_url in seen_urls:
            continue

        name = match.group("name").strip()
        position = match.group("position").strip()
        birthyear = match.group("birthyear").strip()

        roster_lines.append(f"{player_url};{name};{position};{birthyear}")
        seen_urls.add(player_url)

    return roster_lines


def parse_roster_from_whole_segment(segment: str, dbg: bool) -> List[str]:
    roster_lines: List[str] = []
    seen_urls: set[str] = set()

    matches = list(WHOLE_SEGMENT_PARSE_RE.finditer(segment))
    debug(f"Antal träffar i whole-segment-parser: {len(matches)}", dbg)

    for match in matches:
        player_url = f"https://www.eliteprospects.com{match.group('player_path').strip()}"
        if player_url in seen_urls:
            continue

        name = match.group("name").strip()
        position = match.group("position").strip()
        birthyear = match.group("birthyear").strip()

        roster_lines.append(f"{player_url};{name};{position};{birthyear}")
        seen_urls.add(player_url)

    return roster_lines


def parse_roster_from_html(html_text: str, season: str, dbg: bool) -> List[str]:
    segment = extract_roster_segment(html_text, season, dbg)

    roster_lines = parse_roster_from_rows(segment, dbg)
    if roster_lines:
        debug(f"Parser hittade {len(roster_lines)} spelare med row-parser", dbg)
        return roster_lines

    roster_lines = parse_roster_from_whole_segment(segment, dbg)
    debug(f"Parser hittade {len(roster_lines)} spelare med whole-segment-parser", dbg)
    return roster_lines


def run_python_parser(
    url: str,
    season: str,
    output_file: Path,
    dbg: bool,
    dbg_raw_input: bool,
    offline_map: Optional[Dict[str, Path]],
) -> None:
    debug(f"Källa URL: {url}", dbg)
    if offline_map is None:
        html_text = fetch_html(url, season, dbg, dbg_raw_input)
    else:
        html_text = read_offline_html(url, offline_map, dbg, dbg_raw_input)

    roster_lines = parse_roster_from_html(html_text, season, dbg)

    # 0 spelare är ett giltigt normalfall: skapa tom rosterfil och fortsätt.
    if not roster_lines:
        debug(f"Parser hittade 0 spelare för {url} - skapar tom rosterfil", dbg)
        write_text(output_file, "")
        debug(f"Skrev tom rosterfil: {output_file}", dbg)
        return

    write_text(output_file, "\n".join(roster_lines) + "\n")
    debug(f"Skrev rosterfil: {output_file}", dbg)


def parse_teams_file(teams_file: Path, season: str, dbg: bool) -> List[Dict[str, str]]:
    teams: List[Dict[str, str]] = []
    for lineno, raw in enumerate(teams_file.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 6:
            raise ValueError(
                f"Fel format i {teams_file} rad {lineno}: förväntade minst 6 kolumner, fick {len(parts)}: {raw}"
            )

        team = {
            "url": replace_season(parts[0], season),
            "roster_filename": replace_season(parts[1], season),
            "series": parts[2],
            "series_shortname": parts[3],
            "team_name": parts[4],
            "logo_filename": parts[5],
        }
        teams.append(team)

        debug(
            f"Team rad {lineno}: {team['url']} -> {team['roster_filename']} "
            f"({team['series']} / {team['series_shortname']} / {team['team_name']} / {team['logo_filename']})",
            dbg,
        )
    return teams


def count_roster_players(roster_file: Path) -> int:
    count = 0
    if not roster_file.exists():
        return 0
    for line in roster_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if ";" in line:
            count += 1
    return count


def make_all_players_file(output_dir: Path, season: str, roster_filenames: List[str], dbg: bool) -> Path:
    all_players = output_dir / f"alla_spelare_{season}.txt"
    lines: List[str] = []
    for roster_name in roster_filenames:
        roster_path = output_dir / roster_name
        if not roster_path.exists():
            debug(f"Rosterfil saknas och hoppas över i alla_spelare: {roster_path}", dbg)
            continue
        for raw in roster_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if ";" in line:
                lines.append(f"{roster_name};{line}")
    write_text(all_players, "\n".join(lines) + ("\n" if lines else ""))
    debug(f"Skapade {all_players} med {len(lines)} rader", dbg)
    return all_players


def make_team_summary_file(output_dir: Path, season: str, roster_filenames: List[str], dbg: bool) -> Path:
    summary_path = output_dir / f"lag_summering_{season}.txt"
    summary_rows = []
    for roster_name in roster_filenames:
        cnt = count_roster_players(output_dir / roster_name)
        summary_rows.append((cnt, roster_name))
    summary_rows.sort(key=lambda x: (x[0], x[1]))
    text = "\n".join(f"{cnt:4d} {name}" for cnt, name in summary_rows)
    write_text(summary_path, text + ("\n" if text else ""))
    debug(f"Skapade {summary_path} med {len(summary_rows)} lag", dbg)
    return summary_path


def make_young_summary_file(output_dir: Path, season: str, all_players_file: Path, dbg: bool) -> Path:
    young_years = {"2003", "2004", "2005", "2006", "2007"}
    counts = {}
    for raw in all_players_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(";")
        if len(parts) < 5:
            continue
        roster_name = parts[0]
        birthyear = parts[-1].strip()
        if birthyear in young_years:
            counts[roster_name] = counts.get(roster_name, 0) + 1

    out = output_dir / f"lag_summering_2003_{season}.txt"
    rows = sorted(counts.items(), key=lambda x: (x[1], x[0]))
    text = "\n".join(f"{cnt:4d} {name}" for name, cnt in rows)
    write_text(out, text + ("\n" if text else ""))
    debug(f"Skapade {out} med {len(rows)} lag", dbg)
    return out


def _diff_header_line(prefix: str, path: Path) -> str:
    ts = _dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return f"{prefix} {path}\t{ts}\n"


def save_diff(old_file: Path | None, new_file: Path, dbg: bool) -> Path:
    date_tag = _dt.datetime.now().strftime("%Y%m%d")
    diff_file = new_file.with_name(f"{new_file.stem}_diff_{date_tag}{new_file.suffix}")
    if old_file is None or not old_file.exists():
        write_text(diff_file, f"Ingen tidigare fil att jämföra med för {new_file.name}\n")
        debug(f"Ingen diff möjlig för {new_file}, gammal fil saknas", dbg)
        return diff_file

    res = subprocess.run(["diff", "-u", str(old_file), str(new_file)], capture_output=True, text=True)
    if res.returncode > 1:
        raise RuntimeError(f"diff misslyckades för {old_file} och {new_file}: {res.stderr}")

    if res.stdout:
        diff_text = res.stdout
    else:
        # Skriv alltid header-rader med tidsstämplar även när inga skillnader finns.
        # Då kan HTML-koden registrera att en ny körning faktiskt har skett.
        diff_text = (
            _diff_header_line("---", old_file)
            + _diff_header_line("+++", new_file)
            + "Inga skillnader.\n"
        )

    write_text(diff_file, diff_text)
    debug(f"Skapade diff-fil {diff_file}", dbg)
    return diff_file


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="getTeamRosters.py",
        description="Hämtar aktuella rosters från Eliteprospects och skapar roster-, summerings- och diff-filer.",
    )
    p.add_argument("-tf", "--teams-file", required=True, help="Path till TEAMS FILE.")
    p.add_argument("-s", "--season", default=DEFAULT_SEASON, help=f"Säsong, default {DEFAULT_SEASON}.")
    p.add_argument("-od", "--output-directory", required=True, help="Katalog där genererade filer sparas.")
    p.add_argument("-of", "--offline-file", help="Offline file map: online adress;offline file")
    p.add_argument("-dbg", "--debug", action="store_true", help="Skriv debug till stderr.")
    p.add_argument(
        "-dbg_raw_input",
        "--debug-raw-input",
        action="store_true",
        help="Dumpa rå input mellan DEBUG_RAW_INPUT_START/END till stderr.",
    )
    return p


def main() -> int:
    args = build_arg_parser().parse_args()

    teams_file = Path(args.teams_file)
    output_dir = Path(args.output_directory)
    season = args.season
    dbg = args.debug
    dbg_raw_input = args.debug_raw_input

    if not teams_file.exists():
        print(f"TEAMS FILE saknas: {teams_file}", file=sys.stderr)
        return 2

    offline_map: Optional[Dict[str, Path]] = None
    if args.offline_file:
        offline_file = Path(args.offline_file)
        if not offline_file.exists():
            print(f"OFFLINE FILE saknas: {offline_file}", file=sys.stderr)
            return 2
        offline_map = parse_offline_mapping(offline_file, season, dbg)

    output_dir.mkdir(parents=True, exist_ok=True)

    teams = parse_teams_file(teams_file, season, dbg)
    if not teams:
        print("Inga lag hittades i TEAMS FILE.", file=sys.stderr)
        return 1

    all_players_file = output_dir / f"alla_spelare_{season}.txt"
    summary_file = output_dir / f"lag_summering_{season}.txt"

    old_all_players = backup_if_exists(all_players_file, dbg)
    old_summary = backup_if_exists(summary_file, dbg)

    roster_filenames: List[str] = []

    for team in teams:
        url = team["url"]
        roster_filename = team["roster_filename"]
        roster_path = output_dir / roster_filename
        roster_filenames.append(roster_filename)
        run_python_parser(url, season, roster_path, dbg, dbg_raw_input, offline_map)

    new_all_players = make_all_players_file(output_dir, season, roster_filenames, dbg)
    new_summary = make_team_summary_file(output_dir, season, roster_filenames, dbg)
    make_young_summary_file(output_dir, season, new_all_players, dbg)

    diff_all = save_diff(old_all_players, new_all_players, dbg)
    diff_summary = save_diff(old_summary, new_summary, dbg)

    print("Klar.")
    print(f"Rosterfiler skapade i: {output_dir}")
    print(f"Alla spelare: {new_all_players}")
    print(f"Lag summering: {new_summary}")
    print(f"Diff alla spelare: {diff_all}")
    print(f"Diff lag summering: {diff_summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
