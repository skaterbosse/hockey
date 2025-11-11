#!/usr/bin/env python3
import os
from datetime import datetime, timedelta
import subprocess

CACHE_DIR = "cache/deep"
os.makedirs(CACHE_DIR, exist_ok=True)

def run(cmd):
    print("+", cmd)
    subprocess.run(cmd, shell=True, check=True)

today = datetime.now().date()
target_days = [today + timedelta(days=i) for i in range(0, 8)]  # idag + 7 dagar framåt

for date in target_days:
    filename = f"All_games_{date.isoformat()}_deep.txt"
    cache_file = os.path.join(CACHE_DIR, filename)

    if not os.path.exists(cache_file):
        print(f"➡️ Deep fetch: {date}")
        run(
            f"python3 scripts/getGames.py -sd {date} -ed {date} -ah null -f {cache_file}"
        )
    else:
        print(f"✅ Already exists, skipping: {date}")

# bygg games.csv från senaste deep-data
last = os.path.join(CACHE_DIR, f"All_games_{today.isoformat()}_deep.txt")
if os.path.exists(last):
    run(f"cp {last} data/games.csv")
else:
    print("❌ ERROR: today's deep file missing")

print("Done")

