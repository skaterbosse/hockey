#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    date = None
    debug = False

    i = 0
    while i < len(argv):
        if argv[i] == "--date" and i+1 < len(argv):
            date = argv[i+1]
            i += 2
        elif argv[i] == "-dbg":
            debug = True
            i += 1
        else:
            i += 1

    if not date:
        print("Usage: createGamesFile.py --date YYYY-MM-DD [-dbg]")
        return 1

    print(f"[createGamesFile] Generating games for {date}")

    os.makedirs("data", exist_ok=True)

    tmp_file = "data/games_tmp.csv"
    out_file = "data/games_new.csv"

    # === Steg 1: getGames.py ===
    cmd1 = [
        "python3",
        os.path.join(BASE, "getGames.py"),
        "-sd", date,
        "-ed", date,
        "-ah", "null",
        "-f", tmp_file,
    ]
    if debug:
        cmd1.append("-dbg")

    print("[createGamesFile] Running:", " ".join(cmd1))
    r1 = subprocess.run(cmd1)
    if r1.returncode != 0:
        print("[createGamesFile] ERROR: getGames.py failed")
        return r1.returncode

    # === Steg 2: getClubs.py ===
    cmd2 = [
        "python3",
        os.path.join(BASE, "getClubs.py"),
        "-gf", tmp_file,
        "-cf", os.path.join(BASE, "Clubs.txt"),
        "-af", os.path.join(BASE, "Arenas.csv"),
        "-scf", os.path.join(BASE, "Combined_clubs_teams.txt"),
        "-ogf", out_file,
    ]

    print("[createGamesFile] Running:", " ".join(cmd2))
    r2 = subprocess.run(cmd2)
    if r2.returncode != 0:
        print("[createGamesFile] ERROR: getClubs.py failed")
        return r2.returncode

    # === Steg 3: Städa ===
    if os.path.exists(tmp_file):
        os.remove(tmp_file)

    print(f"[createGamesFile] Done → {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

