#!/usr/bin/env python3
"""Build scheduler state from successful schedule CSVs; all calculations in UTC."""
import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
UTC = timezone.utc

def parse(value):
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    return d.astimezone(UTC)

def stamp(d):
    return d.isoformat(timespec='seconds').replace('+00:00', 'Z')

def build(rows, previous, now, last_regular, config):
    games = {}
    for row in rows:
        key = row['League'] + ':' + row['GameID']
        status = row['Status']
        if status in ('CANCELLED', 'POSTPONED'):
            continue
        start = parse(row['StartUTC'])
        old = previous.get(key, {})
        final = None
        if status == 'FINAL':
            # First observation is conservative, including on initial deployment.
            final = old.get('finalObservedUTC') or stamp(now)
        games[key] = dict(startUTC=stamp(start), status=status, finalObservedUTC=final)
    due = []
    active = []
    for key, game in games.items():
        start = parse(game['startUTC'])
        if game['status'] == 'FINAL':
            continue
        if start > now:
            due.append(start)
        else:
            # Fail open even after 210 minutes for unresolved statuses.
            active.append(key)
    interval = None
    if active:
        interval = config['live_interval_minutes']
    else:
        finals = [parse(g['finalObservedUTC']) for g in games.values() if g['finalObservedUTC']]
        if finals:
            age = (now - max(finals)).total_seconds()/60
            interval = next((i for end,i in config['postgame_phases'] if age < end), None)
    if interval is not None:
        due.append(last_regular + timedelta(minutes=interval))
    return dict(schemaVersion=1, generatedUTC=stamp(now), lastRegularUTC=stamp(last_regular),
                nextDueUTC=stamp(min(due)) if due else None, intervalMinutes=interval,
                activeGames=active, games=games,
                validUntilUTC=stamp(now+timedelta(minutes=config['schedule_max_age_minutes'])))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir', type=Path, default=BASE.parent/'data')
    p.add_argument('--config', type=Path, default=BASE/'scheduler_config.json')
    p.add_argument('--now', help='UTC observation time for testing')
    p.add_argument('--run-start', help='UTC workflow start time')
    args=p.parse_args()
    now=parse(args.now) if args.now else datetime.now(UTC)
    last=parse(args.run_start) if args.run_start else now
    last=datetime.fromtimestamp(int(last.timestamp())//300*300, UTC)
    config=json.loads(args.config.read_text())
    if config['live_interval_minutes'] != 10 or config['minimum_live_window_minutes'] < 210:
        raise ValueError('Safety policy requires 10 min and at least 210 min')
    out=args.data_dir/'updateSchedule.json'
    previous=json.loads(out.read_text()).get('games', {}) if out.exists() else {}
    today=now.astimezone(ZoneInfo('Europe/Stockholm')).date()
    rows=[]
    for offset in range(-1,7):
        day=today+timedelta(days=offset)
        file=args.data_dir/'games'/f'Games_{day}.csv'
        if not file.exists():
            if offset <= 0: raise FileNotFoundError(file)
            continue
        with file.open(encoding='utf-8-sig',newline='') as f:
            rows.extend(csv.DictReader(f,delimiter=';'))
    # Deduplicate by league and ID; retain prior observations only for present games.
    rows=list({(r['League'],r['GameID']):r for r in rows}.values())
    result=build(rows,previous,now,last,config)
    tmp=out.with_suffix('.tmp'); tmp.write_text(json.dumps(result,indent=2)+'\n'); tmp.replace(out)
    print('Scheduler:',result['nextDueUTC'], 'interval:',result['intervalMinutes'])
if __name__=='__main__': main()
