#!/usr/bin/env python3
import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

COMPETITIONS = {
    "PL": {
        "slug": "premier-league",
        "serie": "Premier League",
    },
}

TIMEOUT_SECONDS = 30


def build_refooty_url(source):
    if not source or "match=" not in source:
        return None
    match = source.split("match=", 1)[1]
    return "https://refooty.com/video/" + match.replace("_", "-")


def fetch_json(url):
    request = Request(
        url,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://refooty.com",
            "Referer": "https://refooty.com/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        },
    )

    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset))


def fetch_competition(slug, count):
    page = 1
    rows = []

    while len(rows) < count:
        per_page = min(50, max(1, count - len(rows)))
        url = f"https://a.refooty.com/api/videos/by-competition/{slug}?page={page}&per_page={per_page}"

        try:
            payload = fetch_json(url)
        except HTTPError as exc:
            print(f"Warning: HTTP {exc.code} while fetching {url}", file=sys.stderr)
            break
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"Warning: could not fetch/parse {url}: {exc}", file=sys.stderr)
            break

        items = payload.get("data", []) if isinstance(payload, dict) else []
        if not items:
            break

        rows.extend(items)

        if len(items) < per_page:
            break

        page += 1

    return rows[:count]


def format_duration(seconds):
    if not isinstance(seconds, int):
        return ""
    minutes, secs = divmod(seconds, 60)
    return f"{minutes:02d}:{secs:02d}"


def main():
    parser = argparse.ArgumentParser(description="Fetch football highlights from ReFooty.")
    parser.add_argument("league", choices=COMPETITIONS.keys(), help="League code, for example PL")
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=50,
        help="Max number of highlights to return. Default: 50.",
    )
    args = parser.parse_args()

    if args.count < 1:
        print("count must be at least 1", file=sys.stderr)
        return 2

    cfg = COMPETITIONS[args.league]
    items = fetch_competition(cfg["slug"], args.count)

    highlights = []
    seen = set()

    for item in items:
        source = item.get("source", "")
        if "match=" not in source:
            continue

        matchstart = (item.get("event_at") or "")[:10]
        home_team = item.get("team1") or {}
        away_team = item.get("team2") or {}
        home = (home_team.get("name") or "").strip()
        away = (away_team.get("name") or "").strip()
        video_link = build_refooty_url(source)

        if not matchstart or not home or not away or not video_link:
            continue

        key = (matchstart, home, away, video_link)
        if key in seen:
            continue
        seen.add(key)

        highlights.append(
            {
                "Matchstart": matchstart,
                "Serie": cfg["serie"],
                "Titel": item.get("title") or f"{home} vs {away}",
                "Hemmalag": home,
                "Logo hemmalag": home_team.get("logo_url", ""),
                "Bortalag": away,
                "Logo bortalag": away_team.get("logo_url", ""),
                "Videolänk": video_link,
                "highlightslängd": format_duration(item.get("duration_seconds")),
            }
        )

    highlights.sort(key=lambda row: row["Matchstart"], reverse=True)
    print(json.dumps(highlights, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
