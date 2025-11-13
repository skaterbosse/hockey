#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
getGames.py – Hämtar matcher från stats.swehockey.se med förbättrad loggning.
Version: 2025-11-13
"""

import sys
import os
import argparse
import requests
import datetime
import time
import json
from pathlib import Path

# =====================
# Hjälpfunktioner för loggning
# =====================
def log(msg, logfile=None):
    """Skriv logg till både terminal och loggfil."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    if logfile:
        with open(logfile, "a", encoding="utf-8") as f:
            f.write(line + "\n")

def safe_request(url, retries=3, delay=3, logfile=None):
    """HTTP GET med retries och loggning."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            log(f"⚠️ Försök {attempt}/{retries} misslyckades för {url}: {e}", logfile)
            if attempt < retries:
                time.sleep(delay)
    log(f"❌ Permanent fel efter {retries} försök för {url}", logfile)
    return None

# =====================
# Huvudprogram
# =====================
def main():
    parser = argparse.ArgumentParser(description="Fetch games from swehockey API")
    parser.add_argument("-sd", "--startdate", required=True, help="Startdatum YYYY-MM-DD")
    parser.add_argument("-ed", "--enddate", required=True, help="Slutdatum YYYY-MM-DD")
    parser.add_argument("-ah", "--arenahost", default="null", help="Arena eller host filter")
    parser.add_argument("-f", "--file", required=True, help="Utdatafil")
    parser.add_argument("-sh", "--shallow", action="store_true", help="Hämta endast grunddata (shallow mode)")
    args = parser.parse_args()

    # =====================
    # Förbered loggning
    # =====================
    os.makedirs("logs", exist_ok=True)
    logfilename = f"logs/getGames_{args.startdate}_to_{args.enddate}.log"
    log(f"🚀 Startar getGames.py (shallow={args.shallow}) från {args.startdate} till {args.enddate}", logfilename)

    # =====================
    # API URL
    # =====================
    base_url = "https://stats.swehockey.se/api/games"
    params = {
        "startDate": args.startdate,
        "endDate": args.enddate,
        "arenaHost": args.arenahost,
        "shallow": str(args.shallow).lower()
    }

    log(f"📡 Hämtar matcher från {base_url} med parametrar: {params}", logfilename)

    # =====================
    # Hämta data
    # =====================
    response = safe_request(base_url, logfile=logfilename)
    if not response:
        log("❌ Kunde inte hämta data från API:t. Avbryter.", logfilename)
        sys.exit(1)

    try:
        data = response.json()
    except json.JSONDecodeError as e:
        log(f"❌ JSON-fel: {e}", logfilename)
        sys.exit(1)

    if not data:
        log("⚠️ API returnerade tomt resultat.", logfilename)
        sys.exit(0)

    # =====================
    # Skriv resultat
    # =====================
    os.makedirs(os.path.dirname(args.file), exist_ok=True)
    try:
        with open(args.file, "w", encoding="utf-8") as f:
            if isinstance(data, list):
                for match in data:
                    f.write(json.dumps(match, ensure_ascii=False) + "\n")
            else:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        log(f"✅ Skrev {len(data)} matcher till {args.file}", logfilename)
    except Exception as e:
        log(f"❌ Fel vid skrivning till {args.file}: {e}", logfilename)
        sys.exit(1)

    # =====================
    # Avslut
    # =====================
    log("🏁 getGames.py klar.", logfilename)

if __name__ == "__main__":
    main()

