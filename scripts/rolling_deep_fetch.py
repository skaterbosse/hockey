#!/usr/bin/env python3
"""
rolling_deep_fetch.py
- Säkerställer deep-data för 'idag' och saknade dagar fram till +8
- Bygger ett fönster för index.html: [-4 .. +7] dagar runt idag
- Skapar/uppdaterar data/games.csv via getClubs.py
"""

from __future__ import annotations
import subprocess
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import shutil

TZ = ZoneInfo("Europe/Stockholm")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
CACHE_DEEP = REPO_ROOT / "cache" / "deep"
DATA_DIR = REPO_ROOT / "data"

CLUBS = SCRIPTS / "Clubs.txt"
ARENAS = SCRIPTS / "Arenas.csv"
COMBINED = SCRIPTS / "Combined_clubs_teams.txt"

def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)

def ensure_deep_for_day(day: datetime) -> Path:
    """Hämtar deep för ett enskilt datum om saknas. Returnerar filväg."""
    CACHE_DEEP.mkdir(parents=True, exist_ok=True)
    dstr = day.strftime("%Y-%m-%d")
    out = CACHE_DEEP / f"All_games_{dstr}_deep.txt"
    if out.exists():
        print(f"[deep] OK (exists) {out}")
        return out
    # Deep (default) – utan -sh
    cmd = [
        sys.executable, str(SCRIPTS / "getGames.py"),
        "-sd", dstr,
        "-ed", dstr,
        "-ah", "null",
        "-f", str(out)
    ]
    run(cmd)
    return out

def main():
    now_local = datetime.now(TZ)
    today = now_local.date()

    # 1) Säkerställ deep för idag + saknade fram till +8
    for offset in range(0, 9):  # 0..8
        day = datetime.combine(today + timedelta(days=offset), datetime.min.time(), tzinfo=TZ)
        ensure_deep_for_day(day)

    # 2) Bygg 11-dagars fönster [-4 .. +7] till data/games.csv
    #    concatenerar deep-filer och låter sedan getClubs.py skapa ”update”-filen
    window_files = []
    for offset in range(-4, 8):  # -4..+7
        day = datetime.combine(today + timedelta(days=offset), datetime.min.time(), tzinfo=TZ)
        dstr = day.strftime("%Y-%m-%d")
        f = CACHE_DEEP / f"All_games_{dstr}_deep.txt"
        if f.exists():
            window_files.append(f)

    if not window_files:
        print("WARN: Inga deep-filer i fönstret, avbryter utan att skriva om games.csv")
        return

    # Skriv temporär concat-fil
    tmp_concat = REPO_ROOT / "tmp_concat_deep.txt"
    with tmp_concat.open("w", encoding="utf-8") as w:
        for p in window_files:
            with p.open("r", encoding="utf-8") as r:
                w.write(r.read().rstrip("\n") + "\n")

    # Kör getClubs.py för att producera enriched/uppdaterad output
    tmp_update = REPO_ROOT / "tmp_deep_update.txt"
    cmd = [
        sys.executable, str(SCRIPTS / "getClubs.py"),
        "-gf", str(tmp_concat),
        "-cf", str(CLUBS),
        "-af", str(ARENAS),
        "-scf", str(COMBINED),
        "-ogf", str(tmp_update)
    ]
    run(cmd)

    # 3) Kopiera till data/games.csv
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(tmp_update, DATA_DIR / "games.csv")
    print(f"[write] data/games.csv uppdaterad ({DATA_DIR / 'games.csv'})")

    # Cleanup temporära
    try:
        tmp_concat.unlink(missing_ok=True)
        tmp_update.unlink(missing_ok=True)
    except Exception as e:
        print(f"Cleanup warning: {e}")

if __name__ == "__main__":
    main()

