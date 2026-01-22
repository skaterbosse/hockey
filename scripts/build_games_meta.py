#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

CSV_PATH  = Path("data/games.csv")
OUT_PATH  = Path("data/games.meta.json")

# Kolumner ni sa att hash ska baseras på:
HASH_COLS = [
    "date",
    "time",
    "link_to_series",
    "home_team",
    "away_team",
    "result",
    "result_link",
    "status",
]

def short_hash(s: str, n: int = 8) -> str:
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()
    return h[:n]

def canonical_row(row: dict) -> str:
    # Stabil ordning + separatorer.
    parts = []
    for k in HASH_COLS:
        parts.append((row.get(k) or "").strip())
    return "|".join(parts)

def main():
    if not CSV_PATH.exists():
        raise SystemExit(f"Missing {CSV_PATH}")

    rows = []
    with CSV_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=';')
        for r in reader:
            # Spara bara relevanta fält
            rows.append({k: r.get(k, "") for k in HASH_COLS})

    by_date = {}
    all_lines_for_global = []

    for r in rows:
        d = (r.get("date") or "").strip()
        if not d:
            continue
        line = canonical_row(r)
        all_lines_for_global.append(line)

        by_date.setdefault(d, {"rows": 0, "hash": None, "_lines": []})
        by_date[d]["rows"] += 1
        by_date[d]["_lines"].append(line)

    # Hash per datum
    for d, obj in by_date.items():
        joined = "\n".join(obj["_lines"])
        obj["hash"] = short_hash(joined)
        del obj["_lines"]

    # Global hash (hela datasetet / datumfönstret)
    global_joined = "\n".join(all_lines_for_global)
    global_hash = short_hash(global_joined)

    out = {
        "schema": 2,
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "rows": len(rows),
        "hash": {
            "global": global_hash
        },
        "by_date": by_date
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(by_date)} dates, {len(rows)} rows)")

if __name__ == "__main__":
    main()

