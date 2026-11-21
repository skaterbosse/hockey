#!/usr/bin/env python3
"""Read-only diagnosis of NHL goalie discrepancies using existing local data."""
import argparse
import csv
import json
from pathlib import Path


def diagnose(root, date, game_id):
    root = Path(root)
    raw = root / 'raw' / 'games' / 'NHL' / str(game_id) / 'boxscore.json'
    stats = root / 'playerstats' / f'PlayerStats_{date}.csv'
    if not raw.is_file() or not stats.is_file():
        raise FileNotFoundError(f'Missing input: {raw if not raw.is_file() else stats}')
    box = json.loads(raw.read_text(encoding='utf-8'))
    if str(box.get('id')) != str(game_id):
        raise ValueError('Boxscore game ID does not match requested game')
    with stats.open(encoding='utf-8-sig', newline='') as f:
        rows = [r for r in csv.DictReader(f, delimiter=';') if r['GameID'] == str(game_id) and r['Role'] == 'goalie']
    print(f'NHL {game_id} / {date} — read-only goalie diagnostics')
    issues = 0
    for side in ('awayTeam', 'homeTeam'):
        team = box[side]['abbrev']
        for p in box['playerByGameStats'][side]['goalies']:
            pid = str(p.get('playerId', ''))
            name = p.get('name', {}).get('default', pid)
            match = [r for r in rows if r['TeamCode'] == team and r['PlayerID'] == pid]
            saves, shots, goals = (int(p.get(k) or 0) for k in ('saves', 'shotsAgainst', 'goalsAgainst'))
            active = any(r.get('TimeOnIce') not in ('', '00:00', None) for r in match)
            if not active:
                continue
            consistent = saves + goals == shots
            csv_equal = len(match) == 1 and all(str(match[0][k]) == str(v) for k, v in zip(('Saves','ShotsAgainst','GoalsAgainst'), (saves,shots,goals)))
            print(f'{team} {name}: saves={saves}, shotsAgainst={shots}, goalsAgainst={goals}; source_consistent={consistent}; csv_matches_source={csv_equal}')
            if not consistent or not csv_equal:
                issues += 1
    print(f'Discrepancies: {issues}. No files modified.')
    return issues


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--date', required=True)
    p.add_argument('--game-id', required=True)
    p.add_argument('--data-dir', default=None, help='Default: statsByDate/data_test')
    a = p.parse_args()
    root = Path(a.data_dir) if a.data_dir else Path(__file__).resolve().parent.parent / 'data_test'
    diagnose(root, a.date, a.game_id)

if __name__ == '__main__':
    main()
