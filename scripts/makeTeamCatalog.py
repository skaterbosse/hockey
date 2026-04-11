#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_SEASON = "2026-2027"
DEFAULT_INPUT_FOLDER = "./output"
DEFAULT_HISTORY_START = "2026-03-26 18:00"
TAB_ORDER = ["overview", "SHL", "HA", "HES", "HEN", "H2", "H3", "U20", "U18", "U16", "all-players", "search"]
COMPARE_MODES = [("day", "~1 dag", 1), ("three", "~3 dag", 3), ("week", "~1 vecka", 7), ("fourweek", "~4 vecka", 28)]


def debug(msg: str, enabled: bool) -> None:
    if enabled:
        print(f"[DEBUG] {msg}", file=sys.stderr)


def escape_nbsp(s: str) -> str:
    return html.escape(s).replace(" ", "&nbsp;")


def classify_position(pos: str) -> str:
    p = (pos or "").upper()
    if p == "G":
        return "G"
    if "D" in p and "G" not in p:
        return "D"
    return "F"


def compute_team_stats(team: Dict[str, Any]) -> Dict[str, Any]:
    g = d = f = 0
    years = []
    for p in team.get("players", []):
        cls = classify_position(p.get("position", ""))
        if cls == "G":
            g += 1
        elif cls == "D":
            d += 1
        else:
            f += 1
        try:
            years.append(int(p.get("birthyear")))
        except Exception:
            pass
    avg = None
    med = None
    if years:
        ages = [2026 - y + 0.5 for y in years]
        avg = sum(ages) / len(ages)
        ys = sorted(years)
        med = ys[len(ys)//2]
    return {"G": g, "D": d, "F": f, "avg": avg, "med": med}


def render_dist_block(stats: Dict[str, Any]) -> str:
    return (
        "<span class='overview-dist'>"
        "["
        f"<span class='dist-part'>G<span class='dist-num'>{stats['G']}</span></span>"
        "|"
        f"<span class='dist-part'>D<span class='dist-num'>{stats['D']}</span></span>"
        "|"
        f"<span class='dist-part'>F<span class='dist-num'>{stats['F']}</span></span>"
        "]"
        "</span>"
    )


def normalize_logo_path(p: str) -> str:
    return p if p.endswith("/") else p + "/"


def season_to_title(season: str) -> str:
    return season.replace("-", "/")


def format_dt_minute(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "okänd tid"


def tab_group_from_shortname(shortname: str) -> Optional[str]:
    s = (shortname or "").strip().upper()
    if s == "SHL":
        return "SHL"
    if s == "HA":
        return "HA"
    if s == "HES":
        return "HES"
    if s == "HEN":
        return "HEN"
    if s.startswith("H2"):
        return "H2"
    if s.startswith("H3"):
        return "H3"
    if s.startswith("U20"):
        return "U20"
    if s.startswith("U18"):
        return "U18"
    if s.startswith("U16"):
        return "U16"
    return None


def categorize_position(pos: str) -> str:
    p = (pos or "").upper()
    if p == "G":
        return "goalies"
    if "D" in p and "G" not in p:
        return "defence"
    return "forwards"


def parse_player_line(line: str) -> Optional[Dict[str, str]]:
    parts = [p.strip() for p in line.split(";")]
    if len(parts) < 4:
        return None
    return {
        "link": parts[0],
        "name": parts[1],
        "position_raw": parts[2],
        "birthyear": parts[3],
    }



def parse_series_file(seriesfile: Optional[Path], dbg: bool) -> Dict[str, Dict[str, str]]:
    series_map: Dict[str, Dict[str, str]] = {}
    if seriesfile is None:
        return series_map
    with seriesfile.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(";")]
            if len(parts) < 3:
                print(f"ERROR: Ogiltig rad i series file på rad {lineno}: {line}", file=sys.stderr)
                continue
            shortname, main_name, logo_file = parts[:3]
            series_map[shortname] = {
                "shortname": shortname,
                "main_name": main_name,
                "logo_file": logo_file,
            }
            debug(f"Serie rad {lineno}: short={shortname} main={main_name} logo={logo_file}", dbg)
    return series_map


def parse_teams_file(teamsfile: Path, season: str, dbg: bool) -> List[Dict[str, str]]:
    teams: List[Dict[str, str]] = []
    with teamsfile.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(";")]
            if len(parts) < 6:
                print(f"ERROR: Ogiltig rad i teams file på rad {lineno}: {line}", file=sys.stderr)
                continue
            url, roster_file, series_name, series_shortname, team_name, logo_file = parts[:6]
            roster_file = re.sub(r"\b20\d{2}-20\d{2}\b", season, roster_file)
            teams.append(
                {
                    "url": url,
                    "roster_file": roster_file,
                    "series_name": series_name,
                    "series_shortname": series_shortname,
                    "team_name": team_name,
                    "logo_file": logo_file,
                }
            )
    return teams


def read_roster_file(roster_path: Path, team_meta: Dict[str, str], dbg: bool) -> Dict[str, Any]:
    players: List[Dict[str, str]] = []
    if not roster_path.exists():
        print(f"ERROR: Rosterfil saknas: {roster_path}", file=sys.stderr)
    else:
        with roster_path.open("r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parsed = parse_player_line(line)
                if not parsed:
                    continue
                players.append(
                    {
                        "link": parsed["link"],
                        "name": parsed["name"],
                        "position": parsed["position_raw"],
                        "birthyear": parsed["birthyear"],
                        "team": team_meta["team_name"],
                        "serie": team_meta["series_name"],
                        "team_file": team_meta["roster_file"],
                    }
                )
    players.sort(key=lambda p: p["name"].lower())
    out = dict(team_meta)
    out["players"] = players
    out["player_count"] = len(players)
    return out


def find_roster_path(team: Dict[str, str], input_dir: Path) -> Path:
    return input_dir / team["roster_file"]


def parse_lag_summering_file(path: Path) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    if not path.exists():
        return counts
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            m = re.match(r"\s*(\d+)\s+(\S+)", raw.rstrip("\n"))
            if m:
                counts[m.group(2)] = int(m.group(1))
    return counts


def player_signature(player: Dict[str, str]) -> Tuple[str, str, str, str]:
    return (
        player.get("link", ""),
        player.get("name", ""),
        player.get("position", ""),
        player.get("birthyear", ""),
    )


def parse_all_players_file(path: Path) -> Dict[str, List[Dict[str, str]]]:
    result: Dict[str, List[Dict[str, str]]] = {}
    if path is None or not path.exists():
        return result
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(";")]
            if len(parts) < 5:
                continue
            team_file, link, name, position, birthyear = parts[:5]
            result.setdefault(team_file, []).append(
                {
                    "team_file": team_file,
                    "link": link,
                    "name": name,
                    "position": position,
                    "birthyear": birthyear,
                }
            )
    return result


def map_to_signature_dict(state_map: Dict[str, List[Dict[str, str]]]) -> Dict[Tuple[str, str, str, str, str], Dict[str, str]]:
    out: Dict[Tuple[str, str, str, str, str], Dict[str, str]] = {}
    for team_file, players in state_map.items():
        for p in players:
            sig = (team_file, p["link"], p["name"], p["position"], p["birthyear"])
            out[sig] = dict(p)
    return out


def signature_dict_to_map(sig_dict: Dict[Tuple[str, str, str, str, str], Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    out: Dict[str, List[Dict[str, str]]] = {}
    for p in sig_dict.values():
        out.setdefault(p["team_file"], []).append(dict(p))
    for team_file in out:
        out[team_file].sort(key=lambda p: p["name"].lower())
    return out


def build_diff_from_snapshots(
    current_map: Dict[str, List[Dict[str, str]]],
    compare_map: Dict[str, List[Dict[str, str]]],
) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    result: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
    all_team_files = sorted(set(current_map.keys()) | set(compare_map.keys()))
    for team_file in all_team_files:
        current_players = current_map.get(team_file, [])
        compare_players = compare_map.get(team_file, [])
        current_by_sig = {player_signature(p): p for p in current_players}
        compare_by_sig = {player_signature(p): p for p in compare_players}
        added = [current_by_sig[sig] for sig in sorted(set(current_by_sig) - set(compare_by_sig))]
        removed = [compare_by_sig[sig] for sig in sorted(set(compare_by_sig) - set(current_by_sig))]
        result[team_file] = {"added": added, "removed": removed}
    return result


def build_overview_players(team: Dict[str, Any], diff_map: Dict[str, Dict[str, List[Dict[str, str]]]], changes_only: bool = False) -> List[Dict[str, str]]:
    current_players: List[Dict[str, str]] = []
    diff_entry = diff_map.get(team["roster_file"], {"added": [], "removed": []})
    added_set = {player_signature(p) for p in diff_entry.get("added", [])}
    current_set = {player_signature(p) for p in team["players"]}

    for p in team["players"]:
        row = dict(p)
        row["status"] = "added" if player_signature(p) in added_set else "current"
        if not changes_only or row["status"] != "current":
            current_players.append(row)

    removed_players: List[Dict[str, str]] = []
    for p in diff_entry.get("removed", []):
        sig = player_signature(p)
        if sig in current_set:
            continue
        removed_players.append(
            {
                "link": p["link"],
                "name": p["name"],
                "position": p["position"],
                "birthyear": p["birthyear"],
                "team": team["team_name"],
                "serie": team["series_name"],
                "team_file": team["roster_file"],
                "status": "removed",
            }
        )

    rows = current_players + removed_players
    rows.sort(key=lambda p: (0 if p.get("status") == "added" else 1 if p.get("status") == "removed" else 2, p["name"].lower()))
    return rows


def player_line_html(p: Dict[str, str], compact: bool = False, css_class: str = "player") -> str:
    name = html.escape(p["name"])
    link = html.escape(p["link"])
    pos = html.escape(p.get("position", ""))
    birth = html.escape(p.get("birthyear", ""))
    if compact:
        return f"<div class='{css_class}'><a href=\"{link}\">{name}</a> — {pos} · {birth}</div>"
    team = html.escape(p.get("team", ""))
    serie = html.escape(p.get("serie", ""))
    return f"<div class='{css_class}'><a href=\"{link}\">{name}</a> — {pos} · {birth} · {serie} · {team}</div>"


def player_line_overview_html(p: Dict[str, str]) -> str:
    cls = "player"
    if p.get("status") == "added":
        cls += " player-added"
    elif p.get("status") == "removed":
        cls += " player-removed"
    return player_line_html(p, compact=True, css_class=cls)


def render_team_players(players: List[Dict[str, str]], overview_mode: bool = False) -> List[str]:
    html_parts: List[str] = []
    for cat, label in [("goalies", "Målvakter"), ("defence", "Backar"), ("forwards", "Forwards")]:
        cat_players = [p for p in players if categorize_position(p.get("position", "")) == cat]
        if not cat_players:
            continue
        html_parts.append(f"<h3>{label}</h3>")
        for p in cat_players:
            html_parts.append(player_line_overview_html(p) if overview_mode else player_line_html(p, compact=True))
    return html_parts


def build_tab_series(teams: List[Dict[str, Any]]) -> Dict[str, List[Tuple[str, List[Dict[str, Any]]]]]:
    grouped: Dict[str, List[Tuple[str, List[Dict[str, Any]]]]] = {k: [] for k in ["SHL", "HA", "HES", "HEN", "H2", "H3", "U20", "U18", "U16"]}
    series_order: Dict[str, List[str]] = {k: [] for k in grouped}
    series_map: Dict[str, Dict[str, List[Dict[str, Any]]]] = {k: {} for k in grouped}
    for team in teams:
        tab = tab_group_from_shortname(team["series_shortname"])
        if not tab:
            continue
        series_name = team["series_name"]
        if series_name not in series_map[tab]:
            series_map[tab][series_name] = []
            series_order[tab].append(series_name)
        series_map[tab][series_name].append(team)
    for tab in grouped:
        grouped[tab] = []
        for name in series_order[tab]:
            grouped[tab].append((name, sorted(series_map[tab][name], key=lambda t: t["team_name"].lower())))
    return grouped



def parse_history_start(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError(
        f"Ogiltigt format för -hs/--history-start: {value!r}. "
        "Använd YYYY-MM-DD eller YYYY-MM-DD HH:MM"
    )


def build_diff_map_from_diff_item(diff_item: Dict[str, Any]) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    diff_map: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
    for p in diff_item.get("added", []):
        diff_map.setdefault(p["team_file"], {"added": [], "removed": []})["added"].append(p)
    for p in diff_item.get("removed", []):
        diff_map.setdefault(p["team_file"], {"added": [], "removed": []})["removed"].append(p)
    return diff_map


def build_history_block(
    teams: List[Dict[str, Any]],
    grouped_tabs: Dict[str, List[Tuple[str, List[Dict[str, Any]]]]],
    overview_counts: Dict[str, int],
    diff_items: List[Dict[str, Any]],
    history_start: datetime,
    logo_path_html: str,
) -> List[str]:
    html_parts: List[str] = []
    html_parts.append(f"<h1>Historik efter {html.escape(format_dt_minute(history_start))}</h1>")

    filtered_items = [
        item for item in sorted(diff_items, key=lambda x: x["new_ts"], reverse=True)
        if item.get("new_ts") and item["new_ts"] >= history_start
    ]

    if not filtered_items:
        html_parts.append("<p>Ingen historik hittades inom valt intervall.</p>")
        return html_parts

    team_by_file = {team["roster_file"]: team for team in teams}
    ordered_team_files: List[str] = []
    for tab in ["SHL", "HA", "HES", "HEN", "H2", "H3", "U20", "U18", "U16"]:
        for _, series_teams in grouped_tabs[tab]:
            for team in series_teams:
                ordered_team_files.append(team["roster_file"])

    for item in filtered_items:
        html_parts.append(f"<h2>Spelarförändringar [{html.escape(format_dt_minute(item['new_ts']))}]</h2>")
        diff_map = build_diff_map_from_diff_item(item)

        changed_files = [
            team_file for team_file in ordered_team_files
            if team_file in diff_map and (diff_map[team_file].get("added") or diff_map[team_file].get("removed"))
        ]

        if not changed_files:
            html_parts.append("<p>Inga förändringar.</p>")
            continue

        for team_file in changed_files:
            team = team_by_file.get(team_file)
            if not team:
                continue
            count = overview_counts.get(team["roster_file"], team["player_count"])
            logo_html = f"<img src='{html.escape(logo_path_html + team['logo_file'])}' class='team-logo'>" if team.get("logo_file") else ""
            stats = compute_team_stats(team)
            dist_html = render_dist_block(stats)
            summary = (
                "<div class='overview-team-summary'>"
                f"<span class='overview-count'>{count}</span>"
                f"{dist_html}"
                f"<span class='overview-logo-slot'>{logo_html}</span>"
                f"<span>{escape_nbsp(team['team_name'])}</span>"
                f"<span class='overview-serie'>{html.escape(team['series_name'])}</span>"
                "</div>"
            )
            html_parts.append(f"<details open><summary>{summary}</summary>")
            html_parts.extend(render_team_players(build_overview_players(team, diff_map, changes_only=True), overview_mode=True))
            html_parts.append("</details>")

    return html_parts


def parse_diff_timestamp_from_header(header_line: str) -> Optional[datetime]:
    m = re.search(r"\t(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", header_line)
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") if m else None


def parse_all_players_diff_file(diff_path: Path) -> Dict[str, Any]:
    added: List[Dict[str, str]] = []
    removed: List[Dict[str, str]] = []
    old_ts: Optional[datetime] = None
    new_ts: Optional[datetime] = None
    with diff_path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.startswith("--- "):
                old_ts = parse_diff_timestamp_from_header(line)
                continue
            if line.startswith("+++ "):
                new_ts = parse_diff_timestamp_from_header(line)
                continue
            if not line or line.startswith("@@") or line.startswith("Inga skillnader"):
                continue
            if line[0] not in "+-":
                continue
            parts = [p.strip() for p in line[1:].split(";")]
            if len(parts) < 5:
                continue
            item = {"team_file": parts[0], "link": parts[1], "name": parts[2], "position": parts[3], "birthyear": parts[4]}
            if line[0] == "+":
                added.append(item)
            else:
                removed.append(item)
    return {"path": diff_path, "old_ts": old_ts, "new_ts": new_ts, "added": added, "removed": removed}


def list_all_players_diffs(input_dir: Path, season: str, dbg: bool) -> List[Dict[str, Any]]:
    items = []
    for p in sorted(input_dir.glob(f"alla_spelare_{season}_diff_*.txt")):
        item = parse_all_players_diff_file(p)
        if item["new_ts"] is not None:
            items.append(item)
            debug(f"Diff {p.name}: old={item['old_ts']} new={item['new_ts']} +{len(item['added'])} -{len(item['removed'])}", dbg)
    items.sort(key=lambda x: x["new_ts"])
    return items


def reconstruct_run_states_from_diffs(current_map: Dict[str, List[Dict[str, str]]], diff_items: List[Dict[str, Any]], dbg: bool) -> List[Dict[str, Any]]:
    if not diff_items:
        return []
    states: List[Dict[str, Any]] = []
    sig_dict = map_to_signature_dict(current_map)
    states.append({"ts": diff_items[-1]["new_ts"], "map": signature_dict_to_map(sig_dict)})
    for i in range(len(diff_items) - 1, 0, -1):
        diff_item = diff_items[i]
        for p in diff_item["added"]:
            sig_dict.pop((p["team_file"], p["link"], p["name"], p["position"], p["birthyear"]), None)
        for p in diff_item["removed"]:
            sig_dict[(p["team_file"], p["link"], p["name"], p["position"], p["birthyear"])] = dict(p)
        states.append({"ts": diff_items[i - 1]["new_ts"], "map": signature_dict_to_map(sig_dict)})
        debug(f"Rekonstruerad state för {diff_items[i - 1]['new_ts']}", dbg)
    states.sort(key=lambda x: x["ts"])
    return states


def choose_compare_state(current_ts: datetime, states: List[Dict[str, Any]], target_days: int) -> Optional[Dict[str, Any]]:
    older = [s for s in states if s["ts"] < current_ts]
    if not older:
        return None
    scored = []
    for s in older:
        delta_days = abs((current_ts - s["ts"]).total_seconds() / 86400.0 - target_days)
        scored.append((delta_days, s["ts"], s))
    scored.sort(key=lambda x: (x[0], x[1]))
    return scored[0][2]


def team_has_changes(team: Dict[str, Any], diff_map: Dict[str, Dict[str, List[Dict[str, str]]]]) -> bool:
    entry = diff_map.get(team["roster_file"], {"added": [], "removed": []})
    return bool(entry.get("added") or entry.get("removed"))


def build_overview_mode_block(mode_id: str, teams: List[Dict[str, Any]], grouped_tabs: Dict[str, List[Tuple[str, List[Dict[str, Any]]]]], overview_counts: Dict[str, int], diff_map: Dict[str, Dict[str, List[Dict[str, str]]]], compare_ts: Optional[datetime], current_ts: Optional[datetime], logo_path_html: str) -> List[str]:
    html_parts: List[str] = []
    html_parts.append(f"<div class='overview-mode-block' id='overview-mode-{mode_id}'>")
    html_parts.append(f"<h1>Spelarförändringar [{html.escape(format_dt_minute(compare_ts))} - {html.escape(format_dt_minute(current_ts))}]</h1>")
    html_parts.append("<div class='legend'><span class='added'>Nya spelare</span><span class='removed'>Förlorade spelare</span></div>")
    changed_teams: List[Dict[str, Any]] = []
    for tab in ["SHL", "HA", "HES", "HEN", "H2", "H3", "U20", "U18", "U16"]:
        for _, series_teams in grouped_tabs[tab]:
            for team in series_teams:
                if team_has_changes(team, diff_map):
                    changed_teams.append(team)
    for team in changed_teams:
        logo_html = f"<img src='{html.escape(logo_path_html + team['logo_file'])}' class='team-logo'>" if team.get("logo_file") else ""
        stats = compute_team_stats(team)
        dist_html = render_dist_block(stats)
        summary = ("<div class='overview-team-summary'>"
                   f"<span class='overview-count'>{overview_counts.get(team['roster_file'], team['player_count'])}</span>"
                   f"{dist_html}"
                   f"<span class='overview-logo-slot'>{logo_html}</span>"
                   f"<span>{escape_nbsp(team['team_name'])}</span>"
                   f"<span class='overview-serie'>{html.escape(team['series_name'])}</span>"
                   "</div>")
        html_parts.append(f"<details open><summary>{summary}</summary>")
        html_parts.extend(render_team_players(build_overview_players(team, diff_map, changes_only=True), overview_mode=True))
        html_parts.append("</details>")
    html_parts.append(f"<h1>Antal Spelare {html.escape(format_dt_minute(current_ts))}</h1>")
    html_parts.append("<div class='legend'><span class='added'>Nya spelare</span><span class='removed'>Förlorade spelare</span></div>")
    overview_teams = sorted(teams, key=lambda t: (-(overview_counts.get(t['roster_file'], t['player_count'])), t['team_name'].lower()))
    for team in overview_teams:
        count = overview_counts.get(team["roster_file"], team["player_count"])
        logo_html = f"<img src='{html.escape(logo_path_html + team['logo_file'])}' class='team-logo'>" if team.get("logo_file") else ""
        stats = compute_team_stats(team)
        dist_html = render_dist_block(stats)
        summary = ("<div class='overview-team-summary'>"
                   f"<span class='overview-count'>{count}</span>"
                   f"{dist_html}"
                   f"<span class='overview-logo-slot'>{logo_html}</span>"
                   f"<span>{escape_nbsp(team['team_name'])}</span>"
                   f"<span class='overview-serie'>{html.escape(team['series_name'])}</span>"
                   "</div>")
        html_parts.append(f"<details><summary>{summary}</summary>")
        html_parts.extend(render_team_players(build_overview_players(team, diff_map, changes_only=False), overview_mode=True))
        html_parts.append("</details>")
    html_parts.append("</div>")
    return html_parts


def generate_html(teams: List[Dict[str, Any]], all_players: List[Dict[str, str]], output_path: Path, title: str, logo_path_html: str, overview_counts: Dict[str, int], compare_blocks: List[Dict[str, Any]], series_info: Dict[str, Dict[str, str]], diff_items: List[Dict[str, Any]], history_start: datetime) -> None:
    grouped_tabs = build_tab_series(teams)
    html_parts: List[str] = []
    html_parts.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
    html_parts.append(f"<title>{html.escape(title)}</title>")
    html_parts.append("""
<style>
body { font-family: Arial, sans-serif; margin: 0; padding: 0; }
nav { position: sticky; top: 0; z-index: 1000; background: #333; color: white; padding: 1em; display: flex; flex-wrap: wrap; font-size: 1.25em; gap: 0.8em; }
nav a { color: white; text-decoration: none; }
nav a:hover { text-decoration: underline; }
section { display: none; padding: 1em; }
section.active { display: block; }
.player { border-bottom: 1px solid #ddd; padding: 4px 0; font-size: 1.15em; }
.player-added { color: #0a7a25; background: #eefbf0; }
.player-removed { color: #b00020; background: #fff1f1; text-decoration: line-through; }
details { margin-bottom: 0.5em; }
.team-logo { margin-right: 0.5em; max-height: 2.2em; vertical-align: middle; }
summary { font-weight: bold; cursor: pointer; padding: 0.35em 0.5em; background: #eee; border: 1px solid #ccc; border-radius: 4px; font-size: 1.45em; display: flex; align-items: center; gap: 0.5em; }
h1 { margin-top: 1em; }
h2.serie-title { background:#444; color:white; padding:0.4em 0.6em; border-radius:6px; font-size:1.35em; }
.overview-summary { display: grid; grid-template-columns: 3ch auto 3em 1fr auto; align-items: center; width: 100%; gap: 0.6em; }
.overview-count { font-variant-numeric: tabular-nums; display:inline-block; min-width:2ch; text-align:right; }
.overview-serie { font-size: 0.8em; color: #444; margin-left: auto; }
.overview-dist { font-family: monospace; font-size: 0.9em; white-space: nowrap; display:inline-block; min-width:14ch; }
.series-team-summary { display:grid; grid-template-columns: 3ch auto 3em 1fr auto; align-items:center; width:100%; gap:0.6em; }
.series-logo-slot { display:inline-flex; align-items:center; justify-content:flex-start; width:3em; }
.overview-team-summary { display:grid; grid-template-columns: 3ch auto 3em 1fr auto; align-items:center; width:100%; gap:0.6em; }
.overview-logo-slot { display:inline-flex; align-items:center; justify-content:flex-start; width:3em; }
.dist-part { display:inline; }
.dist-num { display:inline-block; min-width:2ch; text-align:right; }
.series-header-row { display: inline-flex; align-items: center; gap: 0.8em; }
.series-logo { max-height: 2.2em; vertical-align: middle; }
.legend { margin: 1em 0; display: flex; gap: 1em; flex-wrap: wrap; }
.legend span { padding: 0.2em 0.4em; border-radius: 4px; border: 1px solid #ccc; }
.legend .added { background: #eefbf0; color: #0a7a25; }
.legend .removed { background: #fff1f1; color: #b00020; text-decoration: line-through; }
#searchBox { width:100%; padding:0.5em; font-size:1em; }
.compare-controls { display:flex; align-items:center; gap:1.25em; flex-wrap:wrap; margin: 0.5em 0 1em 0; }
.compare-controls label { display:inline-flex; align-items:center; gap:0.35em; font-size:1.05em; }
.overview-mode-block { display:none; }
.overview-mode-block.active { display:block; }
.hidden { display:none; }
.toggle-all { display:inline-block; margin: 0.5em 0 1em 0; }
</style>
<script>
function showPage(id, updateHash = true) {
  var secs = document.querySelectorAll("section");
  secs.forEach(s => s.classList.remove("active"));
  var el = document.getElementById(id);
  if (el) { el.classList.add("active"); }
  if (updateHash) {
    history.replaceState(null, "", "#" + id);
  }
  window.scrollTo(0, 0);
}
function renderSearchResults(query) {
  let container = document.getElementById("searchResults");
  container.innerHTML = "";
  if (!query) return;
  let q = query.toLowerCase();
  let filtered = allPlayers.filter(p =>
    p.name.toLowerCase().includes(q) ||
    p.team.toLowerCase().includes(q) ||
    p.serie.toLowerCase().includes(q)
  );
  if (filtered.length === 0) {
    container.innerHTML = "<p>Inga spelare hittades.</p>";
    return;
  }
  filtered.forEach(p => {
    let div = document.createElement("div");
    div.className = "player";
    div.innerHTML = `<a href="${p.link}">${p.name}</a> — ${p.position} · ${p.birthyear} · ${p.serie} · ${p.team}`;
    container.appendChild(div);
  });
}
function toggleSeriesSort(tab, enabled) {
  const section = document.getElementById(tab);
  if (!section) return;
  section.querySelectorAll(".series-group").forEach(group => {
    const items = Array.from(group.querySelectorAll("details[data-player-count][data-team-name]"));
    items.sort((a, b) => {
      if (enabled) {
        const ca = parseInt(a.getAttribute("data-player-count") || "0", 10);
        const cb = parseInt(b.getAttribute("data-player-count") || "0", 10);
        if (cb !== ca) return cb - ca;
      }
      const na = (a.getAttribute("data-team-name") || "").toLowerCase();
      const nb = (b.getAttribute("data-team-name") || "").toLowerCase();
      return na.localeCompare(nb);
    });
    items.forEach(item => group.appendChild(item));
  });
}

function updateOverviewMode(mode) {
  document.querySelectorAll(".overview-mode-block").forEach(el => el.classList.remove("active"));
  var block = document.getElementById("overview-mode-" + mode);
  if (block) block.classList.add("active");
}
window.addEventListener("DOMContentLoaded", () => {
  var h = location.hash.replace('#','');
  if (h && document.getElementById(h)) {
    showPage(h, false);
  } else {
    showPage("overview", false);
  }
  document.querySelectorAll("nav a[data-target]").forEach(a => {
    a.addEventListener("click", ev => { ev.preventDefault(); showPage(a.getAttribute("data-target")); return false; });
  });
  let searchBox = document.getElementById("searchBox");
  if (searchBox) searchBox.addEventListener("input", (e) => renderSearchResults(e.target.value));
  document.querySelectorAll("input[name='compare-mode']").forEach(r => r.addEventListener("change", ev => updateOverviewMode(ev.target.value)));
  let checked = document.querySelector("input[name='compare-mode']:checked");
  updateOverviewMode(checked ? checked.value : "day");
});
</script>
""")
    html_parts.append("</head><body>")
    nav_map = {"overview": "Översikt", "SHL": "SHL", "HA": "HA", "HES": "HES", "HEN": "HEN", "H2": "H2", "H3": "H3", "U20": "U20", "U18": "U18", "U16": "U16", "all-players": "Alla Spelare", "search": "Sök Spelare"}
    html_parts.append("<nav>")
    for tab in TAB_ORDER:
        html_parts.append(f"<a href='#{tab}' data-target='{tab}'>{nav_map[tab]}</a>")
    html_parts.append("</nav>")
    html_parts.append("<section id='overview' class='active'><div class='compare-controls'><span>Jämför senaste med:</span>")
    for i, (mode_id, mode_label, _) in enumerate(COMPARE_MODES):
        checked_attr = " checked" if i == 0 else ""
        html_parts.append(f"<label><input type='radio' name='compare-mode' value='{mode_id}'{checked_attr}> {html.escape(mode_label)}</label>")
    html_parts.append("</div>")
    for block in compare_blocks:
        html_parts.extend(build_overview_mode_block(block["mode_id"], teams, grouped_tabs, overview_counts, block["diff_map"], block["compare_ts"], block["current_ts"], logo_path_html))
    html_parts.extend(build_history_block(teams, grouped_tabs, overview_counts, diff_items, history_start, logo_path_html))
    html_parts.append("</section>")
    for tab in ["SHL", "HA", "HES", "HEN", "H2", "H3", "U20", "U18", "U16"]:
        series_header_html = html.escape(tab)
        header_info = series_info.get(tab, {})
        if header_info:
            logo_html = ""
            if header_info.get("logo_file"):
                logo_html = f"<img src='{html.escape(logo_path_html + header_info['logo_file'])}' class='series-logo'>"
            parts = [f"<span>{html.escape(tab)}</span>"]
            if logo_html:
                parts.append(f"<span>{logo_html}</span>")
            if header_info.get("main_name"):
                parts.append(f"<span>{html.escape(header_info.get('main_name', ''))}</span>")
            series_header_html = "<span class='series-header-row'>" + "".join(parts) + "</span>"
        html_parts.append(
            f"<section id='{tab}'><h1 style='display:flex;align-items:center;justify-content:space-between;gap:1em;'>"
            f"<span>{series_header_html}</span>"
            f"<label style='font-size:0.6em;font-weight:normal;white-space:nowrap;'>Antalsortering: <input type='checkbox' checked onchange=\"toggleSeriesSort('{tab}', this.checked)\"></label>"
            f"</h1>"
        )
        for series_name, series_teams in grouped_tabs[tab]:
            html_parts.append(f"<h2 class='serie-title'>{html.escape(series_name)}</h2>")
            html_parts.append("<div class='series-group'>")
            for team in sorted(series_teams, key=lambda t: (-t["player_count"], t["team_name"].lower())):
                logo_html = f"<img src='{html.escape(logo_path_html + team['logo_file'])}' class='team-logo'>" if team.get("logo_file") else ""
                stats = compute_team_stats(team)
                dist_html = render_dist_block(stats)
                if stats["avg"] is not None:
                    avg_txt = f"{stats['avg']:.1f}".replace(".", ",")
                    age_block = f"[Avg: {avg_txt}|Med: {stats['med']}]"
                else:
                    age_block = "[Avg: -|-]"
                summary = (
                    "<div class='series-team-summary'>"
                    "<span class='overview-count'>"
                    f"{team['player_count']}"
                    "</span>"
                    f"{dist_html}"
                    f"<span class='series-logo-slot'>{logo_html}</span>"
                    f"<span>{escape_nbsp(team['team_name'])}</span>"
                    f"<span style='margin-left:auto'>{html.escape(age_block)}</span>"
                    "</div>"
                )
                html_parts.append(f"<details data-player-count='{team['player_count']}' data-team-name='{html.escape(team['team_name'], quote=True)}'><summary>{summary}</summary>")
                html_parts.extend(render_team_players(team["players"], overview_mode=False))
                html_parts.append("</details>")
            html_parts.append("</div>")
        html_parts.append("</section>")
    html_parts.append("<section id='all-players'><h1>Alla spelare</h1>")
    for p in all_players:
        html_parts.append(player_line_html(p))
    html_parts.append("</section>")
    html_parts.append("<section id='search'><h1>Sök Spelare</h1><input type='text' id='searchBox' placeholder='Skriv namn, lag eller serie...'><div id='searchResults'></div></section>")
    html_parts.append("<script>let allPlayers = " + json.dumps(all_players, ensure_ascii=False) + ";</script></body></html>")
    output_path.write_text("\n".join(html_parts), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Series and Teams HTML catalog.")
    parser.add_argument("-o", "--output", required=True, help="Output HTML file")
    parser.add_argument("-tf", "--teamsfile", required=True, help="Teams file with mapping")
    parser.add_argument("-sf", "--seriesfile", help="Series file: Serie kortnamn;Huvudserie namn;logo fil")
    parser.add_argument("-s", "--season", default=DEFAULT_SEASON, help=f"Season, default {DEFAULT_SEASON}")
    parser.add_argument("-if", "--input-folder", default=DEFAULT_INPUT_FOLDER, help="Folder with generated roster/output files")
    parser.add_argument("-lp", "--logopath", required=True, help="Logo path for HTML references")
    parser.add_argument("-lp_script", "--logopath_script", help="Local path for script to access logo files (defaults to -lp)")
    parser.add_argument("-dbg", "--debug", action="store_true", help="Verbose debug to stderr")
    parser.add_argument("-hs", "--history-start", default=DEFAULT_HISTORY_START, help="Historikstart, format YYYY-MM-DD eller YYYY-MM-DD HH:MM")
    args = parser.parse_args()

    dbg = args.debug
    history_start = parse_history_start(args.history_start)
    teamsfile = Path(args.teamsfile)
    input_dir = Path(args.input_folder)
    logo_path_html = normalize_logo_path(args.logopath)
    logo_path_script = normalize_logo_path(args.logopath_script or args.logopath)

    series_info = parse_series_file(Path(args.seriesfile) if args.seriesfile else None, dbg)
    teams_meta = parse_teams_file(teamsfile, args.season, dbg)
    teams: List[Dict[str, Any]] = []
    all_players: List[Dict[str, str]] = []
    for team_meta in teams_meta:
        roster_path = find_roster_path(team_meta, input_dir)
        team = read_roster_file(roster_path, team_meta, dbg)
        logo_full_path = Path(logo_path_script) / team_meta["logo_file"]
        if team_meta["logo_file"] and not logo_full_path.exists():
            print(f"Warning: Logo saknas för {team_meta['team_name']}: {logo_full_path}", file=sys.stderr)
        teams.append(team)
        all_players.extend(team["players"])
    all_players.sort(key=lambda p: p["name"].lower())

    current_summary_path = input_dir / f"lag_summering_{args.season}.txt"
    current_all_players_path = input_dir / f"alla_spelare_{args.season}.txt"
    overview_counts = parse_lag_summering_file(current_summary_path)
    current_map = parse_all_players_file(current_all_players_path)

    diff_items = list_all_players_diffs(input_dir, args.season, dbg)
    states = reconstruct_run_states_from_diffs(current_map, diff_items, dbg)
    current_ts = diff_items[-1]["new_ts"] if diff_items else datetime.fromtimestamp(current_all_players_path.stat().st_mtime)

    compare_blocks: List[Dict[str, Any]] = []
    for mode_id, mode_label, target_days in COMPARE_MODES:
        chosen_state = choose_compare_state(current_ts, states, target_days)
        compare_map = chosen_state["map"] if chosen_state else {}
        compare_ts = chosen_state["ts"] if chosen_state else None
        diff_map = build_diff_from_snapshots(current_map, compare_map)
        compare_blocks.append({"mode_id": mode_id, "mode_label": mode_label, "compare_ts": compare_ts, "current_ts": current_ts, "diff_map": diff_map})

    title = f"Series and Teams Catalog {season_to_title(args.season)}"
    generate_html(teams, all_players, Path(args.output), title, logo_path_html, overview_counts, compare_blocks, series_info, diff_items, history_start)
    print(f"Wrote HTML catalog to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
