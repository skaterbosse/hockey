#!/usr/bin/env python3
import argparse
import base64
import html
import mimetypes
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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


@dataclass
class Highlight:
    league: str
    date_str: str
    time_str: str
    home_team: str
    away_team: str
    title: str
    url: str


def dbg(enabled: bool, msg: str) -> None:
    if enabled:
        print(f"[DBG] {msg}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate hockey highlights text files and optional HTML.")
    p.add_argument("-l", "--leagues-file", required=True, help="Leagues config file")
    p.add_argument("-od", "--output-directory", required=True, help="Output directory")
    p.add_argument("-oh", "--output-html", default=None, help="Output HTML file")
    p.add_argument("-off", "--offline", action="store_true", help="Use saved highlights text files when generating HTML")
    p.add_argument("-nh", "--no-html", action="store_true", help="Do not generate HTML")
    p.add_argument("-ld", "--logo-directory", required=True, help="Logo directory")
    p.add_argument("-sd", "--script-directory", default=None, help="Script directory")
    p.add_argument("-dbg", "--debug", action="store_true", help="Debug output")
    return p.parse_args()


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


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
            while len(parts) < 8:
                parts.append("")
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
                )
            )
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
        m = re.match(r"^\s*(\d{4}[-/.]\d{2}[-/.]\d{2})\s*-\s*(\d{4}[-/.]\d{2}[-/.]\d{2})\s*$", piece)
        if not m:
            dbg(debug, f"Could not parse active window: {piece}")
            continue
        start = parse_date_flex(m.group(1))
        end = parse_date_flex(m.group(2))
        if start and end and start <= today <= end:
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

            # Kolumn 1 kan innehålla flera alternativa namn separerade med |
            alt_names = [x.strip() for x in alt_names_raw.split("|") if x.strip()]

            for alt_name in alt_names:
                mapping[normalize_team_name(alt_name)] = (full_name, logo_file)

            # Lägg även in kolumn 2 explicit som uppslagsnamn
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


def serialize_highlight(h: Highlight) -> str:
    if h.time_str:
        return f"{h.date_str};{h.time_str};{h.home_team};{h.away_team};{h.title};{h.url}"
    return f"{h.date_str};{h.home_team};{h.away_team};{h.title};{h.url}"


def sort_key(h: Highlight) -> Tuple[str, str, str, str]:
    return (h.date_str, h.time_str or "", h.league, h.title)


def run_script(script_path: Path, debug: bool) -> List[str]:
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")
    cmd = [str(script_path)]
    dbg(debug, f"Running: {shlex.join(cmd)}")
    cp = subprocess.run(cmd, capture_output=True, text=True, check=True)
    if cp.stderr.strip():
        dbg(debug, f"{script_path.name} stderr: {cp.stderr.strip()}")
    return [ln for ln in cp.stdout.splitlines() if ln.strip()]


def read_saved(path: Path) -> List[str]:
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def write_saved(path: Path, items: List[Highlight]) -> None:
    lines = [serialize_highlight(h) for h in sorted(items, key=sort_key, reverse=True)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def dedupe(items: List[Highlight]) -> List[Highlight]:
    seen = set()
    out: List[Highlight] = []
    for h in sorted(items, key=sort_key, reverse=True):
        key = (h.date_str, h.time_str, h.home_team, h.away_team, h.title, h.url, h.league)
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def collect_for_league(league: League, output_dir: Path, today: date, offline: bool, debug: bool) -> List[Highlight]:
    save_path = output_dir / f"{safe_filename(league.name)}_Highlights.txt"
    active_today = is_active_today(league.active_windows_raw, today, debug)
    dbg(debug, f"{league.name}: active_today={active_today}, offline={offline}")

    if offline:
        lines = read_saved(save_path)
    else:
        lines = run_script(league.script_path, debug) if active_today else read_saved(save_path)

    parsed: List[Highlight] = []
    for line in lines:
        h = parse_highlight_line(line)
        if not h:
            dbg(debug, f"{league.name}: could not parse line: {line}")
            continue
        h.league = league.name
        parsed.append(h)

    parsed = dedupe(parsed)
    if not offline:
        write_saved(save_path, parsed)
    return parsed


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
            ".png": "image/png",
            ".gif": "image/gif",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }.get(suffix, "application/octet-stream")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def resolve_team_display_and_logo(
    league_name: str,
    raw_team_name: str,
    team_map: Dict[str, Tuple[str, str]],
    league_logo_name: str,
    logo_dir: Path,
    debug: bool,
) -> Tuple[str, Optional[Path]]:
    normalized = normalize_team_name(raw_team_name)
    entry = team_map.get(normalized)

    if entry:
        display_name, logo_file = entry
        logo_path = logo_dir / logo_file
        if logo_path.exists():
            return display_name, logo_path
        if debug:
            print(
                f"[DBG] {league_name}: lag '{raw_team_name}' matchade '{logo_file}' men filen saknas på '{logo_path}'",
                file=sys.stderr,
            )

    fallback = logo_dir / league_logo_name if league_logo_name else None
    if debug:
        print(
            f"[DBG] {league_name}: lag '{raw_team_name}' saknar logga, sökt på '{logo_dir}' med nyckel '{normalized}'. "
            f"Använder ligalogga '{fallback}'",
            file=sys.stderr,
        )
    return raw_team_name, fallback if fallback and fallback.exists() else None


def resolve_league_logo(league: League, logo_dir: Path, debug: bool) -> Optional[Path]:
    if not league.logo_name:
        return None
    p = logo_dir / league.logo_name
    if p.exists():
        return p
    dbg(debug, f"{league.name}: ligalogga saknas på {p}")
    return None


def render_html(leagues: List[League], league_items: Dict[str, List[Highlight]], output_html: Path, logo_dir: Path, debug: bool) -> None:
    league_map = {l.name: l for l in leagues}
    team_maps = {l.name: load_team_assets(l.teams_file, debug) for l in leagues}

    all_items: List[Highlight] = []
    for v in league_items.values():
        all_items.extend(v)
    all_items = sorted(all_items, key=sort_key, reverse=True)

    cutoff = datetime.now() - timedelta(days=5)
    latest = [h for h in all_items if (parse_highlight_datetime(h) and parse_highlight_datetime(h) >= cutoff)]

    tab_names = ["Senaste"] + [l.name for l in leagues]

    def build_row(h: Highlight) -> str:
        league = league_map[h.league]
        team_map = team_maps[h.league]

        league_logo_path = resolve_league_logo(league, logo_dir, debug)
        home_display, home_logo_path = resolve_team_display_and_logo(
            h.league, h.home_team, team_map, league.logo_name, logo_dir, debug
        )
        away_display, away_logo_path = resolve_team_display_and_logo(
            h.league, h.away_team, team_map, league.logo_name, logo_dir, debug
        )

        home_src = inline_image_data(home_logo_path, debug, f"{h.league} home {home_display}")
        away_src = inline_image_data(away_logo_path, debug, f"{h.league} away {away_display}")
        league_bg_src = inline_image_data(league_logo_path, debug, f"{h.league} league logo")

        dt = h.date_str + (f"  {h.time_str}" if h.time_str else "")
        
        if league_bg_src:
            bg_style = f'style="--league-logo:url(\'{league_bg_src}\');"'
        else:
            bg_style = ""
            
        home_img = f'<img class="team-logo" src="{home_src}" alt="{html.escape(home_display)} logo">' if home_src else ''
        away_img = f'<img class="team-logo" src="{away_src}" alt="{html.escape(away_display)} logo">' if away_src else ''

        return f"""
<a class="highlight-link" href="{html.escape(h.url)}" target="_blank" rel="noopener noreferrer">
  <div class="highlight-bg"{bg_style}></div>
  <div class="highlight-grid">
    <div class="hl-date">{html.escape(dt)}</div>
    <div class="hl-desc">{html.escape(h.title)}</div>
    <div class="hl-league">{html.escape(h.league)}</div>

    <div class="hl-home-logo">{home_img}</div>
    <div class="hl-play"><span class="play-circle"><span class="play-triangle"></span></span></div>
    <div class="hl-away-logo">{away_img}</div>

    <div class="hl-home-name">{html.escape(home_display)}</div>
    <div></div>
    <div class="hl-away-name">{html.escape(away_display)}</div>
  </div>
</a>
"""

    nav_html = "\n".join(
        f"<a href='#tab-{html.escape(name)}' data-target='tab-{html.escape(name)}'>{html.escape(name)}</a>"
        for name in tab_names
    )

    sections: List[str] = []
    sections.append(f"<section id='tab-Senaste' class='active'><div class='highlights-list'>{''.join(build_row(h) for h in latest)}</div></section>")
    for lg in leagues:
        sections.append(f"<section id='tab-{html.escape(lg.name)}'><div class='highlights-list'>{''.join(build_row(h) for h in league_items.get(lg.name, []))}</div></section>")

    html_text = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>Hockey Highlights</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body {{ font-family: Arial, sans-serif; margin: 0; padding: 0; background:#f0f0f0; }}
nav {{ position: sticky; top: 0; z-index: 1000; background: #333; color: white; padding: 1em; display: flex; flex-wrap: wrap; font-size: 1.25em; gap: 0.8em; }}
nav a {{ color: white; text-decoration: none; }}
nav a:hover {{ text-decoration: underline; }}
section {{ display: none; padding: 0.75em; }}
section.active {{ display: block; }}

.highlights-list {{ display:flex; flex-direction:column; gap:12px; }}

.highlight-link {{
  position: relative;
  display:block;
  overflow:hidden;
  border: 1px solid #cfcfcf;
  border-radius: 10px;
  text-decoration:none;
  color:#111;
  background:#efefef;
  min-height: 175px;
}}

.highlight-bg {{
  position:absolute;
  inset:0;
  background-image: var(--league-logo), var(--league-logo), var(--league-logo), var(--league-logo), var(--league-logo);
  background-repeat: no-repeat, no-repeat, no-repeat, no-repeat, no-repeat;
  background-size: 150px auto, 150px auto, 150px auto, 150px auto, 150px auto;
  background-position: 1% 50%, 25% 50%, 50% 50%, 75% 50%, 99% 50%;
  opacity: 0.08;
  filter: grayscale(100%);
  pointer-events:none;
}}

.highlight-grid {{
  position:relative;
  z-index:1;
  display:grid;
  grid-template-columns: 1fr 140px 1fr;
  gap: 0.6em 0.8em;
  align-items:center;
  padding: 0.9em 0.9em 1em 0.9em;
}}

.hl-date {{
  grid-column: 1;
  grid-row: 1;
  font-size: clamp(1.0rem, 2.8vw, 1.45rem);
  font-weight: 800;
  text-align:left;
}}

.hl-desc {{
  grid-column: 2;
  grid-row: 1;
  text-align:center;
  font-size: clamp(0.9rem, 2.3vw, 1.1rem);
  font-weight: 700;
  line-height:1.15;
}}

.hl-league {{
  grid-column: 3;
  grid-row: 1;
  text-align:right;
  font-size: clamp(1rem, 2.8vw, 1.35rem);
  font-weight: 800;
}}

.hl-home-logo, .hl-away-logo {{
  display:flex;
  justify-content:center;
  align-items:center;
  min-height: 92px;
}}

.hl-home-logo {{ grid-column: 1; grid-row: 2; }}
.hl-play {{ grid-column: 2; grid-row: 2; display:flex; justify-content:center; align-items:center; }}
.hl-away-logo {{ grid-column: 3; grid-row: 2; }}

.team-logo {{
  max-height: 92px;
  max-width: 92px;
  object-fit: contain;
}}

.play-circle {{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:72px;
  height:72px;
  border-radius:50%;
  background: #c70039;
  box-shadow:0 3px 10px rgba(0,0,0,0.18);
}}

.play-triangle {{
  width: 0;
  height: 0;
  border-top: 18px solid transparent;
  border-bottom: 18px solid transparent;
  border-left: 28px solid white;
  margin-left: 6px;
}}

.hl-home-name, .hl-away-name {{
  font-size: clamp(1.05rem, 3vw, 1.35rem);
  font-weight: 800;
  text-align:center;
  line-height:1.15;
}}

.hl-home-name {{ grid-column: 1; grid-row: 3; }}
.hl-away-name {{ grid-column: 3; grid-row: 3; }}

@media (min-width: 700px) {{
  section {{ max-width: 1200px; margin: 0 auto; }}
  .highlight-bg {{
    background-size: 190px auto, 190px auto, 190px auto, 190px auto, 190px auto;
  }}
  .team-logo {{
    max-height: 110px;
    max-width: 110px;
  }}
}}

@media (max-width: 480px) {{
  .highlight-grid {{
    grid-template-columns: 1fr 100px 1fr;
  }}
  .play-circle {{
    width: 58px;
    height: 58px;
  }}
  .play-triangle {{
    border-top: 14px solid transparent;
    border-bottom: 14px solid transparent;
    border-left: 22px solid white;
    margin-left: 4px;
  }}
  .team-logo {{
    max-height: 74px;
    max-width: 74px;
  }}
}}
</style>
<script>
function showPage(id, updateHash = true) {{
  var secs = document.querySelectorAll("section");
  secs.forEach(s => s.classList.remove("active"));
  var el = document.getElementById(id);
  if (el) {{ el.classList.add("active"); }}
  if (updateHash) {{
    history.replaceState(null, "", "#" + id);
  }}
  window.scrollTo(0, 0);
}}
window.addEventListener("DOMContentLoaded", () => {{
  var h = location.hash.replace('#','');
  if (h && document.getElementById(h)) {{
    showPage(h, false);
  }} else {{
    showPage("tab-Senaste", false);
  }}
  document.querySelectorAll("nav a[data-target]").forEach(a => {{
    a.addEventListener("click", ev => {{ ev.preventDefault(); showPage(a.getAttribute("data-target")); return false; }});
  }});
}});
</script>
</head><body>
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

    today = date.today()
    league_items: Dict[str, List[Highlight]] = {}
    for league in leagues:
        try:
            league_items[league.name] = collect_for_league(league, output_dir, today, args.offline, args.debug)
            dbg(args.debug, f"{league.name}: {len(league_items[league.name])} highlights")
        except subprocess.CalledProcessError as e:
            print(f"Failed running script for {league.name}: {e}", file=sys.stderr)
            if e.stderr:
                print(e.stderr, file=sys.stderr)
            return 2
        except Exception as e:
            print(f"Failed processing league {league.name}: {e}", file=sys.stderr)
            return 3

    if not args.no_html:
        output_html = Path(args.output_html).resolve() if args.output_html else (output_dir / "hockeyHighlights.html")
        render_html(leagues, league_items, output_html, logo_dir, args.debug)
        dbg(args.debug, f"HTML written to {output_html}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
