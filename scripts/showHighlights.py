#!/usr/bin/env python3
import argparse
import base64
import html
import json
import mimetypes
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class League:
    name: str
    teams_file: Optional[Path]
    description: str
    manual_web_address: str
    logo_name: str
    script_path: Path
    flashscore_results: str
    active_windows_raw: str
    active_week_windows_raw: str
    script_args_raw: str
    sport: str = "Hockey"


@dataclass
class Highlight:
    league: str
    date_str: str
    time_str: str
    home_team: str
    away_team: str
    title: str
    url: str
    sport: str = "Hockey"
    home_logo_url: str = ""
    away_logo_url: str = ""
    duration: str = ""


def dbg(enabled: bool, msg: str) -> None:
    if enabled:
        print(f"[DBG] {msg}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate hockey/football highlights text files and optional HTML.")
    p.add_argument("-l", "--leagues-file", required=True, help="Leagues config file")
    p.add_argument("-od", "--output-directory", required=True, help="Output directory")
    p.add_argument("-oh", "--output-html", default=None, help="Output HTML file")
    p.add_argument("-off", "--offline", action="store_true", help="Use saved highlights files when generating HTML")
    p.add_argument("-fo", "--force-online", action="store_true", help="Force online update for all leagues, ignoring active date/time windows")
    p.add_argument("-nh", "--no-html", action="store_true", help="Do not generate HTML")
    p.add_argument("-ld", "--logo-directory", required=True, help="Logo directory")
    p.add_argument("-sd", "--script-directory", default=None, help="Script directory")
    p.add_argument("-dbg", "--debug", action="store_true", help="Debug output")
    return p.parse_args()


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def split_multi(value: str) -> List[str]:
    return [p.strip() for p in (value or "").split("|")]


def normalize_team_name(name: str) -> str:
    s = name.strip().lower()
    repl = {
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "å": "a", "ä": "a", "á": "a", "à": "a", "â": "a", "ã": "a",
        "ö": "o", "ø": "o", "ó": "o", "ò": "o", "ô": "o",
        "ü": "u", "ú": "u", "ù": "u",
        "ï": "i", "í": "i", "ì": "i",
        "ç": "c", "æ": "ae", "ß": "ss",
    }
    for k, v in repl.items():
        s = s.replace(k, v)
    s = s.replace("&", " and ")
    s = s.replace("/", " ").replace("-", " ").replace(".", " ").replace("'", "")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def normalize_football_league_name(name: str) -> str:
    value = (name or "").strip()
    low = value.lower()
    if low == "allsvenskan, herrar":
        return "Allsvenskan"
    if low == "superettan":
        return "SuperEttan"
    return value


def parse_leagues_file(path: Path, script_dir: Optional[Path], debug: bool) -> List[League]:
    out: List[League] = []
    base = path.parent.resolve()
    script_base = script_dir.resolve() if script_dir else base
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(";")]
            # 10 kolumner = historiskt format. 11 kolumner = +Sport.
            # En avslutande extra semikolon accepteras och ignoreras.
            while len(parts) > 10 and parts[-1] == "":
                parts.pop()
            if len(parts) not in (10, 11):
                dbg(debug, f"Skipping malformed league row, expected 10 or 11 columns got {len(parts)}: {line}")
                continue
            if not parts[0] or not parts[5]:
                dbg(debug, f"Skipping malformed league row: {line}")
                continue
            out.append(
                League(
                    name=parts[0],
                    teams_file=(base / parts[1]).resolve() if parts[1] else None,
                    description=parts[2],
                    manual_web_address=parts[3],
                    logo_name=parts[4],
                    script_path=(script_base / parts[5]).resolve(),
                    flashscore_results=parts[6],
                    active_windows_raw=parts[7],
                    active_week_windows_raw=parts[8],
                    script_args_raw=parts[9],
                    sport=parts[10] if len(parts) == 11 and parts[10] else "Hockey",
                )
            )
    return out


def display_league_names(league: League) -> List[str]:
    names = split_multi(league.name)
    if league.sport.lower() == "fotboll":
        names = [normalize_football_league_name(n) for n in names]
    return [n for n in names if n]


def display_logo_for_league(league: League, display_name: str) -> str:
    names = display_league_names(league)
    logos = split_multi(league.logo_name)
    if display_name in names:
        idx = names.index(display_name)
        if idx < len(logos):
            return logos[idx]
    return logos[0] if logos else ""


def build_display_league_map(leagues: List[League]) -> Dict[str, League]:
    out: Dict[str, League] = {}
    for lg in leagues:
        for name in display_league_names(lg):
            out[name] = lg
        out[lg.name] = lg
    return out


def parse_date_flex(s: str) -> Optional[date]:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def is_active_today(active_windows_raw: str, today: date, debug: bool) -> bool:
    raw = (active_windows_raw or "").strip()
    if not raw:
        return True
    for block in raw.split("|"):
        piece = block.strip()
        if not piece:
            continue
        m = re.match(r"^\s*(\d{4}[-/.]\d{2}[-/.]\d{2})\s*,\s*(\d{4}[-/.]\d{2}[-/.]\d{2})\s*$", piece)
        if not m:
            m = re.match(r"^\s*(\d{4}[-/.]\d{2}[-/.]\d{2})\s*-\s*(\d{4}[-/.]\d{2}[-/.]\d{2})\s*$", piece)
        if not m:
            dbg(debug, f"Could not parse active date window: {piece}")
            continue
        start = parse_date_flex(m.group(1))
        end = parse_date_flex(m.group(2))
        if start and end and start <= today <= end:
            return True
    return False


def parse_week_time_to_minutes(value: str) -> Optional[int]:
    value = value.strip()
    m = re.match(r"^(\d{2}):(\d{2})$", value)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    if hh == 24 and mm == 0:
        return 1440
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return hh * 60 + mm
    return None


def is_active_now_in_week(active_week_windows_raw: str, now_dt: datetime, debug: bool) -> bool:
    raw = (active_week_windows_raw or "").strip()
    if not raw:
        return True

    current_day = now_dt.isoweekday()
    previous_day = 7 if current_day == 1 else current_day - 1
    current_minutes = now_dt.hour * 60 + now_dt.minute

    for block in raw.split("|"):
        piece = block.strip()
        if not piece:
            continue
        m = re.match(r"^\s*\{([0-9, ]+)\}\s*,\s*\{(\d{2}:\d{2})\s*,\s*(\d{2}:\d{2})\}\s*$", piece)
        if not m:
            dbg(debug, f"Could not parse active week time window: {piece}")
            continue
        days = {int(x.strip()) for x in m.group(1).split(",") if x.strip()}
        start_minutes = parse_week_time_to_minutes(m.group(2))
        end_minutes = parse_week_time_to_minutes(m.group(3))
        if start_minutes is None or end_minutes is None:
            dbg(debug, f"Could not parse times in active week time window: {piece}")
            continue
        if start_minutes <= end_minutes:
            if current_day in days and start_minutes <= current_minutes < end_minutes:
                return True
        else:
            if (current_day in days and current_minutes >= start_minutes) or (previous_day in days and current_minutes < end_minutes):
                return True
    return False


def load_team_assets(team_file: Optional[Path], debug: bool) -> Dict[str, Tuple[str, str]]:
    mapping: Dict[str, Tuple[str, str]] = {}
    if not team_file:
        return mapping
    if not team_file.exists():
        dbg(debug, f"Team file does not exist: {team_file}")
        return mapping
    with team_file.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(";")]
            if len(parts) < 3:
                continue
            alt_names_raw, full_name, logo_file = parts[0], parts[1], parts[2]
            alt_names = [x.strip() for x in alt_names_raw.split("|") if x.strip()]
            for alt_name in alt_names:
                mapping[normalize_team_name(alt_name)] = (full_name, logo_file)
            if full_name:
                mapping[normalize_team_name(full_name)] = (full_name, logo_file)
    return mapping


def parse_highlight_line(line: str) -> Optional[Highlight]:
    parts = [p.strip() for p in line.strip().split(";")]
    if len(parts) == 6:
        date_str, time_str, home_team, away_team, title, url = parts
    elif len(parts) == 5:
        date_str, home_team, away_team, title, url = parts
        time_str = ""
    elif len(parts) == 4:
        date_str, home_team, away_team, url = parts
        time_str = ""
        title = f"{home_team} vs {away_team}"
    else:
        return None
    return Highlight("", date_str, time_str, home_team, away_team, title, url)


def parse_matchstart(value: str) -> Tuple[str, str]:
    value = (value or "").strip()
    if not value:
        return "", ""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        candidate = value[:16] if fmt == "%Y-%m-%d %H:%M" else value[:19] if fmt == "%Y-%m-%dT%H:%M:%S" else value[:10]
        try:
            dt = datetime.strptime(candidate, fmt)
            return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M") if fmt != "%Y-%m-%d" else ""
        except ValueError:
            pass
    if " " in value:
        d, t = value.split(" ", 1)
        return d, t[:5]
    return value[:10], ""


def parse_football_json(text: str, debug: bool) -> List[Highlight]:
    if not text.strip():
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        dbg(debug, f"Could not parse football JSON: {exc}")
        return []
    if isinstance(payload, dict):
        for key in ("items", "results", "data", "highlights"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        dbg(debug, "Football JSON did not contain a list")
        return []

    out: List[Highlight] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        date_str, time_str = parse_matchstart(str(item.get("Matchstart", "")))
        league = normalize_football_league_name(str(item.get("Serie", "")))
        h = Highlight(
            league=league,
            date_str=date_str,
            time_str=time_str,
            home_team=str(item.get("Hemmalag", "") or ""),
            away_team=str(item.get("Bortalag", "") or ""),
            title=str(item.get("Titel", "") or ""),
            url=str(item.get("Videolänk", "") or ""),
            sport="Fotboll",
            home_logo_url=str(item.get("Logo hemmalag", "") or ""),
            away_logo_url=str(item.get("Logo bortalag", "") or ""),
            duration=str(item.get("highlightslängd", "") or ""),
        )
        if h.date_str and h.home_team and h.away_team and h.url:
            out.append(h)
    return out


def serialize_highlight(h: Highlight) -> str:
    if h.time_str:
        return f"{h.date_str};{h.time_str};{h.home_team};{h.away_team};{h.title};{h.url}"
    return f"{h.date_str};{h.home_team};{h.away_team};{h.title};{h.url}"


def serialize_football_json(items: List[Highlight]) -> str:
    payload = []
    for h in sorted(items, key=sort_key, reverse=True):
        payload.append({
            "Matchstart": (h.date_str + (f" {h.time_str}" if h.time_str else "")),
            "Serie": h.league,
            "Titel": h.title,
            "Hemmalag": h.home_team,
            "Logo hemmalag": h.home_logo_url,
            "Bortalag": h.away_team,
            "Logo bortalag": h.away_logo_url,
            "Videolänk": h.url,
            "highlightslängd": h.duration,
        })
    return json.dumps(payload, ensure_ascii=False, indent=2)


def sort_key(h: Highlight) -> Tuple[str, str, str, str]:
    return (h.date_str, h.time_str or "", h.league, h.title)


def run_script(script_path: Path, script_args_raw: str, debug: bool) -> List[str]:
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")
    if script_path.suffix == ".py":
        cmd = [sys.executable, str(script_path)]
    else:
        cmd = [str(script_path)]
    cmd += shlex.split(script_args_raw) if script_args_raw else []
    dbg(debug, f"Running: {shlex.join(cmd)}")
    cp = subprocess.run(cmd, capture_output=True, text=True, check=True)
    if cp.stderr.strip():
        dbg(debug, f"{script_path.name} stderr: {cp.stderr.strip()}")
    return [ln for ln in cp.stdout.splitlines() if ln.strip()]


def read_saved(path: Path) -> List[str]:
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def read_saved_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_saved(path: Path, items: List[Highlight]) -> None:
    lines = [serialize_highlight(h) for h in sorted(items, key=sort_key, reverse=True)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_saved_football(path: Path, items: List[Highlight]) -> None:
    path.write_text(serialize_football_json(items) + "\n", encoding="utf-8")


def dedupe(items: List[Highlight]) -> List[Highlight]:
    seen = set()
    out: List[Highlight] = []
    for h in sorted(items, key=sort_key, reverse=True):
        key = (h.date_str, h.time_str, h.home_team, h.away_team, h.title, h.url, h.league, h.sport)
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def collect_for_league(league: League, output_dir: Path, now_dt: datetime, offline: bool, force_online: bool, debug: bool) -> Tuple[List[Highlight], bool]:
    is_football = league.sport.lower() == "fotboll"
    save_path = output_dir / f"{safe_filename(league.name)}_Highlights.{'json' if is_football else 'txt'}"
    active_today = is_active_today(league.active_windows_raw, now_dt.date(), debug)
    active_now = force_online or (active_today and is_active_now_in_week(league.active_week_windows_raw, now_dt, debug))
    dbg(debug, f"{league.name}: sport={league.sport}, active_today={active_today}, active_now={active_now}, offline={offline}, force_online={force_online}")

    updated = False
    if is_football:
        if offline:
            text = read_saved_text(save_path)
            if not text:
                # Praktisk fallback om filen redan finns från separat fotbollsspår.
                text = read_saved_text(output_dir / "fotboll_highlights.json")
        elif active_now:
            text = "\n".join(run_script(league.script_path, league.script_args_raw, debug))
            updated = True
        else:
            text = read_saved_text(save_path)
            if not text:
                text = read_saved_text(output_dir / "fotboll_highlights.json")

        parsed = dedupe(parse_football_json(text, debug))
        if not offline and updated:
            write_saved_football(save_path, parsed)
        return parsed, updated

    if offline:
        lines = read_saved(save_path)
    else:
        if active_now:
            lines = run_script(league.script_path, league.script_args_raw, debug)
            updated = True
        else:
            lines = read_saved(save_path)

    parsed: List[Highlight] = []
    for line in lines:
        h = parse_highlight_line(line)
        if not h:
            dbg(debug, f"{league.name}: could not parse line: {line}")
            continue
        h.league = league.name
        h.sport = league.sport
        parsed.append(h)

    parsed = dedupe(parsed)
    if not offline and updated:
        write_saved(save_path, parsed)
    return parsed, updated


def parse_highlight_datetime(h: Highlight) -> Optional[datetime]:
    try:
        if h.time_str:
            return datetime.strptime(f"{h.date_str} {h.time_str}", "%Y-%m-%d %H:%M")
        return datetime.strptime(h.date_str, "%Y-%m-%d")
    except ValueError:
        return None


def inline_image_data(path: Optional[Path], debug: bool, context: str) -> str:
    if not path or not path.exists():
        if debug:
            print(f"[DBG] Missing image for {context}: {path}", file=sys.stderr)
        return ""
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        suffix = path.suffix.lower()
        mime = {
            ".png": "image/png", ".gif": "image/gif", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml",
        }.get(suffix, "application/octet-stream")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def resolve_static_asset(*relative_parts: str) -> Optional[Path]:
    candidates = [Path.cwd(), Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent]
    for base in candidates:
        candidate = base.joinpath(*relative_parts)
        if candidate.exists():
            return candidate
    return None


def resolve_team_display_and_logo(league_name: str, raw_team_name: str, team_map: Dict[str, Tuple[str, str]], league_logo_name: str, logo_dir: Path, debug: bool) -> Tuple[str, Optional[Path]]:
    normalized = normalize_team_name(raw_team_name)
    entry = team_map.get(normalized)
    if entry:
        display_name, logo_file = entry
        logo_path = logo_dir / logo_file
        if logo_path.exists():
            return display_name, logo_path
        if debug:
            print(f"[DBG] {league_name}: lag '{raw_team_name}' matchade '{logo_file}' men filen saknas på '{logo_path}'", file=sys.stderr)
    fallback = logo_dir / league_logo_name if league_logo_name else None
    if debug:
        print(f"[DBG] {league_name}: lag '{raw_team_name}' saknar logga, sökt på '{logo_dir}' med nyckel '{normalized}'. Använder ligalogga '{fallback}'", file=sys.stderr)
    return raw_team_name, fallback if fallback and fallback.exists() else None


def resolve_league_logo(league: League, logo_dir: Path, debug: bool, display_name: Optional[str] = None) -> Optional[Path]:
    logo_name = display_logo_for_league(league, display_name) if display_name else split_multi(league.logo_name)[0] if league.logo_name else ""
    if not logo_name:
        return None
    p = logo_dir / logo_name
    if p.exists():
        return p
    dbg(debug, f"{league.name}: ligalogga saknas på {p}")
    return None


def format_highlight_title(title: str, max_line: int = 25) -> str:
    title = title.replace("\r", " ").replace("\n", " ")
    title = re.sub(r"\s+", " ", title.strip())
    if len(title) <= max_line:
        return html.escape(title)
    split_idx = -1
    for i in range(min(len(title), max_line), 0, -1):
        if title[i - 1] in [" ", "-"]:
            split_idx = i
            break
    if split_idx == -1:
        first = title[:max_line]
        second = title[max_line:max_line * 2]
        return html.escape(first) + "<br>" + html.escape(second)
    first = title[:split_idx].rstrip(" -")
    second = title[split_idx:].lstrip(" -")[:max_line]
    return html.escape(first) + "<br>" + html.escape(second)


def tab_id(name: str) -> str:
    return "tab-" + safe_filename(name)


def render_html(leagues: List[League], league_items: Dict[str, List[Highlight]], output_html: Path, logo_dir: Path, debug: bool) -> None:
    display_league_map = build_display_league_map(leagues)
    team_maps = {name: load_team_assets(lg.teams_file, debug) for name, lg in display_league_map.items()}

    all_items: List[Highlight] = []
    for v in league_items.values():
        all_items.extend(v)
    all_items = sorted(all_items, key=sort_key, reverse=True)

    cutoff = datetime.now() - timedelta(days=5)
    latest = [h for h in all_items if (parse_highlight_datetime(h) and parse_highlight_datetime(h) >= cutoff)]

    tab_names: List[str] = ["Senaste"]
    for lg in leagues:
        for name in display_league_names(lg):
            if name not in tab_names and any(h.league == name for h in all_items):
                tab_names.append(name)
    for h in all_items:
        if h.league and h.league not in tab_names:
            tab_names.append(h.league)

    play_icon_src = inline_image_data(resolve_static_asset("icons", "localsport_play_symbol.svg"), debug, "localsport play symbol")
    brand_logo_src = inline_image_data(resolve_static_asset("icons", "local_sport_full_logo_night_mode_highlights.svg"), debug, "localsport full logo")

    def sport_for_tab(name: str) -> str:
        source = latest if name == "Senaste" else [x for x in all_items if x.league == name]
        sports = {h.sport for h in source if h.sport}
        if len(sports) == 1:
            return next(iter(sports))
        return "Both"

    def build_row(h: Highlight) -> str:
        league = display_league_map.get(h.league)
        team_map = team_maps.get(h.league, {})
        home_display = h.home_team
        away_display = h.away_team
        home_src = h.home_logo_url
        away_src = h.away_logo_url
        league_bg_src = h.home_logo_url or h.away_logo_url

        if league and h.sport.lower() != "fotboll":
            logo_name = display_logo_for_league(league, h.league)
            league_logo_path = resolve_league_logo(league, logo_dir, debug, h.league)
            home_display, home_logo_path = resolve_team_display_and_logo(h.league, h.home_team, team_map, logo_name, logo_dir, debug)
            away_display, away_logo_path = resolve_team_display_and_logo(h.league, h.away_team, team_map, logo_name, logo_dir, debug)
            home_src = inline_image_data(home_logo_path, debug, f"{h.league} home {home_display}")
            away_src = inline_image_data(away_logo_path, debug, f"{h.league} away {away_display}")
            league_bg_src = inline_image_data(league_logo_path, debug, f"{h.league} league logo")
        elif league and h.sport.lower() == "fotboll":
            league_logo_path = resolve_league_logo(league, logo_dir, debug, h.league)
            league_bg_src = inline_image_data(league_logo_path, debug, f"{h.league} league logo") or league_bg_src

        dt = h.date_str + (f"  {h.time_str}" if h.time_str else "")
        bg_style = f'style="--league-logo:url(\'{html.escape(league_bg_src)}\');"' if league_bg_src else ""
        home_img = f'<img class="team-logo" src="{html.escape(home_src)}" alt="{html.escape(home_display)} logo">' if home_src else ""
        away_img = f'<img class="team-logo" src="{html.escape(away_src)}" alt="{html.escape(away_display)} logo">' if away_src else ""
        play_img = f'<img class="play-icon" src="{play_icon_src}" alt="Play">' if play_icon_src else '<span class="play-fallback">▶</span>'
        duration_html = f'<span class="hl-duration">{html.escape(h.duration)}</span>' if h.duration else ""

        return f"""
<a class="highlight-link" data-sport="{html.escape(h.sport)}" href="{html.escape(h.url)}" target="_blank" rel="noopener noreferrer">
  <div class="highlight-bg"{bg_style}></div>
  <div class="highlight-grid">
    <div class="hl-date">{html.escape(dt)}</div>
    <div class="hl-desc">{format_highlight_title(h.title)}{duration_html}</div>
    <div class="hl-league">{html.escape(h.league)}</div>

    <div class="hl-home-logo">{home_img}</div>
    <div class="hl-play">{play_img}</div>
    <div class="hl-away-logo">{away_img}</div>

    <div class="hl-home-name">{html.escape(home_display)}</div>
    <div></div>
    <div class="hl-away-name">{html.escape(away_display)}</div>
  </div>
</a>
"""

    nav_html = "\n".join(
        f'<a href="#{tab_id(name)}" data-target="{tab_id(name)}" data-sport="{html.escape(sport_for_tab(name))}">{html.escape(name)}</a>'
        for name in tab_names
    )
    nav_html += '\n<a class="settings-link" href="#tab-Settings" data-target="tab-Settings" data-sport="Both" title="Inställningar">⚙</a>'

    sections: List[str] = []
    sections.append(f"<section id='{tab_id('Senaste')}' class='active' data-sport='Both'><div class='highlights-list'>{''.join(build_row(h) for h in latest)}</div></section>")
    for name in tab_names[1:]:
        items = [h for h in all_items if h.league == name]
        sections.append(f"<section id='{tab_id(name)}' data-sport='{html.escape(sport_for_tab(name))}'><div class='highlights-list'>{''.join(build_row(h) for h in items)}</div></section>")

    settings_section = """
<section id='tab-Settings' data-sport='Both'>
  <div class='settings-panel'>
    <label class='settings-box'><input type='checkbox' name='sportFilter' value='Both' checked> Fotboll och Hockey</label>
    <label class='settings-box'><input type='checkbox' name='sportFilter' value='Hockey'> Hockey</label>
    <label class='settings-box'><input type='checkbox' name='sportFilter' value='Fotboll'> Fotboll</label>
  </div>
</section>
"""
    sections.append(settings_section)

    brand_header = f'<header class="site-brand"><a href="index.html"><img class="site-brand-logo" src="{brand_logo_src}" alt="LocalSport Highlights"></a></header>' if brand_logo_src else ""

    html_text = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>Local Sports: Highlights</title>
<meta property="og:title" content="Local Sports: Highlights">
<meta property="og:type" content="website">
<meta property="og:url" content="https://localsport.se/highlights.html">
<meta property="og:description" content="Highlights från hockey- och fotbollsligor samlade på ett ställe.">
<meta property="og:site_name" content="Local Sports">
<meta property="og:image" content="https://localsport.se/icons/localsport_1200x630_black.png">
<meta property="og:image:secure_url" content="https://localsport.se/icons/localsport_1200x630_black.png">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<link rel="apple-touch-icon" href="https://localsport.se/icons/localsport_1200x630_black.png">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body {{ font-family: Arial, sans-serif; margin: 0; padding: 0; background:#000000; }}
.site-brand {{ position: sticky; top: 0; z-index: 1100; background: #000000; padding: 0.55em 1em 0.45em 1em; display: flex; justify-content: center; align-items: center; box-shadow: 0 2px 8px rgba(0,0,0,0.14); }}
.site-brand-logo {{ max-width: min(92vw, 420px); width: 100%; height: auto; display: block; }}
nav {{ position: sticky; top: 68px; z-index: 1000; background: #000000; color: white; padding: 1em; display: flex; flex-wrap: wrap; font-size: 1.25em; gap: 0.8em; }}
nav a {{ color: white; text-decoration: none; border-bottom: 5px solid transparent; padding-bottom: 0.18em; font-weight: 700; }}
nav a:hover {{ text-decoration: none; }}
nav a.active {{ border-bottom-color: #d7f378; }}
.settings-link {{ margin-left:auto; }}
section {{ display: none; padding: 0.75em; }}
section.active {{ display: block; }}
.highlights-list {{ display:flex; flex-direction:column; gap:12px; }}
.highlight-link {{ position: relative; display:block; overflow:hidden; border: 1px solid #cfcfcf; border-radius: 10px; text-decoration:none; color:#111; background:#efefef; min-height: 162px; }}
.highlight-bg {{ position:absolute; inset:0; background-image: var(--league-logo), var(--league-logo), var(--league-logo), var(--league-logo), var(--league-logo); background-repeat: no-repeat, no-repeat, no-repeat, no-repeat, no-repeat; background-size: 150px auto, 150px auto, 150px auto, 150px auto, 150px auto; background-position: 1% 50%, 25% 50%, 50% 50%, 75% 50%, 99% 50%; opacity: 0.08; filter: grayscale(100%); pointer-events:none; }}
.highlight-grid {{ position:relative; z-index:1; display:grid; grid-template-columns: minmax(0, 1fr) 92px minmax(0, 1fr); gap: 0.15em 0.45em; align-items:center; padding: 3.15em 0.9em 0.6em 0.9em; }}
.hl-date {{ position: absolute; top: 0.72em; left: 0.9em; width: 25%; font-size: clamp(1.0rem, 2.8vw, 1.45rem); font-weight: 800; text-align:left; line-height: 1.05; }}
.hl-desc {{ position: absolute; top: 0.56em; left: 50%; width: min(69%, calc(100% - (0.9em + 25% + 0.3em) - (0.9em + 3ch + 0.3em))); transform: translateX(-50%); text-align:center; font-size: clamp(0.9rem, 2.3vw, 1.1rem); font-weight: 700; line-height:1.12; max-width: 100%; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; word-break: break-word; }}
.hl-duration {{ display:block; font-size:0.85em; font-weight:700; opacity:0.75; margin-top:0.15em; }}
.hl-league {{ position: absolute; top: 0.72em; right: 0.9em; width: 7ch; text-align:right; font-size: clamp(0.85rem, 2.2vw, 1.05rem); font-weight: 800; }}
.hl-home-logo, .hl-away-logo {{ display:flex; justify-content:center; align-items:center; min-height: 92px; }}
.hl-home-logo {{ grid-column: 1; grid-row: 2; }}
.hl-play {{ grid-column: 2; grid-row: 2; display:flex; justify-content:center; align-items:center; }}
.hl-away-logo {{ grid-column: 3; grid-row: 2; }}
.team-logo {{ max-height: 92px; max-width: 92px; object-fit: contain; }}
.play-icon {{ width: 72px; height: 72px; display: block; }}
.play-fallback {{ font-size: 58px; line-height: 1; }}
.hl-home-name, .hl-away-name {{ font-size: clamp(1.05rem, 3vw, 1.35rem); font-weight: 800; text-align:center; line-height:1.15; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }}
.hl-home-name {{ grid-column: 1; grid-row: 3; }}
.hl-away-name {{ grid-column: 3; grid-row: 3; }}
.settings-panel {{ max-width: 900px; margin: 0 auto; display:flex; flex-direction:column; gap:12px; }}
.settings-box {{ display:flex; align-items:center; gap:0.7em; color:#111; background:#efefef; border:1px solid #cfcfcf; border-radius:10px; padding:1em; font-size:1.2em; font-weight:800; }}
.settings-box input {{ width:1.25em; height:1.25em; }}
@media (min-width: 700px) {{ section {{ max-width: 1200px; margin: 0 auto; }} .highlight-bg {{ background-size: 190px auto, 190px auto, 190px auto, 190px auto, 190px auto; }} .team-logo {{ max-height: 110px; max-width: 110px; }} .play-icon {{ width: 88px; height: 88px; }} }}
@media (max-width: 480px) {{ .site-brand {{ padding-left: 0.75em; padding-right: 0.75em; }} nav {{ top: 60px; }} .highlight-grid {{ grid-template-columns: 1fr 100px 1fr; }} .team-logo {{ max-height: 74px; max-width: 74px; }} .play-icon {{ width: 62px; height: 62px; }} }}
</style>
<script>
var sportFilter = localStorage.getItem("localsportHighlightSport") || "Both";
function sportAllowed(sport) {{ return sportFilter === "Both" || sport === sportFilter || sport === "Both"; }}
function applySportFilter() {{
  document.querySelectorAll("nav a[data-target]").forEach(a => {{
    var sport = a.getAttribute("data-sport") || "Both";
    a.style.display = sportAllowed(sport) ? "" : "none";
  }});
  document.querySelectorAll(".highlight-link").forEach(card => {{
    var sport = card.getAttribute("data-sport") || "Both";
    card.style.display = sportAllowed(sport) ? "" : "none";
  }});
  document.querySelectorAll("input[name='sportFilter']").forEach(cb => {{ cb.checked = cb.value === sportFilter; }});
}}
function firstVisibleTab() {{
  var links = Array.from(document.querySelectorAll("nav a[data-target]")).filter(a => a.style.display !== "none" && a.getAttribute("data-target") !== "tab-Settings");
  return links.length ? links[0].getAttribute("data-target") : "tab-Settings";
}}
function showPage(id, updateHash = true) {{
  applySportFilter();
  var targetLink = document.querySelector('nav a[data-target="' + id + '"]');
  if (id !== "tab-Settings" && targetLink && targetLink.style.display === "none") {{ id = firstVisibleTab(); }}
  var secs = document.querySelectorAll("section");
  secs.forEach(s => s.classList.remove("active"));
  var el = document.getElementById(id);
  if (el) {{ el.classList.add("active"); }}
  var links = document.querySelectorAll("nav a[data-target]");
  links.forEach(a => a.classList.remove("active"));
  var activeLink = document.querySelector('nav a[data-target="' + id + '"]');
  if (activeLink) {{ activeLink.classList.add("active"); }}
  if (updateHash) {{ history.replaceState(null, "", "#" + id); }}
  window.scrollTo(0, 0);
}}
window.addEventListener("DOMContentLoaded", () => {{
  document.querySelectorAll("input[name='sportFilter']").forEach(cb => {{
    cb.addEventListener("change", () => {{
      if (!cb.checked) {{ cb.checked = true; return; }}
      sportFilter = cb.value;
      localStorage.setItem("localsportHighlightSport", sportFilter);
      document.querySelectorAll("input[name='sportFilter']").forEach(other => {{ other.checked = other === cb; }});
      applySportFilter();
      showPage(firstVisibleTab());
    }});
  }});
  var h = location.hash.replace('#','');
  applySportFilter();
  if (h && document.getElementById(h)) {{ showPage(h, false); }} else {{ showPage("tab-Senaste", false); }}
  document.querySelectorAll("nav a[data-target]").forEach(a => {{
    a.addEventListener("click", ev => {{ ev.preventDefault(); showPage(a.getAttribute("data-target")); return false; }});
  }});
}});
</script>
</head><body>
{brand_header}
<nav>
{nav_html}
</nav>
{''.join(sections)}
</body></html>
"""
    output_html.write_text(html_text, encoding="utf-8")


def main() -> int:
    args = parse_args()
    leagues_file = Path(args.leagues_file).resolve()
    output_dir = Path(args.output_directory).resolve()
    logo_dir = Path(args.logo_directory).resolve()
    script_dir = Path(args.script_directory).resolve() if args.script_directory else None
    output_dir.mkdir(parents=True, exist_ok=True)

    leagues = parse_leagues_file(leagues_file, script_dir, args.debug)
    if not leagues:
        print("No leagues found.", file=sys.stderr)
        return 1

    now_dt = datetime.now(ZoneInfo("Europe/Stockholm"))
    league_items: Dict[str, List[Highlight]] = {}
    any_league_updated = False
    for league in leagues:
        try:
            league_items[league.name], league_updated = collect_for_league(league, output_dir, now_dt, args.offline, args.force_online, args.debug)
            any_league_updated = any_league_updated or league_updated
            dbg(args.debug, f"{league.name}: {len(league_items[league.name])} highlights")
        except subprocess.CalledProcessError as e:
            print(f"Failed running script for {league.name}: {e}", file=sys.stderr)
            if e.stderr:
                print(e.stderr, file=sys.stderr)
            return 2
        except Exception as e:
            print(f"Failed processing league {league.name}: {e}", file=sys.stderr)
            return 3

    if not args.offline and not any_league_updated:
        dbg(args.debug, "No leagues updated; skipping HTML generation.")
        return 0

    if not args.no_html:
        output_html = Path(args.output_html).resolve() if args.output_html else (output_dir / "hockeyHighlights.html")
        render_html(leagues, league_items, output_html, logo_dir, args.debug)
        dbg(args.debug, f"HTML written to {output_html}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
