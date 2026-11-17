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

def highlights_complete(row, goals):
    # A final score includes one artificial goal for a shootout winner.
    try:
        expected = int(row['HomeScore']) + int(row['AwayScore'])
        if row.get('Decision') == 'GWS':
            expected -= 1
    except (KeyError, ValueError, TypeError):
        return False
    if goals is None or expected < 0 or len(goals) != expected:
        return False
    return all(str(g.get('VideoURL') or '').strip().startswith(('https://', 'http://')) for g in goals)


def build(rows, previous, now, last_regular, config, goal_rows=None):
    games, windows, active = {}, [], []
    for row in rows:
        key = row['League'] + ':' + row['GameID']
        status = row['Status']
        if status in ('CANCELLED', 'POSTPONED'):
            continue
        start = parse(row['StartUTC'])
        old = previous.get(key, {})
        final = None
        complete = None
        if status == 'FINAL':
            final = old.get('finalObservedUTC') or stamp(now)
            # Only NHL currently has a goal-video provider in getGamePlayerStats.
            if row['League'] == 'NHL':
                complete = highlights_complete(row, (goal_rows or {}).get(key))
        games[key] = dict(startUTC=stamp(start), status=status,
                          finalObservedUTC=final, highlightsComplete=complete)
        if status == 'FINAL':
            if row['League'] != 'NHL' or complete:
                continue
            anchor = parse(final)
            interval = config['highlights_interval_minutes']
            expiry = anchor + timedelta(minutes=config['highlights_window_minutes'])
            due = max(anchor, last_regular) + timedelta(minutes=interval)
            kind = 'highlights'
        else:
            interval = config['live_interval_minutes']
            expiry = start + timedelta(minutes=config['maximum_live_window_minutes'])
            due = start if start > now else max(start, last_regular + timedelta(minutes=interval))
            kind = 'live'
        # The Worker rounds up to a five-minute slot. Never schedule at or after expiry.
        slot = datetime.fromtimestamp((int(due.timestamp()+299)//300)*300, UTC)
        if now >= expiry or slot >= expiry:
            continue
        windows.append(dict(game=key, kind=kind, dueUTC=stamp(due),
                            expiresUTC=stamp(expiry), intervalMinutes=interval))
        if kind == 'live' and start <= now:
            active.append(key)
    intervals = [w['intervalMinutes'] for w in windows if parse(w['dueUTC']) <= now + timedelta(minutes=w['intervalMinutes']) and (w['kind'] != 'live' or w['game'] in active)]
    return dict(schemaVersion=2, generatedUTC=stamp(now), lastRegularUTC=stamp(last_regular),
                nextDueUTC=min((w['dueUTC'] for w in windows), default=None),
                intervalMinutes=min(intervals, default=None), activeGames=active,
                windows=windows, games=games, nightMode=config['night_mode'],
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
    if any(config.get(k) != v for k,v in {'live_interval_minutes':10,'maximum_live_window_minutes':210,'highlights_interval_minutes':30,'highlights_window_minutes':130}.items()):
        raise ValueError('Unexpected v5 policy')
    out=args.data_dir/'updateSchedule.json'
    previous=json.loads(out.read_text()).get('games', {}) if out.exists() else {}
    today=now.astimezone(ZoneInfo('Europe/Stockholm')).date()
    rows=[]
    goal_rows={}
    for offset in range(-1,7):
        day=today+timedelta(days=offset)
        file=args.data_dir/'games'/f'Games_{day}.csv'
        if not file.exists():
            if offset <= 0: raise FileNotFoundError(file)
            continue
        with file.open(encoding='utf-8-sig',newline='') as f:
            daily_rows=list(csv.DictReader(f,delimiter=';'))
            rows.extend(daily_rows)
        goalfile=args.data_dir/'playerstats'/f'Goals_{day}.csv'
        if goalfile.exists():
            with goalfile.open(encoding='utf-8-sig',newline='') as f:
                reader=csv.DictReader(f,delimiter=';')
                if {'League','GameID','VideoURL'}.issubset(reader.fieldnames or []):
                    for r in daily_rows:
                        goal_rows.setdefault(r['League']+':'+r['GameID'], [])
                    for r in reader:
                        goal_rows.setdefault(r['League']+':'+r['GameID'], []).append(r)
    # Deduplicate by league and ID; retain prior observations only for present games.
    rows=list({(r['League'],r['GameID']):r for r in rows}.values())
    result=build(rows,previous,now,last,config,goal_rows)
    tmp=out.with_suffix('.tmp'); tmp.write_text(json.dumps(result,indent=2)+'\n'); tmp.replace(out)
    print('Scheduler:',result['nextDueUTC'], 'interval:',result['intervalMinutes'])
if __name__=='__main__': main()
