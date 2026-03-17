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
TAB_ORDER = ["overview", "SHL", "HA", "HES", "HEN", "H2", "H3", "U20", "U18", "U16", "all-players", "search"]
COMPARE_MODES = [("day", "~ en dag", 1), ("week", "~ en vecka", 7), ("month", "~ en månad", 30)]


def debug(msg: str, enabled: bool) -> None:
    if enabled:
        print(f"[DEBUG] {msg}", file=sys.stderr)


def escape_nbsp(s: str) -> str:
    return html.escape(s).replace(" ", "&nbsp;")


def normalize_logo_path(p: str) -> str:
    return p if p.endswith("/") else p + "/"


def season_to_title(season: str) -> str:
    return season.replace("-", "/")


def format_ts(path: Optional[Path]) -> Optional[str]:
    if path is None or not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def html_ts(ts: Optional[str]) -> str:
    return html.escape(ts) if ts else "okänd tid"


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


def tab_sort_key(team: Dict[str, Any]) -> Tuple[int, str, str]:
    tab = tab_group_from_shortname(team["series_shortname"]) or "ZZZ"
    idx = TAB_ORDER.index(tab) if tab in TAB_ORDER else 999
    return (idx, team["series_name"].lower(), team["team_name"].lower())


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


def parse_teams_file(teamsfile: Path, season: str, dbg: bool) -> List[Dict[str, str]]:
    teams: List[Dict[str, str]] = []
    debug(f"Läser teams file: {teamsfile}", dbg)
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
            team = {
                "url": url,
                "roster_file": roster_file,
                "series_name": series_name,
                "series_shortname": series_shortname,
                "team_name": team_name,
                "logo_file": logo_file,
            }
            teams.append(team)
            debug(f"Team rad {lineno}: roster={roster_file} serie={series_name} short={series_shortname} team={team_name} logo={logo_file}", dbg)
    debug(f"Antal team inlästa: {len(teams)}", dbg)
    return teams


def read_roster_file(roster_path: Path, team_meta: Dict[str, str], dbg: bool) -> Dict[str, Any]:
    players: List[Dict[str, str]] = []
    debug(f"Läser rosterfil: {roster_path}", dbg)
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


def build_overview_players(
    team: Dict[str, Any],
    diff_map: Dict[str, Dict[str, List[Dict[str, str]]]],
    changes_only: bool = False,
) -> List[Dict[str, str]]:
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
    grouped: Dict[str, List[Tuple[str, List[Dict[str, Any]]]]] = {
        "SHL": [], "HA": [], "HES": [], "HEN": [], "H2": [], "H3": [], "U20": [], "U18": [], "U16": []
    }
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
            teams_sorted = sorted(series_map[tab][name], key=lambda t: t["team_name"].lower())
            grouped[tab].append((name, teams_sorted))
    return grouped


def list_history_files(history_dir: Path, prefix: str, season: str) -> List[Path]:
    files = sorted(history_dir.glob(f"{prefix}_{season}_*.txt"))
    dated: List[Tuple[str, Path]] = []
    for f in files:
        m = re.search(r"_(\d{8})\.txt$", f.name)
        if m:
            dated.append((m.group(1), f))
    return [p for _, p in sorted(dated)]


def choose_compare_history_file(current_path: Path, history_files: List[Path], target_days: int) -> Optional[Path]:
    if not current_path.exists() or not history_files:
        return None
    current_dt = datetime.fromtimestamp(current_path.stat().st_mtime)
    candidates: List[Tuple[float, datetime, Path]] = []
    older: List[Tuple[datetime, Path]] = []
    for p in history_files:
        if not p.exists():
            continue
        dt = datetime.fromtimestamp(p.stat().st_mtime)
        if dt < current_dt:
            older.append((dt, p))
            delta_days = abs((current_dt - dt).total_seconds() / 86400.0 - target_days)
            candidates.append((delta_days, dt, p))
    if candidates:
        candidates.sort(key=lambda x: (x[0], x[1]))
        return candidates[0][2]
    return None


def team_has_changes(team: Dict[str, Any], diff_map: Dict[str, Dict[str, List[Dict[str, str]]]]) -> bool:
    entry = diff_map.get(team["roster_file"], {"added": [], "removed": []})
    return bool(entry.get("added") or entry.get("removed"))


def build_overview_mode_block(
    mode_id: str,
    mode_label: str,
    teams: List[Dict[str, Any]],
    grouped_tabs: Dict[str, List[Tuple[str, List[Dict[str, Any]]]]],
    overview_counts: Dict[str, int],
    diff_map: Dict[str, Dict[str, List[Dict[str, str]]]],
    compare_ts: Optional[str],
    current_ts: Optional[str],
    logo_path_html: str,
    checked: bool,
) -> List[str]:
    html_parts: List[str] = []
    checked_attr = " checked" if checked else ""
    html_parts.append(f"<input type='radio' name='compare-mode' id='compare-{mode_id}' value='{mode_id}'{checked_attr}>")
    html_parts.append("")
    overview_teams = sorted(
        teams,
        key=lambda t: (-(overview_counts.get(t["roster_file"], t["player_count"])), t["team_name"].lower()),
    )

    html_parts.append(f"<div class='overview-mode-block' id='overview-mode-{mode_id}'>")
    html_parts.append(f"<h1>Spelarförändringar [{html_ts(compare_ts)} vs {html_ts(current_ts)}]</h1>")
    html_parts.append("<div class='legend'><span class='added'>Nya spelare</span><span class='removed'>Förlorade spelare</span></div>")

    changed_teams: List[Dict[str, Any]] = []
    for tab in ["SHL", "HA", "HES", "HEN", "H2", "H3", "U20", "U18", "U16"]:
        for series_name, series_teams in grouped_tabs[tab]:
            for team in series_teams:
                if team_has_changes(team, diff_map):
                    changed_teams.append(team)

    for team in changed_teams:
        logo_html = f"<img src='{html.escape(logo_path_html + team['logo_file'])}' class='team-logo'>" if team.get("logo_file") else ""
        summary = (
            "<div class='overview-summary'>"
            f"<span class='overview-count'>{overview_counts.get(team['roster_file'], team['player_count'])}</span>"
            f"<span>{logo_html}</span>"
            f"<span>{escape_nbsp(team['team_name'])}</span>"
            f"<span class='overview-serie'>{html.escape(team['series_name'])}</span>"
            "</div>"
        )
        html_parts.append(f"<details open><summary>{summary}</summary>")
        html_parts.extend(render_team_players(build_overview_players(team, diff_map, changes_only=True), overview_mode=True))
        html_parts.append("</details>")

    html_parts.append(f"<h1>Antal Spelare {html_ts(current_ts)}</h1>")
    html_parts.append(f"<div class='compare-note'>Jämförelsen använder snapshot från {html_ts(compare_ts)}</div>")
    html_parts.append("<div class='legend'><span class='added'>Nya spelare</span><span class='removed'>Förlorade spelare</span></div>")
    html_parts.append("<label class='toggle-all'><input type='checkbox' class='show-all-toggle' data-mode='%s'> visa alla spelare</label>" % mode_id)

    for team in overview_teams:
        count = overview_counts.get(team["roster_file"], team["player_count"])
        logo_html = f"<img src='{html.escape(logo_path_html + team['logo_file'])}' class='team-logo'>" if team.get("logo_file") else ""
        summary = (
            "<div class='overview-summary'>"
            f"<span class='overview-count'>{count}</span>"
            f"<span>{logo_html}</span>"
            f"<span>{escape_nbsp(team['team_name'])}</span>"
            f"<span class='overview-serie'>{html.escape(team['series_name'])}</span>"
            "</div>"
        )
        html_parts.append(f"<details><summary>{summary}</summary>")
        html_parts.append(f"<div class='overview-team-players' data-mode='{mode_id}'>")
        html_parts.append(f"<div class='players-changes-only'>")
        html_parts.extend(render_team_players(build_overview_players(team, diff_map, changes_only=True), overview_mode=True))
        html_parts.append("</div>")
        html_parts.append(f"<div class='players-all hidden'>")
        html_parts.extend(render_team_players(build_overview_players(team, diff_map, changes_only=False), overview_mode=True))
        html_parts.append("</div>")
        html_parts.append("</div>")
        html_parts.append("</details>")

    html_parts.append("</div>")
    return html_parts


def generate_html(
    teams: List[Dict[str, Any]],
    all_players: List[Dict[str, str]],
    output_path: Path,
    title: str,
    logo_path_html: str,
    overview_counts: Dict[str, int],
    compare_blocks: List[Dict[str, Any]],
) -> None:
    grouped_tabs = build_tab_series(teams)

    html_parts: List[str] = []
    html_parts.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
    html_parts.append(f"<title>{html.escape(title)}</title>")
    html_parts.append("""
<style>
body { font-family: Arial, sans-serif; margin: 0; padding: 0; }
nav { background: #333; color: white; padding: 1em; display: flex; flex-wrap: wrap; font-size: 1.25em; gap: 0.8em; }
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
.overview-summary { display: grid; grid-template-columns: 5.5em 3em 1fr auto; align-items: center; width: 100%; gap: 0.6em; }
.overview-count { font-variant-numeric: tabular-nums; }
.overview-serie { font-size: 0.8em; color: #444; margin-left: auto; }
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
.compare-note { color:#444; margin-bottom:0.75em; }
</style>
<script>
function showPage(id) {
  var secs = document.querySelectorAll("section");
  secs.forEach(s => s.classList.remove("active"));
  var el = document.getElementById(id);
  if (el) { el.classList.add("active"); }
  location.hash = id;
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
function updateOverviewMode(mode) {
  document.querySelectorAll(".overview-mode-block").forEach(el => el.classList.remove("active"));
  var block = document.getElementById("overview-mode-" + mode);
  if (block) block.classList.add("active");
}
function updateShowAll(mode, checked) {
  document.querySelectorAll(".overview-team-players[data-mode='" + mode + "']").forEach(el => {
    let a = el.querySelector(".players-all");
    let c = el.querySelector(".players-changes-only");
    if (!a || !c) return;
    if (checked) {
      a.classList.remove("hidden");
      c.classList.add("hidden");
    } else {
      a.classList.add("hidden");
      c.classList.remove("hidden");
    }
  });
}
window.addEventListener("DOMContentLoaded", () => {
  showPage("overview");
  var h = location.hash.replace('#','');
  if (h && document.getElementById(h)) { showPage(h); }
  document.querySelectorAll("nav a[data-target]").forEach(a => {
    a.addEventListener("click", ev => {
      ev.preventDefault();
      showPage(a.getAttribute("data-target"));
      return false;
    });
  });
  let searchBox = document.getElementById("searchBox");
  if (searchBox) {
    searchBox.addEventListener("input", (e) => renderSearchResults(e.target.value));
  }
  document.querySelectorAll("input[name='compare-mode']").forEach(r => {
    r.addEventListener("change", ev => updateOverviewMode(ev.target.value));
  });
  document.querySelectorAll(".show-all-toggle").forEach(c => {
    c.addEventListener("change", ev => updateShowAll(ev.target.getAttribute("data-mode"), ev.target.checked));
  });
  let checked = document.querySelector("input[name='compare-mode']:checked");
  updateOverviewMode(checked ? checked.value : "day");
});
</script>
""")
    html_parts.append("</head><body>")
    nav_map = {
        "overview": "Översikt", "SHL": "SHL", "HA": "HA", "HES": "HES", "HEN": "HEN",
        "H2": "H2", "H3": "H3", "U20": "U20", "U18": "U18", "U16": "U16",
        "all-players": "Alla Spelare", "search": "Sök Spelare",
    }
    html_parts.append("<nav>")
    for tab in TAB_ORDER:
        html_parts.append(f"<a href='#{tab}' data-target='{tab}'>{nav_map[tab]}</a>")
    html_parts.append("</nav>")

    html_parts.append("<section id='overview' class='active'>")
    html_parts.append("<div class='compare-controls'>")
    html_parts.append("<span>Jämför senast sparade spelare och lag med:</span>")
    for i, (mode_id, mode_label, _) in enumerate(COMPARE_MODES):
        checked_attr = " checked" if i == 0 else ""
        html_parts.append(f"<label><input type='radio' name='compare-mode' value='{mode_id}'{checked_attr}> {html.escape(mode_label)}</label>")
    html_parts.append("</div>")
    for block in compare_blocks:
        html_parts.extend(
            build_overview_mode_block(
                mode_id=block["mode_id"],
                mode_label=block["mode_label"],
                teams=teams,
                grouped_tabs=grouped_tabs,
                overview_counts=overview_counts,
                diff_map=block["diff_map"],
                compare_ts=block["compare_ts"],
                current_ts=block["current_ts"],
                logo_path_html=logo_path_html,
                checked=(block["mode_id"] == "day"),
            )
        )
    html_parts.append("</section>")

    for tab in ["SHL", "HA", "HES", "HEN", "H2", "H3", "U20", "U18", "U16"]:
        html_parts.append(f"<section id='{tab}'>")
        html_parts.append(f"<h1>{html.escape(tab)}</h1>")
        for series_name, series_teams in grouped_tabs[tab]:
            html_parts.append(f"<h2 class='serie-title'>{html.escape(series_name)}</h2>")
            for team in series_teams:
                logo_html = f"<img src='{html.escape(logo_path_html + team['logo_file'])}' class='team-logo'>" if team.get("logo_file") else ""
                html_parts.append(f"<details><summary>{logo_html}{escape_nbsp(team['team_name'])}</summary>")
                html_parts.extend(render_team_players(team["players"], overview_mode=False))
                html_parts.append("</details>")
        html_parts.append("</section>")

    html_parts.append("<section id='all-players'>")
    html_parts.append("<h1>Alla spelare</h1>")
    for p in all_players:
        html_parts.append(player_line_html(p))
    html_parts.append("</section>")

    html_parts.append("<section id='search'>")
    html_parts.append("<h1>Sök Spelare</h1>")
    html_parts.append("<input type='text' id='searchBox' placeholder='Skriv namn, lag eller serie...'>")
    html_parts.append("<div id='searchResults'></div>")
    html_parts.append("</section>")

    html_parts.append("<script>")
    html_parts.append("let allPlayers = " + json.dumps(all_players, ensure_ascii=False) + ";")
    html_parts.append("</script>")
    html_parts.append("</body></html>")
    output_path.write_text("\n".join(html_parts), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Series and Teams HTML catalog.")
    parser.add_argument("-o", "--output", required=True, help="Output HTML file")
    parser.add_argument("-tf", "--teamsfile", required=True, help="Teams file with mapping")
    parser.add_argument("-s", "--season", default=DEFAULT_SEASON, help=f"Season, default {DEFAULT_SEASON}")
    parser.add_argument("-if", "--input-folder", default=DEFAULT_INPUT_FOLDER, help="Folder with generated roster/output files")
    parser.add_argument("-lp", "--logopath", required=True, help="Logo path for HTML references")
    parser.add_argument("-lp_script", "--logopath_script", help="Local path for script to access logo files (defaults to -lp)")
    parser.add_argument("-dbg", "--debug", action="store_true", help="Verbose debug to stderr")
    args = parser.parse_args()

    dbg = args.debug
    teamsfile = Path(args.teamsfile)
    input_dir = Path(args.input_folder)
    history_dir = input_dir / "history"
    logo_path_html = normalize_logo_path(args.logopath)
    logo_path_script = normalize_logo_path(args.logopath_script or args.logopath)

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
    current_ts = format_ts(current_summary_path) or format_ts(current_all_players_path)

    history_all_players = list_history_files(history_dir, "alla_spelare", args.season)
    debug(f"History all_players filer: {[p.name for p in history_all_players]}", dbg)

    compare_blocks: List[Dict[str, Any]] = []
    for mode_id, mode_label, target_days in COMPARE_MODES:
        compare_all_players_path = choose_compare_history_file(current_all_players_path, history_all_players, target_days)
        compare_map = parse_all_players_file(compare_all_players_path) if compare_all_players_path else {}
        compare_ts = format_ts(compare_all_players_path)
        diff_map = build_diff_from_snapshots(current_map, compare_map)
        debug(f"Mode {mode_id}: compare file={compare_all_players_path} ts={compare_ts}", dbg)
        compare_blocks.append(
            {
                "mode_id": mode_id,
                "mode_label": mode_label,
                "compare_path": compare_all_players_path,
                "compare_ts": compare_ts,
                "current_ts": current_ts,
                "diff_map": diff_map,
            }
        )

    title = f"Series and Teams Catalog {season_to_title(args.season)}"
    generate_html(
        teams=teams,
        all_players=all_players,
        output_path=Path(args.output),
        title=title,
        logo_path_html=logo_path_html,
        overview_counts=overview_counts,
        compare_blocks=compare_blocks,
    )
    print(f"Wrote HTML catalog to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
