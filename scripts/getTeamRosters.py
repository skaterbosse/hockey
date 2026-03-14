#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import datetime as _dt
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List


DEFAULT_SEASON = "2026-2027"
SEASON_RE = re.compile(r"\b20\d{2}-20\d{2}\b")
HISTORY_RETENTION_DAYS = 31


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


def run_shell_pipeline(url: str, season: str, output_file: Path, dbg: bool) -> None:
    shell_cmd = f"""curl -L -s {shlex.quote(url)} | egrep -a {shlex.quote(season)} | sed 's/https/\\nhttps/g' | egrep -n -B 20000 '<!-- --> Staff' | egrep -A 20000 'Jersey Number' | egrep 'href=\\"/player/|<span title=\\"[1-2][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]\\">[1-2][0-9][0-9][0-9]<' | sed -E "s/.*href=\\"\\/player\\//href=\\"\\/player\\//" | sed -E "s/<\\/a><\\/div>.*span title=\\"[1-2][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]\\">([1-2][0-9][0-9][0-9])<.*/;BIRTYEAR\\1/" | sed -E "s/.*span title=\\"[1-2][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]\\">([1-2][0-9][0-9][0-9])<.*/;_BIRTYEAR\\1/" | tr '\\n' ' ' | sed -E "s/href=\\"\\/player\\//\\nhref=\\"\\/player\\//g" | sed -E "s/<\\/a><span class=.*BIRTYEAR/;/" | sed -E "s/)<\\/a><a class=.*;BIRTYEAR/;/" | sed 's/);BIRTYEAR/;/' | sed -E "s/\\">/;/" | sed -E "s/<\\!\\-\\-.*\\-\\->\\(/;/" | sed -E "s/\\);/;/" | sed -E "s/^href=\\"/https:\\/\\/www\\.eliteprospects\\.com/" | sed -E "s/)<\\/a><a class=.*;/;/" > {shlex.quote(str(output_file))}"""
    debug(f"Kör pipeline för {url}", dbg)
    res = subprocess.run(shell_cmd, shell=True, executable="/bin/bash", capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Pipeline misslyckades för {url}\nSTDERR:\n{res.stderr}\nSTDOUT:\n{res.stdout}")
    if dbg and res.stderr:
        print(res.stderr, file=sys.stderr, end="")


def parse_teams_file(teams_file: Path, season: str, dbg: bool) -> List[Dict[str, str]]:
    teams: List[Dict[str, str]] = []
    for lineno, raw in enumerate(teams_file.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 6:
            raise ValueError(f"Fel format i {teams_file} rad {lineno}: förväntade minst 6 kolumner, fick {len(parts)}: {raw}")
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
            f"Team rad {lineno}: {team['url']} -> {team['roster_filename']} ({team['series']} / {team['series_shortname']} / {team['team_name']} / {team['logo_filename']})",
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
    write_text(diff_file, res.stdout if res.stdout else "Inga skillnader.\n")
    debug(f"Skapade diff-fil {diff_file}", dbg)
    return diff_file


def save_history_snapshot(file_path: Path, output_dir: Path, season: str, prefix: str, dbg: bool) -> Path:
    history_dir = output_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    date_tag = _dt.datetime.now().strftime("%Y%m%d")
    snapshot = history_dir / f"{prefix}_{season}_{date_tag}.txt"
    shutil.copy2(file_path, snapshot)
    debug(f"Historik-snapshot sparad: {snapshot}", dbg)
    return snapshot


def purge_old_history(output_dir: Path, season: str, dbg: bool) -> None:
    history_dir = output_dir / "history"
    if not history_dir.exists():
        return
    cutoff = _dt.datetime.now() - _dt.timedelta(days=HISTORY_RETENTION_DAYS)
    pattern = re.compile(rf"^(alla_spelare|lag_summering)_{re.escape(season)}_(\d{{8}})\.txt$")
    for path in history_dir.iterdir():
        m = pattern.match(path.name)
        if not m:
            continue
        try:
            snap_dt = _dt.datetime.strptime(m.group(2), "%Y%m%d")
        except ValueError:
            continue
        if snap_dt < cutoff:
            path.unlink(missing_ok=True)
            debug(f"Raderade gammal historikfil: {path}", dbg)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="getTeamRosters.py", description="Hämtar aktuella rosters från Eliteprospects och skapar roster-, summerings- och diff-filer.")
    p.add_argument("-tf", "--teams-file", required=True, help="Path till TEAMS FILE.")
    p.add_argument("-s", "--season", default=DEFAULT_SEASON, help=f"Säsong, default {DEFAULT_SEASON}.")
    p.add_argument("-od", "--output-directory", required=True, help="Katalog där genererade filer sparas.")
    p.add_argument("-dbg", "--debug", action="store_true", help="Skriv debug till stderr.")
    return p


def main() -> int:
    args = build_arg_parser().parse_args()
    teams_file = Path(args.teams_file)
    output_dir = Path(args.output_directory)
    season = args.season
    dbg = args.debug

    if not teams_file.exists():
        print(f"TEAMS FILE saknas: {teams_file}", file=sys.stderr)
        return 2

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
        run_shell_pipeline(url, season, roster_path, dbg)

    new_all_players = make_all_players_file(output_dir, season, roster_filenames, dbg)
    new_summary = make_team_summary_file(output_dir, season, roster_filenames, dbg)
    make_young_summary_file(output_dir, season, new_all_players, dbg)

    diff_all = save_diff(old_all_players, new_all_players, dbg)
    diff_summary = save_diff(old_summary, new_summary, dbg)

    save_history_snapshot(new_all_players, output_dir, season, "alla_spelare", dbg)
    save_history_snapshot(new_summary, output_dir, season, "lag_summering", dbg)
    purge_old_history(output_dir, season, dbg)

    print("Klar.")
    print(f"Rosterfiler skapade i: {output_dir}")
    print(f"Alla spelare: {new_all_players}")
    print(f"Lag summering: {new_summary}")
    print(f"Diff alla spelare: {diff_all}")
    print(f"Diff lag summering: {diff_summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
