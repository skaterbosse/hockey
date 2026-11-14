#!/usr/bin/env python3
"""Stage and optionally commit/push StatsByDate rolling match data.

regular: stage yesterday/today data, no deletions.
daily: stage schedule +1..+6 and remove tracked match data older than 7 days.
Only match-related files are staged. Local files are never deleted.
Run after a successful updateHockeyDaily.py invocation.
"""
import argparse
import csv
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
PROJECT = Path('statsByDate/data')
DATE_FILE = re.compile(r'^(?:Games|PlayerStats|Goals|Shootout)_(\d{4}-\d{2}-\d{2})\.csv$')


def git(root, *args, capture=True):
    p = subprocess.run(['git', *args], cwd=root, text=True, capture_output=capture)
    if p.returncode:
        raise RuntimeError(f'git {" ".join(args)} failed: {p.stderr.strip()}')
    return p.stdout.strip() if capture else ''


def game_ids(path):
    ids = set()
    with path.open(encoding='utf-8-sig', newline='') as fh:
        sample = fh.read(4096)
        fh.seek(0)
        reader = csv.DictReader(fh, delimiter=';' if sample.count(';') > sample.count(',') else ',')
        for row in reader:
            norm = {re.sub(r'[^a-z0-9]', '', k.lower()): v for k, v in row.items() if k}
            gid = next((norm[k] for k in ('gameid', 'gamepk', 'id') if norm.get(k)), '')
            lg = next((norm[k] for k in ('league', 'leaguename') if norm.get(k)), '').upper()
            if gid and lg in ('NHL', 'AHL'):
                ids.add((lg, gid))
    return ids


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('regular', 'daily'), default='regular')
    p.add_argument('--date', help='Reference date YYYY-MM-DD (Swedish local date by default)')
    p.add_argument('--days-back', type=int, default=7)
    p.add_argument('--days-forward', type=int, default=6)
    p.add_argument('--repo-dir', type=Path, default=ROOT)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--commit', action='store_true')
    p.add_argument('--push', action='store_true')
    p.add_argument('--verbose', action='store_true')
    args = p.parse_args()
    if args.push and not args.commit:
        p.error('--push requires --commit')
    if args.days_back < 0 or args.days_forward < 0:
        p.error('day limits must be nonnegative')
    try:
        today = date.fromisoformat(args.date) if args.date else datetime.now(ZoneInfo('Europe/Stockholm')).date()
    except ValueError:
        p.error('--date must be YYYY-MM-DD')
    root = args.repo_dir.resolve()
    try:
        if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
            p.error('--repo-dir must be the Git repository root')
        if git(root, 'diff', '--cached', '--name-only'):
            p.error('Git staging area is not empty. Commit/unstage other changes before publishing.')
        if args.push and git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD') == '':
            p.error('Cannot push from a detached HEAD')
    except RuntimeError as exc:
        p.error(str(exc))
    data_root = root / PROJECT
    if not data_root.is_dir():
        p.error(f'Missing data directory: {data_root}')
    target_days = ([today - timedelta(days=1), today] if args.mode == 'regular' else
                   [today + timedelta(days=i) for i in range(1, args.days_forward + 1)])
    to_add = set()
    for day in target_days:
        rel = PROJECT / 'games' / f'Games_{day.isoformat()}.csv'
        if not (root / rel).is_file():
            p.error(f'Missing expected schedule (fetch must succeed first): {rel}')
        to_add.add(rel.as_posix())
        if args.mode == 'regular':
            for prefix in ('PlayerStats', 'Goals', 'Shootout'):
                rel = PROJECT / 'playerstats' / f'{prefix}_{day.isoformat()}.csv'
                if (root / rel).is_file():
                    to_add.add(rel.as_posix())
    # Include raw JSON for games referenced by updated schedules, if available.
    for day in target_days:
        schedule = data_root / 'games' / f'Games_{day.isoformat()}.csv'
        for league, gid in game_ids(schedule):
            folder = data_root / 'raw' / 'games' / league / gid
            if folder.is_dir():
                to_add.update(p.relative_to(root).as_posix() for p in folder.glob('*.json') if p.is_file())

    # Keep the cumulative NHL recap archive in every automated publication.
    # This file is intentionally excluded from rolling-data pruning.
    recap = PROJECT / 'recaps' / 'NHL_Recaps.csv'
    if (root / recap).is_file():
        to_add.add(recap.as_posix())

    to_remove = set()
    if args.mode == 'daily':
        cutoff = today - timedelta(days=args.days_back)
        tracked = git(root, 'ls-files', '--', (PROJECT / 'games').as_posix(),
                      (PROJECT / 'playerstats').as_posix(), (PROJECT / 'raw' / 'games').as_posix()).splitlines()
        for name in tracked:
            path = Path(name)
            if path.parent in (PROJECT / 'games', PROJECT / 'playerstats'):
                match = DATE_FILE.fullmatch(path.name)
                if match and date.fromisoformat(match.group(1)) < cutoff:
                    to_remove.add(name)
        # Raw folders have game IDs, not dates. Only prune when all retained
        # schedule files are available, otherwise preserve them conservatively.
        retained = [today + timedelta(days=i) for i in range(-args.days_back, args.days_forward + 1)]
        missing = [d for d in retained if not (data_root / 'games' / f'Games_{d.isoformat()}.csv').is_file()]
        if missing:
            print('WARNING: Missing retained schedule CSVs; skipping raw JSON pruning: '
                  + ', '.join(map(str, missing)), file=sys.stderr)
        else:
            valid = set()
            for d in retained:
                valid.update(game_ids(data_root / 'games' / f'Games_{d.isoformat()}.csv'))
            raw_prefix = (PROJECT / 'raw' / 'games').parts
            for name in tracked:
                parts = Path(name).parts
                if len(parts) >= len(raw_prefix) + 3 and parts[:len(raw_prefix)] == raw_prefix:
                    league, gid = parts[len(raw_prefix):len(raw_prefix)+2]
                    if (league, gid) not in valid:
                        to_remove.add(name)
    to_add.difference_update(to_remove)
    print(f'Mode: {args.mode}; date: {today}; stage {len(to_add)} files; untrack {len(to_remove)} old files')
    if args.verbose or args.dry_run:
        for path in sorted(to_add):
            print('  ADD ', path)
        for path in sorted(to_remove):
            print('  DROP', path)
    if args.dry_run:
        print('Dry run: no Git changes.')
        return 0
    try:
        if to_add:
            git(root, 'add', '--', *sorted(to_add))
        if to_remove:
            # --cached leaves the user's local match history intact.
            git(root, 'rm', '-q', '--cached', '--', *sorted(to_remove))
        staged = git(root, 'diff', '--cached', '--name-only')
        if not staged:
            print('No changes to publish.')
            return 0
        print(f'Staged {len(staged.splitlines())} changed files.')
        if args.commit:
            git(root, 'commit', '-m', f'StatsByDate {args.mode} {today.isoformat()}', capture=False)
            if args.push:
                git(root, 'push', capture=False)
        else:
            print('Review with: git diff --cached --name-status')
    except RuntimeError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
