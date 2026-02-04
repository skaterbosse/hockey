#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
runLightSeriesUpdates.py
"""

from datetime import datetime, timedelta
from typing import Optional, List
import csv
import shutil
import time
import os
import subprocess
from typing import Dict


DEFAULT_INACTIVITY_MINUTES = 45
DEFAULT_START_POLLING_MINUTES = 30
DEFAULT_MAX_MATCH_MINUTES = 210   # 3h30m
NEVER_STARTED_GRACE_MINUTES = 60

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

def select_series_to_poll(series_rows, debug=False):
    """
    Returnerar lista av series-id (str) som ska pollas NU.
    Steg 1: endast filtrering på Live=YesLight och DoneToday=No
    """

    selected = []

    for row in series_rows:
        live = row.get("Live", "").strip()
        done = row.get("DoneToday", "").strip()

        if live != "YesLight":
            continue
        if done != "No":
            continue

        link = row.get("SerieLink", "")
        if not link:
            continue

        # seriesId = sista delen av URL
        series_id = link.rstrip("/").split("/")[-1]
        selected.append(series_id)

        if debug:
            print(f"[DBG] Selected series {series_id}")

    return selected

def has_unfinalized_matches_today(
    *,
    date_str: str,
    matches: list,
    last_polled: Optional[datetime],
    now: datetime,
) -> bool:
    """
    Returnerar True om det finns matcher idag som:
      - startat
      - inte är Final Score
      - och serien redan pollats tidigare idag
    """
    if last_polled is None:
        return False

    if last_polled.date() != now.date():
        return False

    for m in matches:
        start_dt = _parse_start_time(date_str, m.get("start_time", ""))
        if not start_dt:
            continue

        if start_dt.date() != now.date():
            continue

        if _has_final_score(m.get("status", "")):
            continue

        if now >= start_dt:
            return True

    return False

def _has_final_score(status: str) -> bool:
    if not status:
        return False
    return "Final Score" in status

def _parse_start_time(date_str: str, time_str: str) -> Optional[datetime]:
    """
    Returnerar datetime för matchstart eller None om starttid är ogiltig.
    """
    if not time_str or time_str == "00:00":
        return None
    try:
        return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except Exception:
        return None

def get_now_ts(now_arg=None):
    import time
    from datetime import datetime

    if now_arg:
        # Förväntat format: YYYY-MM-DD HH:MM
        dt = datetime.strptime(now_arg, "%Y-%m-%d %H:%M")
        return int(dt.timestamp())

    return int(time.time())

def is_match_done(
    *,
    date_str: str,
    match: dict,
    now: datetime,
    inactivity_minutes: int = DEFAULT_INACTIVITY_MINUTES,
) -> bool:
    """
    Returnerar True om matchen ska betraktas som klar för idag.

    REGELVERK (light-mode):
      - Endast matcher med "Final Score" är klara
      - Matcher i framtiden är aldrig klara
      - Inaktivitet räknas INTE som klar
    """

    status = match.get("status", "")
    start_dt = _parse_start_time(date_str, match.get("start_time", ""))

    # 1. Match i framtiden → aldrig klar
    if start_dt and start_dt.date() > now.date():
        return False

    # 2. Endast Final Score betyder klar
    if _has_final_score(status):
        return True

    # 3. Alla andra fall → inte klar
    return False

def is_series_done(
    *,
    date_str: str,
    matches: List[dict],
    now: datetime,
    inactivity_minutes: int = DEFAULT_INACTIVITY_MINUTES,
) -> bool:
    """
    Returnerar True om ALLA matcher i serien är klara för idag.
    """

    for match in matches:
        if not is_match_done(
            date_str=date_str,
            match=match,
            now=now,
            inactivity_minutes=inactivity_minutes,
        ):
            return False

    return True

def collect_matches_for_series(games_rows, series_id: str) -> list:
    matches = []
    for g in games_rows:
        if series_id not in g["link_to_series"]:
            continue
        matches.append({
            "game_id": g.get("result_link", ""),
            "start_time": g.get("time", ""),
            "status": g.get("status", ""),
            "last_hash_ts": None,   # fylls senare
        })
    return matches

def should_poll_match(
    *,
    date_str: str,
    match: dict,
    now: datetime,
    inactivity_minutes: int = DEFAULT_INACTIVITY_MINUTES,
    start_polling_minutes: int = DEFAULT_START_POLLING_MINUTES,
    max_match_minutes: int = DEFAULT_MAX_MATCH_MINUTES,
) -> bool:
    """
    Returnerar True om matchen ska pollas NU enligt A2.
    """

    # 1. Starttid måste vara giltig
    start_dt = _parse_start_time(date_str, match.get("start_time", ""))
    if start_dt is None:
        return False

    # 2. Pollning får starta först vid (starttid - start_polling_minutes)
    if now < (start_dt - timedelta(minutes=start_polling_minutes)):
        return False

    # 3. Final Score → aldrig pollas
    if _has_final_score(match.get("status", "")):
        return False

    # 4. Maxtid EJ nådd?
    if now < (start_dt + timedelta(minutes=max_match_minutes)):
        return True

    # 5. Annars: kräver aktivitet
    last_hash_ts = match.get("last_hash_ts")
    if last_hash_ts is None:
        return False

    last_update = datetime.fromtimestamp(last_hash_ts)
    if now - last_update <= timedelta(minutes=inactivity_minutes):
        return True

    return False

def load_games(path: str) -> list:
    """
    Läser games.csv och returnerar lista av dictar.
    Krävs för wrappern – motsvarar hur updateLightSeriesResults.py läser games.
    """
    games = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            games.append(row)
    return games

def load_series_hash(series_id: str, hash_dir: Optional[str]) -> Optional[str]:
    if not hash_dir:
        return None

    path = os.path.join(hash_dir, f"series_live_{series_id}.hash")
    if not os.path.exists(path):
        return None

    with open(path, encoding="utf-8") as f:
        line = f.readline().strip()
        if not line:
            return None
        parts = line.split(";", 1)
        if len(parts) != 2:
            return None
        return parts[1]

def load_series_live(path: str) -> Dict[str, dict]:
    """
    Läser series_live.csv och returnerar:
      {
        series_id: {
          "series_id": str,
          "last_polled": Optional[datetime],
          "done_for_today": bool,
        }
      }
    """
    series = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            series_id = (row.get("series_id") or "").strip()
            if not series_id:
                continue

            raw_last = (row.get("last_polled") or "").strip()
            last_polled = None
            if raw_last and raw_last not in ("0", "None", "null"):
                try:
                    last_polled = datetime.fromisoformat(raw_last)
                except ValueError:
                    last_polled = None

            done_raw = (row.get("done_for_today") or "No").strip()
            done_for_today = (done_raw == "Yes")

            series[series_id] = {
                "series_id": series_id,
                "last_polled": last_polled,
                "done_for_today": done_for_today,
            }

    return series

def _extract_series_id_from_row(row: dict) -> Optional[str]:
    """
    Försöker plocka ut series_id från en rad i series.csv.

    Stödjer olika format:
      - series_id
      - SerieLink (URL där sista segmentet är id)
      - link_to_series (URL där sista segmentet är id)
    """
    sid = (row.get("series_id") or "").strip()
    if sid:
        return sid

    link = (row.get("SerieLink") or row.get("link_to_series") or "").strip()
    if link:
        parts = link.rstrip("/").split("/")
        if parts:
            sid2 = parts[-1].strip()
            if sid2:
                return sid2

    return None

def load_series_catalog(series_csv_path: str, *, debug: bool = False) -> List[dict]:
    """
    Läser data/series.csv (eller motsvarande) och returnerar rader (dict).

    Viktigt: om filen inte finns returneras [] (bootstrap blir no-op).
    """
    if not os.path.exists(series_csv_path):
        if debug:
            print(f"[DBG] No series catalog found at {series_csv_path} → bootstrap skipped")
        return []

    rows: List[dict] = []
    with open(series_csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row:
                rows.append(row)

    if debug:
        print(f"[DBG] Loaded {len(rows)} series rows from {series_csv_path}")

    return rows

def bootstrap_series_live(
    series_live_path: str,
    *,
    series_csv_path: Optional[str] = None,
    debug: bool = False,
) -> bool:
    """
    Bootstrappar series_live.csv om den:
      - saknas, eller
      - endast innehåller header (0 serier), eller
      - saknar en eller flera serier som borde finnas.

    Källan är series.csv och vi tar ENDAST Live=YesLight.

    Returnerar True om series_live.csv skrevs/ändrades, annars False.

    Viktigt för tester:
      - Om series.csv saknas i testkataloger ska detta vara en NO-OP.
      - Vi skriver deterministiskt med '\n' och sorterad ordning.
    """
    # Bestäm default series.csv om ej angivet
    if series_csv_path is None:
        base_dir = os.path.dirname(series_live_path) or "."
        series_csv_path = os.path.join(base_dir, "series.csv")

    # Om series.csv saknas: gör inget (tester ska inte påverkas)
    catalog = load_series_catalog(series_csv_path, debug=debug)
    if not catalog:
        return False

    # Läs befintlig series_live om den finns
    existing_map: Dict[str, dict] = {}
    if os.path.exists(series_live_path):
        try:
            existing_map = load_series_live(series_live_path)
        except Exception:
            # Om filen är trasig: behandla som tom (vi bygger om)
            existing_map = {}

    # Plocka "YesLight"-serier från catalog
    want_ids: List[str] = []
    for row in catalog:
        live = (row.get("Live") or "").strip()
        if live != "YesLight":
            continue
        sid = _extract_series_id_from_row(row)
        if sid:
            want_ids.append(sid)

    want_ids = sorted(set(want_ids))

    if not want_ids:
        if debug:
            print("[DBG] No YesLight series found in series.csv → bootstrap skipped")
        return False

    # Lägg till saknade serier (utan att röra befintliga timestamps)
    changed = False
    for sid in want_ids:
        if sid not in existing_map:
            existing_map[sid] = {
                "series_id": sid,
                "last_polled": None,
                "done_for_today": False,
            }
            changed = True

    # Om filen saknas eller bara header: changed ska bli True (om vi lade till något)
    # Men om den saknar rader och vi faktiskt har want_ids, då lägger vi till => True.
    if not changed:
        # Ingenting att göra
        return False

    # Skriv deterministiskt (och undvik CRLF/variation)
    # Om du redan har write_series_live_if_changed så kan du använda den.
    try:
        write_series_live_if_changed(series_live_path, existing_map)
    except NameError:
        # Fallback om write_series_live_if_changed inte finns i din version
        import io
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\n")
        w.writerow(["series_id", "last_polled", "done_for_today"])
        for sid in sorted(existing_map.keys()):
            s = existing_map[sid]
            w.writerow([
                s["series_id"],
                s["last_polled"].isoformat() if s.get("last_polled") else "",
                "Yes" if s.get("done_for_today") else "No",
            ])
        with open(series_live_path, "w", encoding="utf-8", newline="") as f:
            f.write(buf.getvalue())

    if debug:
        print(f"[DBG] Bootstrapped series_live.csv with {len(want_ids)} YesLight series (added new ones)")

    return True

def write_series_live_if_changed(path: str, series_map: Dict[str, dict]) -> bool:
    """
    Skriver series_live.csv endast om den nya serialiseringen skiljer sig från filens nuvarande innehåll.
    Viktigt:
      - lineterminator '\n' (inte '\r\n')
      - ingen rewrite om ingen ändring (för att testerna annars diffar pga newline)
    Returnerar True om filen skrevs.
    """
    # Läs originalet exakt som text (för jämförelse)
    with open(path, "r", encoding="utf-8") as f:
        original = f.read()

    # Bygg ny text deterministiskt
    # (sorterad på series_id för stabil ordning)
    import io
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\n")
    writer.writerow(["series_id", "last_polled", "done_for_today"])

    for sid in sorted(series_map.keys()):
        s = series_map[sid]
        writer.writerow([
            s["series_id"],
            s["last_polled"].isoformat() if s["last_polled"] else "",
            "Yes" if s["done_for_today"] else "No",
        ])

    new_text = buf.getvalue()

    if new_text == original:
        return False

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new_text)

    return True

def write_series_live(path: str, series_map: Dict[str, dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["series_id", "last_polled", "done_for_today"])
        for s in series_map.values():
            writer.writerow([
                s["series_id"],
                s["last_polled"].isoformat() if s["last_polled"] else "",
                "Yes" if s["done_for_today"] else "No",
            ])

def run_update_light_series(
    *,
    series_id: str,
    games_file: str,
    html_root: Optional[str],
    hash_dir: Optional[str],
    debug: bool,
):
    """
    Kör updateLightSeriesResults.py för exakt en serie.

    OBS:
      - Wrappern använder INTE hash i sin beslutslogik längre.
      - Men om hash_dir finns så ska vi pass-through:a --hash-file
        eftersom updateLightSeriesResults.py (och testerna) förväntar sig att hash uppdateras.
    """

    cmd = [
        "python3",
        "scripts/updateLightSeriesResults.py",
        "--series-id", series_id,
        "-i", games_file,
    ]

    if html_root:
        if os.path.isdir(html_root):
            html_files = [f for f in os.listdir(html_root) if f.lower().endswith(".html")]
            if not html_files:
                raise RuntimeError(f"No HTML file found in {html_root}")

            # Försök hitta fil som matchar series_id
            preferred = None
            for f in html_files:
                if series_id in f:
                    preferred = f
                    break

            html_file = os.path.join(html_root, preferred if preferred else html_files[0])
        else:
            html_file = html_root

        cmd.extend(["--html-file", html_file])

    # ✅ PASS-THROUGH hash-file (utan att wrappern använder hash)
    if hash_dir:
        hash_file = os.path.join(hash_dir, f"series_live_{series_id}.hash")
        cmd.extend(["--hash-file", hash_file])

    if debug:
        print("[DBG] Running:", " ".join(cmd))

    subprocess.run(cmd, check=False)

def run_light_updates(
    *,
    date_str: str,
    now: datetime,
    games_rows: list,
    games_file: str,
    series_live_path: str,
    inactivity_minutes: int,
    start_polling_minutes: int,
    html_root: Optional[str],
    hash_dir: Optional[str],   # används bara som pass-through till updateLightSeriesResults.py
    dry_run: bool,
    debug: bool,
):
    """
    Regler (som dina tester nu verkar följa):

    - Endast serier i series_live.csv behandlas
    - Skip om done_for_today == Yes
    - Skip om last_polled >= now
    - Pollning sker om minst en match har startat och inte är Final Score
    - Efter pollning:
        - Om "content changed" (dvs update har gjort något) vill du uppdatera last_polled.
          (Du har visat debug som säger: "content changed → last_polled=...").
      OBS: I den här varianten gör vi en enkel policy:
        - Om vi pollar alls => uppdatera last_polled = now
      (Om du vill ha en strikt "bara om content changed" måste vi ha hash-compare i wrappern,
       men du har explicit bett att ta bort hash-logik, så vi gör inte compare här.)
    - series_live.csv skrivs endast om något faktiskt ändrats (write_series_live_if_changed)
    """

    series_map = load_series_live(series_live_path)
    any_series_live_change = False

    dbg(f"Starting light update loop, {len(series_map)} series in series_live.csv")

    for series_id, series in series_map.items():
        t_series = _ts()
        dbg(f"Series {series_id} START")
        if series.get("done_for_today"):
            continue

        last_polled = series.get("last_polled")
        if last_polled is not None and last_polled >= now:
            if debug:
                print(f"[DBG] last_polled>=now → skip series {series_id}")
            continue

        # Hämta matcher för denna serie
        matches = []
        for g in games_rows:
            link = g.get("link_to_series", "")
            sid = link.rstrip("/").split("/")[-1] if link else ""
            if sid == series_id:
                matches.append(g)

        # Finns någon aktiv match? (startat och ej Final Score)
        should_poll = False
        for m in matches:
            start_dt = _parse_start_time(date_str, m.get("time", ""))
            if not start_dt:
                continue

            if now >= start_dt and not _has_final_score(m.get("status", "")):
                should_poll = True
                break

        if not should_poll:
            if debug:
                print(f"[DBG] No active matches → skip series {series_id}")
            continue

        # Kör update
        if not dry_run:
            dbg(f"Series {series_id}: invoking updateLightSeriesResults.py")
            run_update_light_series(
                series_id=series_id,
                games_file=games_file,
                html_root=html_root,
                hash_dir=hash_dir,   # ✅ pass-through så TC3-hash kan uppdateras
                debug=debug,
            )
            dbg(f"Series {series_id}: updateLightSeriesResults.py DONE in {_dt_ms(t_series)} ms")

        # Ladda om games efter update
        games_rows = load_games(games_file)

        # Uppdatera last_polled (detta är vad dina senare körningar tycks vilja göra)
        series["last_polled"] = now
        any_series_live_change = True

        if debug:
            print(f"[DBG] Series {series_id}: polled → last_polled={now.isoformat()}")

        dbg(f"Series {series_id} END total {_dt_ms(t_series)} ms")

    if any_series_live_change:
        write_series_live_if_changed(series_live_path, series_map)

# CLI
def parse_args(argv):
    import argparse
    p = argparse.ArgumentParser(description="Run light series live updates (wrapper around updateLightSeriesResults.py)")

    p.add_argument("--gf", "--games-file", dest="games_file", default="data/games.csv", help="Games file (default: data/games.csv)")
    p.add_argument("--slf", "--series-live-file", dest="series_live_file", default="data/series_live.csv", help="Series live file (default: data/series_live.csv)")
    p.add_argument("--it", "--inactivity-time", dest="inactivity_minutes", type=int, default=45, help="Inactivity time in minutes before a game is considered stale")
    p.add_argument("--spt", "--start-polling-time", dest="start_polling_minutes", type=int, default=30, help="Minutes before game start to begin polling")
    p.add_argument("--now", help="Override current time, format: YYYY-MM-DD HH:MM")
    p.add_argument("--html-root", dest="html_root", help="Root directory for live HTML files (testing only)")
    p.add_argument("--hash-dir", dest="hash_dir", help="Directory for series hash files (testing only)")
    p.add_argument("--dry-run", action="store_true", help="Do not perform any updates, only log decisions")
    p.add_argument("-dbg", "--debug", action="store_true", help="Debug logging")

    return p.parse_args(argv)

def main(argv):
    t_start = _ts()
    args = parse_args(argv)
    debug = bool(args.debug)

    now_ts = get_now_ts(args.now)
    now_dt = datetime.fromtimestamp(now_ts)

    if debug:
        print(f"[DBG] Now timestamp: {now_ts}")

    games_rows = load_games(args.games_file)

    if debug:
        print(f"[DBG] Loaded {len(games_rows)} games from {args.games_file}")

    # ✅ Bootstrap series_live.csv om den är tom/header-only eller saknar YesLight-serier
    bootstrap_series_live(
        args.series_live_file,
        # series_csv_path=None betyder: leta i samma katalog som series_live.csv efter "series.csv"
        series_csv_path=None,
        debug=debug,
    )

    run_light_updates(date_str=now_dt.strftime("%Y-%m-%d"),
                      now=now_dt,
                      games_rows=games_rows,
                      games_file=args.games_file,
                      series_live_path=args.series_live_file,
                      inactivity_minutes=args.inactivity_minutes,
                      start_polling_minutes=args.start_polling_minutes,
                      html_root=args.html_root,
                      hash_dir=args.hash_dir,
                      dry_run=args.dry_run,
                      debug=debug)

    if args.dry_run:
        print("Dry-run mode: no actions performed.")

    dbg(f"TOTAL runtime { _dt_ms(t_start) } ms")
    return 0

if __name__ == "__main__":
    import sys
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
