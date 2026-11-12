#!/usr/bin/env python3
"""Archive NHL 5-minute recap links against existing Games_YYYY-MM-DD.csv.

Run AFTER game CSV updates. Existing recap rows are never removed just because
NHL's 32-card listing rotates. Python 3.9+, requires requests + beautifulsoup4.
"""
import argparse
import csv
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

SOURCE = 'https://www.nhl.com/video/topic/game-recaps/'
FIELDS = ['GameID', 'GameDate', 'AwayCode', 'HomeCode', 'VideoID', 'VideoURL', 'Duration', 'PublishedAt']
VIDEO_RE = re.compile(r'^/video/topic/game-recaps/([a-z]{2,3})-at-([a-z]{2,3})-recap-(\d+)$', re.I)


def load_cards(html):
    soup = BeautifulSoup(html, 'html.parser')
    cards = []
    seen = set()
    for a in soup.select('a[href*="/video/topic/game-recaps/"]'):
        path = urlparse(urljoin(SOURCE, a.get('href', ''))).path.rstrip('/')
        m = VIDEO_RE.fullmatch(path)
        if not m:
            continue
        away, home, video_id = m.groups()
        if video_id in seen:
            continue
        seen.add(video_id)
        time = a.select_one('time[datetime]')
        published = time.get('datetime', '') if time else ''
        duration = a.select_one('.nhl-c-card__duration')
        cards.append({
            'AwayCode': away.upper(), 'HomeCode': home.upper(),
            'VideoID': video_id, 'VideoURL': urljoin(SOURCE, path),
            'Duration': duration.get_text(' ', strip=True) if duration else '',
            'PublishedAt': published,
        })
    return cards


def parse_published(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        # NHL markup currently uses a naive datetime; do not guess its timezone.
        return dt.date()
    except ValueError:
        return None


def load_games(folder):
    by_pair = {}
    count = 0
    for path in sorted(folder.glob('Games_*.csv')):
        with path.open('r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f, delimiter=';'):
                if row.get('League', '').upper() != 'NHL':
                    continue
                game_id = row.get('GameID', '').strip()
                date = row.get('Date', '').strip()
                away = row.get('AwayCode', '').strip().upper()
                home = row.get('HomeCode', '').strip().upper()
                if not (game_id and re.fullmatch(r'\d{10}', game_id) and date and away and home):
                    continue
                try:
                    game_date = datetime.strptime(date, '%Y-%m-%d').date()
                except ValueError:
                    continue
                key = (away, home)
                by_pair.setdefault(key, {})[game_id] = {
                    'GameID': game_id, 'GameDate': date,
                    'AwayCode': away, 'HomeCode': home,
                    '_date': game_date,
                }
                count += 1
    return {key: list(rows.values()) for key, rows in by_pair.items()}, count


def match_card(card, games):
    candidates = games.get((card['AwayCode'], card['HomeCode']), [])
    pub_date = parse_published(card['PublishedAt'])
    if not pub_date:
        return None, 'missing/invalid publication date'
    # Recaps generally publish on the match day or the following calendar day.
    # Allow 2 days to accommodate timezone ambiguity and late publication.
    # A single candidate is required; no guesses on ambiguous matches.
    plausible = [g for g in candidates if timedelta(days=0) <= pub_date - g['_date'] <= timedelta(days=2)]
    if len(plausible) == 1:
        return plausible[0], None
    return None, f'{len(plausible)} candidate games for {card["AwayCode"]}-{card["HomeCode"]} near {pub_date}'


def read_existing(path):
    rows = {}
    if path.exists():
        with path.open('r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f, delimiter=';')
            if not reader.fieldnames or not set(FIELDS).issubset(reader.fieldnames):
                raise ValueError(f'Unexpected recap CSV header in {path}')
            for row in reader:
                if row.get('GameID'):
                    rows[row['GameID']] = {field: row.get(field, '') for field in FIELDS}
    return rows


def save_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.csv.tmp')
    with temp.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, delimiter=';', lineterminator='\n')
        writer.writeheader()
        writer.writerows(sorted(rows.values(), key=lambda r: (r['GameDate'], r['GameID'])))
    temp.replace(path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--games-dir', type=Path, default=Path('statsByDate/data/games'))
    p.add_argument('--output', type=Path, default=Path('statsByDate/data/recaps/NHL_Recaps.csv'))
    p.add_argument('--html-file', type=Path, help='Use a saved NHL HTML page for offline testing')
    p.add_argument('--timeout', type=int, default=25)
    args = p.parse_args()
    if not args.games_dir.is_dir():
        p.error(f'Games directory does not exist: {args.games_dir}')
    if args.html_file:
        html = args.html_file.read_text(encoding='utf-8')
    else:
        try:
            response = requests.get(SOURCE, timeout=args.timeout, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; LocalSportRecapIndexer/1.0)',
                'Accept': 'text/html',
            })
            response.raise_for_status()
            html = response.text
        except requests.RequestException as e:
            print(f'[ERROR] NHL fetch failed: {e}', file=sys.stderr)
            return 1
    cards = load_cards(html)
    print(f'[NHL recaps] Found {len(cards)} recap cards')
    if not cards:
        print('[ERROR] No recap cards found. Existing archive untouched.', file=sys.stderr)
        return 1
    games, count = load_games(args.games_dir)
    print(f'[NHL games] Read {count} NHL game rows')
    existing = read_existing(args.output)
    added = updated = skipped = 0
    for card in cards:
        game, reason = match_card(card, games)
        if not game:
            print(f'[SKIP] {card["AwayCode"]} at {card["HomeCode"]} video={card["VideoID"]}: {reason}')
            skipped += 1
            continue
        game_id = game['GameID']
        row = {key: card[key] if key in card else game[key] for key in FIELDS}
        if game_id not in existing:
            existing[game_id] = row
            added += 1
            print(f'[ADD] {game["GameDate"]} {game["AwayCode"]} at {game["HomeCode"]} GameID={game_id}')
        elif existing[game_id] != row:
            existing[game_id] = row
            updated += 1
            print(f'[UPDATE] GameID={game_id}')
    if added or updated or not args.output.exists():
        save_rows(args.output, existing)
    print(f'[DONE] Added={added}, Updated={updated}, Skipped={skipped}, Archived={len(existing)} -> {args.output}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
