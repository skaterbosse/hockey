#!/usr/bin/env python3
"""
Fetch Swedish football highlight playlists from Fotbollplay and export selected match metadata as JSON.

Examples:
  python3 getSwedishFotballHighlights.py
  python3 getSwedishFotballHighlights.py -sd 2026-01-01 -ed 2026-04-30
  python3 getSwedishFotballHighlights.py -sd 2026-01-01 -ed 2026-04-30 -of highlights.json

If -sd/--startdate and -ed/--enddate are omitted, the script defaults to:
  -sd = today's date minus 14 days
  -ed = today's date
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://api.fotbollplay.se/allsvenskan/playlist"
MAX_COUNT = 50
TIMEOUT_SECONDS = 30


def default_startdate() -> str:
    return (date.today() - timedelta(days=14)).isoformat()


def default_enddate() -> str:
    return date.today().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Swedish football highlights from Fotbollplay."
    )
    parser.add_argument(
        "-sd",
        "--startdate",
        default=default_startdate(),
        help="Start date, for example 2026-01-01. Default: today minus 14 days.",
    )
    parser.add_argument(
        "-ed",
        "--enddate",
        default=default_enddate(),
        help="End date, for example 2026-04-30. Default: today.",
    )
    parser.add_argument(
        "-of",
        "--output-file",
        help="Output JSON file. If omitted, JSON is written to stdout.",
    )
    return parser.parse_args()


def validate_date(value: str, arg_name: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise SystemExit(f"Invalid {arg_name}: {value}. Expected format YYYY-MM-DD.")


def build_url(from_offset: int, count: int, startdate: str, enddate: str) -> str:
    params = {
        "all_leagues": "true",
        "channels": "[]",
        "count": str(count),
        "filters": json.dumps(["official"]),
        "from": str(from_offset),
        "from_date": startdate,
        "holdback": "all",
        "include_channels": "true",
        "tags": json.dumps([{"action": "highlights"}]),
        "to_date": enddate,
    }
    return f"{BASE_URL}?{urlencode(params)}"


def fetch_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "getSwedishFotballHighlights/1.1",
        },
    )

    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
    except HTTPError as exc:
        raise RuntimeError(f"HTTP error {exc.code} while fetching {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error while fetching {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse JSON response from {url}") from exc


def extract_items(payload: Any) -> List[Dict[str, Any]]:
    """
    The API may return either a list directly or a dict containing a list.
    This keeps the script tolerant to small response-shape differences.
    """
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("items", "results", "playlists", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    raise RuntimeError("Unexpected API response shape: could not find a list of playlist items.")


def format_match_start(value: Optional[str]) -> Optional[str]:
    """
    Convert ISO timestamp like 2026-04-25T15:00:03.840000Z to YYYY-MM-DD HH:MM.
    If parsing fails, return the original value.
    """
    if not value:
        return None

    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def duration_ms_to_seconds(duration_ms: Optional[int]) -> Optional[int]:
    if isinstance(duration_ms, int):
        return round(duration_ms / 1000)
    return None


def format_duration_mmss(seconds: Optional[int]) -> Optional[str]:
    """Convert seconds to MM:SS, for example 146 -> 02:26."""
    if seconds is None:
        return None
    minutes, secs = divmod(seconds, 60)
    return f"{minutes:02d}:{secs:02d}"


def get_duration_ms(item: Dict[str, Any]) -> Optional[int]:
    duration_ms = item.get("duration_ms")
    if isinstance(duration_ms, int):
        return duration_ms

    # Fallback: sometimes duration can be inferred from the first event.
    events = item.get("events") or []
    if events and isinstance(events[0], dict):
        from_ts = events[0].get("from_timestamp")
        to_ts = events[0].get("to_timestamp")
        if isinstance(from_ts, int) and isinstance(to_ts, int) and to_ts >= from_ts:
            return to_ts - from_ts

    return None


def map_highlight(item: Dict[str, Any]) -> Dict[str, Any]:
    game = item.get("game") or {}
    home_team = game.get("home_team") or {}
    visiting_team = game.get("visiting_team") or {}

    duration_ms = get_duration_ms(item)
    duration_seconds = duration_ms_to_seconds(duration_ms)

    return {
        "Matchstart": format_match_start(game.get("start_of_1st_half") or game.get("start_time")),
        "Serie": game.get("tournament_name") or (game.get("tournament") or {}).get("league_name"),
        "Titel": item.get("description"),
        "Hemmalag": home_team.get("name"),
        "Logo hemmalag": home_team.get("logo_url"),
        "Bortalag": visiting_team.get("name"),
        "Logo bortalag": visiting_team.get("logo_url"),
        "Videolänk": item.get("minified_frontend_url") or item.get("frontend_url"),
        "highlightslängd": format_duration_mmss(duration_seconds),
    }


def fetch_all_highlights(startdate: str, enddate: str) -> List[Dict[str, Any]]:
    all_items: List[Dict[str, Any]] = []
    from_offset = 0

    while True:
        url = build_url(from_offset, MAX_COUNT, startdate, enddate)
        payload = fetch_json(url)
        items = extract_items(payload)

        if not items:
            break

        all_items.extend(items)

        if len(items) < MAX_COUNT:
            break

        from_offset += MAX_COUNT

    return [map_highlight(item) for item in all_items]


def main() -> int:
    args = parse_args()
    validate_date(args.startdate, "startdate")
    validate_date(args.enddate, "enddate")

    if args.startdate > args.enddate:
        print("startdate must be earlier than or equal to enddate.", file=sys.stderr)
        return 2

    try:
        highlights = fetch_all_highlights(args.startdate, args.enddate)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output = json.dumps(highlights, ensure_ascii=False, indent=2)

    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as file:
            file.write(output)
            file.write("\n")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
