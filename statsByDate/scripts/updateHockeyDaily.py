#!/usr/bin/env python3
"""Fetch StatsByDate data. Regular: yesterday/today; daily: schedules +1..+6.

Legacy single-date calls (-d YYYY-MM-DD) remain supported.
All dates use Europe/Stockholm, independent of runner timezone.
"""
import argparse
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPTS_DIR.parent


def run_step(label, command, dry_run):
    script = SCRIPTS_DIR / command[1]
    if not script.is_file():
        print(f'ERROR: Missing script: {script}', file=sys.stderr)
        return 2
    actual = [command[0], str(script), *command[2:]]
    print(f'\n[{label}]', flush=True)
    print('  ' + ' '.join(map(str, actual)), flush=True)
    if dry_run:
        return 0
    result = subprocess.run(actual, cwd=PROJECT_DIR, check=False)
    if result.returncode:
        print(f'ERROR: {label} failed ({result.returncode}); stopping.', file=sys.stderr)
    return result.returncode


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('regular', 'daily'), default='regular')
    p.add_argument('-d', '--date', help='Manual single date, or reference date with --mode (YYYY-MM-DD)')
    p.add_argument('-l', '--leagues', choices=('NHL', 'AHL', 'NHL,AHL', 'AHL,NHL'), default='NHL,AHL')
    p.add_argument('--ep', action='store_true', help='Also rebuild EP profiles')
    p.add_argument('--ep-only', action='store_true', help='Only rebuild EP profiles')
    p.add_argument('--ep-dir', default=str(PROJECT_DIR / 'data' / 'ep'))
    p.add_argument('--no-refresh', action='store_true', help='Use cached schedules')
    p.add_argument('--refresh-stats', action='store_true', help='Refresh cached raw game statistics')
    p.add_argument('--no-strict', action='store_true', help='Allow individual statistics errors')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    try:
        anchor = date.fromisoformat(args.date) if args.date else datetime.now(ZoneInfo('Europe/Stockholm')).date()
    except ValueError:
        p.error('--date must be YYYY-MM-DD')
    leagues = ','.join(dict.fromkeys(args.leagues.split(',')))
    stats_league = 'ALL' if ',' in leagues else leagues
    # -d without an explicit mode preserves the previous one-day behavior.
    manual = args.date is not None and not any(a == '--mode' or a.startswith('--mode=') for a in sys.argv[1:])
    days = ([anchor] if manual else
            [anchor - timedelta(days=1), anchor] if args.mode == 'regular' else
            [anchor + timedelta(days=i) for i in range(1, 7)])
    print(f'Mode: {"manual" if manual else args.mode}; reference: {anchor}; dates: {days[0]}..{days[-1]}', flush=True)
    started = time.monotonic()
    if not args.ep_only:
        for day in days:
            schedule = [sys.executable, 'getGamesByDate.py', '-d', day.isoformat(), '-l', leagues]
            if not args.no_refresh:
                schedule.append('--refresh')
            rc = run_step(f'Schedule {day}', schedule, args.dry_run)
            if rc:
                return rc
            if args.mode == 'daily' and not manual:
                continue  # Future schedules only; never fetch future player stats.
            stats = [sys.executable, 'getGamePlayerStats.py', '-d', day.isoformat(), '-l', stats_league]
            if not args.no_strict:
                stats.append('--strict')
            if args.refresh_stats:
                stats.append('--refresh')
            rc = run_step(f'Player statistics {day}', stats, args.dry_run)
            if rc:
                return rc
    if args.ep or args.ep_only:
        rc = run_step('EliteProspects profiles',
                      [sys.executable, 'getEliteProspectsPlayers.py', '--dir', args.ep_dir], args.dry_run)
        if rc:
            return rc
    print(f'\nDone in {time.monotonic()-started:.1f}s.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
