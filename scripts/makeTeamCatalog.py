#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import glob
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
COMPARE_MODES = [("day", "Näst senaste (en dag)", 1), ("week", "Cirka en vecka", 7), ("month", "Cirka en månad", 30)]


def debug(msg: str, enabled: bool) -> None:
    if enabled:
        print(f"[DEBUG] {msg}", file=sys.stderr)


def escape_nbsp(s: str) -> str:
    return html.escape(s).replace(" ", "&nbsp;")


def normalize_html_logo_path(p: str) -> str:
    return p if p.endswith("/") else p + "/"


def season_to_title(season: str) -> str:
    return season.replace("-", "/")


def format_ts_from_path(path: Optional[Path]) -> Optional[str]:
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


def tab_sort_index(team: Dict[str, Any]) -> int:
    tab = tab_group_from_shortname(team["series_shortname"]) or "ZZZ"
    return TAB_ORDER.index(tab) if tab in TAB_ORDER else 999


def categorize_position(pos: str) -> str:
    p = (pos or "").upper()
    if "G" in p:
        return "goalies"
    if "D" in p:
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
    debug(f"Spelare hittade i {roster_path.name}: {len(players)}", dbg)
    out = dict(team_meta)
    out["players"] = players
    out["player_count"] = len(players)
    return out


def find_roster_path(team: Dict[str, str], input_dir: Path) -> Path:
    return input_dir / team["roster_file"]


def parse_lag_summering_file(path: Path, dbg: bool) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    debug(f"Läser lag_summering: {path}", dbg)
    if not path.exists():
        print(f"ERROR: Summeringsfil saknas: {path}", file=sys.stderr)
        return counts
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            m = re.match(r"\s*(\d+)\s+(\S+)", raw.rstrip("\n"))
            if m:
                counts[m.group(2)] = int(m.group(1))
    return counts


def list_history_files(base_dir: Path, prefix: str, season: str, dbg: bool) -> List[Path]:
    history_dir = base_dir / "history"
    pattern = str(history_dir / f"{prefix}_{season}_*.txt")
    files = sorted(Path(p) for p in glob.glob(pattern))
    debug(f"Historikfiler för {prefix}: {len(files)} st", dbg)
    return files


def choose_snapshot(files: List[Path], target_days: int) -> Optional[Path]:
    if not files:
        return None
    now = datetime.now().date()
    ranked = []
    for path in files:
        m = re.search(r"_(\d{8})\.txt$", path.name)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        delta = (now - d).days
        if delta < 0:
            continue
        ranked.append((abs(delta - target_days), delta, path))
    if not ranked:
        return files[-1]
    ranked.sort(key=lambda x: (x[0], x[1]))
    return ranked[0][2]


def parse_all_players_snapshot(path: Optional[Path], dbg: bool) -> Dict[str, List[Dict[str, str]]]:
    result: Dict[str, List[Dict[str, str]]] = {}
    if path is None:
        return result
    debug(f"Läser snapshot för alla spelare: {path}", dbg)
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
                {"team_file": team_file, "link": link, "name": name, "position": position, "birthyear": birthyear}
            )
    for team_file in result:
        result[team_file].sort(key=lambda p: p["name"].lower())
    return result


def player_signature(player: Dict[str, str]) -> Tuple[str, str, str, str]:
    return (player.get("link", ""), player.get("name", ""), player.get("position", ""), player.get("birthyear", ""))


def build_compare_diff_map(teams: List[Dict[str, Any]], current_by_team: Dict[str, List[Dict[str, str]]], previous_by_team: Dict[str, List[Dict[str, str]]]) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    result: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
    team_files = {t["roster_file"] for t in teams}
    for team_file in team_files:
        current_players = current_by_team.get(team_file, [])
        prev_players = previous_by_team.get(team_file, [])
        current_map = {player_signature(p): p for p in current_players}
        prev_map = {player_signature(p): p for p in prev_players}
        added = [current_map[s] for s in current_map.keys() - prev_map.keys()]
        removed = [prev_map[s] for s in prev_map.keys() - current_map.keys()]
        added.sort(key=lambda p: p["name"].lower())
        removed.sort(key=lambda p: p["name"].lower())
        result[team_file] = {"added": added, "removed": removed}
    return result


def build_overview_players(team: Dict[str, Any], diff_map: Dict[str, Dict[str, List[Dict[str, str]]]]) -> List[Dict[str, str]]:
    current_players: List[Dict[str, str]] = []
    diff_entry = diff_map.get(team["roster_file"], {"added": [], "removed": []})
    added_set = {player_signature(p) for p in diff_entry.get("added", [])}
    current_set = {player_signature(p) for p in team["players"]}

    for p in team["players"]:
        row = dict(p)
        row["status"] = "added" if player_signature(p) in added_set else "current"
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
    rows.sort(key=lambda p: (p["status"] == "removed", p["name"].lower()))
    return rows


def build_changed_only_players(team: Dict[str, Any], diff_map: Dict[str, Dict[str, List[Dict[str, str]]]]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    diff_entry = diff_map.get(team["roster_file"], {"added": [], "removed": []})
    for p in diff_entry.get("added", []):
        rows.append(
            {
                "link": p["link"], "name": p["name"], "position": p["position"], "birthyear": p["birthyear"],
                "team": team["team_name"], "serie": team["series_name"], "team_file": team["roster_file"], "status": "added",
            }
        )
    for p in diff_entry.get("removed", []):
        rows.append(
            {
                "link": p["link"], "name": p["name"], "position": p["position"], "birthyear": p["birthyear"],
                "team": team["team_name"], "serie": team["series_name"], "team_file": team["roster_file"], "status": "removed",
            }
        )
    rows.sort(key=lambda p: (p["status"] == "removed", p["name"].lower()))
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


def player_line_status_html(p: Dict[str, str]) -> str:
    cls = "player"
    if p.get("status") == "added":
        cls += " player-added"
    elif p.get("status") == "removed":
        cls += " player-removed"
    return player_line_html(p, compact=True, css_class=cls)


def render_team_players(players: List[Dict[str, str]], status_mode: bool = False) -> List[str]:
    html_parts: List[str] = []
    for cat, label in [("goalies", "Målvakter"), ("defence", "Backar"), ("forwards", "Forwards")]:
        cat_players = [p for p in players if categorize_position(p.get("position", "")) == cat]
        if not cat_players:
            continue
        html_parts.append(f"<h3>{label}</h3>")
        for p in cat_players:
            html_parts.append(player_line_status_html(p) if status_mode else player_line_html(p, compact=True))
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


def build_changes_teams(teams: List[Dict[str, Any]], diff_map: Dict[str, Dict[str, List[Dict[str, str]]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for team in teams:
        diff_entry = diff_map.get(team["roster_file"], {"added": [], "removed": []})
        if diff_entry["added"] or diff_entry["removed"]:
            out.append(team)
    out.sort(key=lambda t: (tab_sort_index(t), t["series_name"].lower(), t["team_name"].lower()))
    return out


def render_compare_block(mode_id: str, label: str, teams: List[Dict[str, Any]], logo_path_html: str, overview_counts: Dict[str, int], diff_map: Dict[str, Dict[str, List[Dict[str, str]]]], current_ts: Optional[str], previous_ts: Optional[str], default_checked: bool) -> str:
    html_parts: List[str] = []
    block_cls = "compare-block active" if default_checked else "compare-block"
    html_parts.append(f"<div id='compare-{mode_id}' class='{block_cls}'>")
    html_parts.append(f"<h1>Spelarförändringar mellan {html_ts(previous_ts)} och {html_ts(current_ts)}</h1>")
    html_parts.append(f"<div class='note'><label><input type='checkbox' class='show-all-toggle' data-mode='{mode_id}'> visa alla spelare</label></div>")
    changes_teams = build_changes_teams(teams, diff_map)
    for team in changes_teams:
        logo_html = f"<img src='{html.escape(logo_path_html + team['logo_file'])}' class='team-logo'>" if team.get("logo_file") else ""
        html_parts.append(f"<details open><summary>{logo_html}{escape_nbsp(team['team_name'])}</summary>")
        html_parts.append(f"<div class='changes-only mode-{mode_id}'>")
        html_parts.extend(render_team_players(build_changed_only_players(team, diff_map), status_mode=True))
        html_parts.append("</div>")
        html_parts.append(f"<div class='changes-all mode-{mode_id}' style='display:none'>")
        html_parts.extend(render_team_players(build_overview_players(team, diff_map), status_mode=True))
        html_parts.append("</div>")
        html_parts.append("</details>")

    html_parts.append(f"<h1>Antal Spelare {html_ts(current_ts)}</h1>")
    html_parts.append("<div class='legend'><span class='added'>Nya spelare</span><span class='removed'>Förlorade spelare</span></div>")
    html_parts.append(f"<div class='note'>Nya spelare och Förlorade spelare jämförs med listning gjord {html_ts(previous_ts)}</div>")
    overview_teams = sorted(teams, key=lambda t: (-(overview_counts.get(t['roster_file'], t['player_count'])), t['team_name'].lower()))
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
        html_parts.extend(render_team_players(build_overview_players(team, diff_map), status_mode=True))
        html_parts.append("</details>")
    html_parts.append("</div>")
    return "\n".join(html_parts)


def generate_html(
    teams: List[Dict[str, Any]],
    all_players: List[Dict[str, str]],
    output_path: Path,
    title: str,
    logo_path_html: str,
    overview_counts: Dict[str, int],
    compare_views: Dict[str, Dict[str, Any]],
    dbg: bool,
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
.note { margin: 0.4em 0 1em 0; font-size: 1.0em; color: #333; }
.compare-block { display:none; }
.compare-block.active { display:block; }
.compare-switch { display:flex; gap:1.2em; flex-wrap:wrap; margin:0.5em 0 1em 0; }
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
function setCompareMode(mode) {
  document.querySelectorAll(".compare-block").forEach(el => el.classList.remove("active"));
  let block = document.getElementById("compare-" + mode);
  if (block) { block.classList.add("active"); }
}
function toggleShowAll(mode, checked) {
  document.querySelectorAll(".changes-only.mode-" + mode).forEach(el => el.style.display = checked ? "none" : "block");
  document.querySelectorAll(".changes-all.mode-" + mode).forEach(el => el.style.display = checked ? "block" : "none");
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
  document.querySelectorAll("input[name='compare-mode']").forEach(r => {
    r.addEventListener("change", e => setCompareMode(e.target.value));
  });
  document.querySelectorAll(".show-all-toggle").forEach(cb => {
    cb.addEventListener("change", e => toggleShowAll(e.target.getAttribute("data-mode"), e.target.checked));
  });
  setCompareMode("day");
  let searchBox = document.getElementById("searchBox");
  if (searchBox) {
    searchBox.addEventListener("input", (e) => renderSearchResults(e.target.value));
  }
});
</script>
""")
    html_parts.append("</head><body>")
    nav_map = {"overview": "Översikt", "SHL": "SHL", "HA": "HA", "HES": "HES", "HEN": "HEN", "H2": "H2", "H3": "H3", "U20": "U20", "U18": "U18", "U16": "U16", "all-players": "Alla Spelare", "search": "Sök Spelare"}
    html_parts.append("<nav>")
    for tab in TAB_ORDER:
        html_parts.append(f"<a href='#{tab}' data-target='{tab}'>{nav_map[tab]}</a>")
    html_parts.append("</nav>")

    html_parts.append("<section id='overview' class='active'>")
    html_parts.append("<div class='note'>Jämför senast sparade spelare och lag med:</div>")
    html_parts.append("<div class='compare-switch'>")
    for mode, label, _days in COMPARE_MODES:
        checked = " checked" if mode == "day" else ""
        html_parts.append(f"<label><input type='radio' name='compare-mode' value='{mode}'{checked}> {html.escape(label)}</label>")
    html_parts.append("</div>")
    for mode, label, _days in COMPARE_MODES:
        view = compare_views[mode]
        html_parts.append(render_compare_block(mode, label, teams, logo_path_html, overview_counts, view["diff_map"], view["current_ts"], view["previous_ts"], mode == "day"))
    html_parts.append("</section>")

    for tab in ["SHL", "HA", "HES", "HEN", "H2", "H3", "U20", "U18", "U16"]:
        html_parts.append(f"<section id='{tab}'>")
        html_parts.append(f"<h1>{html.escape(tab)}</h1>")
        for series_name, series_teams in grouped_tabs[tab]:
            html_parts.append(f"<h2 class='serie-title'>{html.escape(series_name)}</h2>")
            for team in series_teams:
                logo_html = f"<img src='{html.escape(logo_path_html + team['logo_file'])}' class='team-logo'>" if team.get("logo_file") else ""
                html_parts.append(f"<details><summary>{logo_html}{escape_nbsp(team['team_name'])}</summary>")
                html_parts.extend(render_team_players(team["players"], status_mode=False))
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
    debug(f"HTML skriven: {output_path}", dbg)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Series and Teams HTML catalog.")
    parser.add_argument("-o", "--output", required=True, help="Output HTML file")
    parser.add_argument("-tf", "--teamsfile", required=True, help="Teams file with mapping")
    parser.add_argument("-if", "--input-folder", default=DEFAULT_INPUT_FOLDER, help=f"Input folder from getTeamRosters.py output (default: {DEFAULT_INPUT_FOLDER})")
    parser.add_argument("-s", "--season", default=DEFAULT_SEASON, help=f"Season, default {DEFAULT_SEASON}")
    parser.add_argument("-lp", "--logopath", required=True, help="Logo path for HTML references")
    parser.add_argument("-lp_script", "--logopath_script", help="Local path for script to access logo files (defaults to -lp)")
    parser.add_argument("-dbg", "--debug", action="store_true", help="Verbose debug output to stderr")
    args = parser.parse_args()

    dbg = args.debug
    teamsfile = Path(args.teamsfile)
    input_dir = Path(args.input_folder)
    logo_path_html = normalize_html_logo_path(args.logopath)
    logo_path_script = Path(args.logopath_script if args.logopath_script else args.logopath)

    debug(f"teamsfile={teamsfile}", dbg)
    debug(f"input_dir={input_dir}", dbg)
    debug(f"logopath (HTML)={logo_path_html}", dbg)
    debug(f"logopath_script (local)={logo_path_script}", dbg)
    debug(f"season={args.season}", dbg)
    debug(f"output={args.output}", dbg)

    if not teamsfile.exists():
        print(f"ERROR: Teams file saknas: {teamsfile}", file=sys.stderr)
        return 2
    if not input_dir.exists():
        print(f"ERROR: Input folder saknas: {input_dir}", file=sys.stderr)
        return 2
    if not logo_path_script.exists():
        print(f"ERROR: Logo folder saknas: {logo_path_script}", file=sys.stderr)
        return 2

    teams_meta = parse_teams_file(teamsfile, args.season, dbg)
    teams: List[Dict[str, Any]] = []
    all_players: List[Dict[str, str]] = []
    missing_logo_count = 0

    for team_meta in teams_meta:
        roster_path = find_roster_path(team_meta, input_dir)
        debug(f"Roster path för {team_meta['team_name']}: {roster_path} (exists={roster_path.exists()})", dbg)
        team = read_roster_file(roster_path, team_meta, dbg)

        logo_full_path = logo_path_script / team_meta["logo_file"]
        logo_exists = logo_full_path.exists()
        debug(f"Logo för {team_meta['team_name']}: html_src={logo_path_html + team_meta['logo_file']} local_path={logo_full_path} exists={logo_exists}", dbg)
        if team_meta["logo_file"] and not logo_exists:
            print(f"ERROR: Logo saknas för {team_meta['team_name']}: {logo_full_path}", file=sys.stderr)
            missing_logo_count += 1

        teams.append(team)
        all_players.extend(team["players"])

    if missing_logo_count > 0:
        print(f"ERROR: Antal saknade logo-filer: {missing_logo_count}", file=sys.stderr)

    all_players.sort(key=lambda p: p["name"].lower())
    current_by_team = {team["roster_file"]: [
        {"team_file": p["team_file"], "link": p["link"], "name": p["name"], "position": p["position"], "birthyear": p["birthyear"]}
        for p in team["players"]
    ] for team in teams}

    summary_path = input_dir / f"lag_summering_{args.season}.txt"
    current_ts = format_ts_from_path(summary_path)
    overview_counts = parse_lag_summering_file(summary_path, dbg)

    all_history = list_history_files(input_dir, "alla_spelare", args.season, dbg)

    compare_views: Dict[str, Dict[str, Any]] = {}
    for mode, _label, days in COMPARE_MODES:
        previous_snapshot = choose_snapshot(all_history, days)
        previous_ts = format_ts_from_path(previous_snapshot)
        previous_by_team = parse_all_players_snapshot(previous_snapshot, dbg) if previous_snapshot else {}
        diff_map = build_compare_diff_map(teams, current_by_team, previous_by_team)
        compare_views[mode] = {
            "previous_snapshot": previous_snapshot,
            "previous_ts": previous_ts,
            "current_ts": current_ts,
            "diff_map": diff_map,
        }
        debug(f"Jämförelseläge {mode}: snapshot={previous_snapshot} previous_ts={previous_ts}", dbg)

    title = f"Series and Teams Catalog {season_to_title(args.season)}"
    generate_html(teams, all_players, Path(args.output), title, logo_path_html, overview_counts, compare_views, dbg)
    print(f"Wrote HTML catalog to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
