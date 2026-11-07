#!/usr/bin/env python3
"""Download NHL/AHL schedules for one date or inclusive date range.

Uses league-local schedule dates, not Swedish calendar dates. Python 3.10+.
Only schedule data is downloaded; per-game boxscores are a later step.
Version 2: normalized status, AHL scores/team IDs/UTC start, original SourceStatus.
"""
import argparse
import csv
from datetime import date, timedelta, datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

NHL_URL = 'https://api-web.nhle.com/v1/schedule/'
AHL_URL = 'https://lscluster.hockeytech.com/feed/index.php'
AHL_KEY = 'ccb91f29d6744675'  # public, read-only website key
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / 'data'

FIELDS = ['League','Date','GameID','Season','GameType','Status','AwayTeam','AwayCode','AwayTeamID',
          'HomeTeam','HomeCode','HomeTeamID','AwayScore','HomeScore','StartUTC','Source','SourceStatus']


def get_json(url, params=None):
    if params:
        url += ('&' if '?' in url else '?') + urlencode(params)
    last_error = None
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers={'User-Agent':'Mozilla/5.0 (compatible; StatsByDate/1.0)',
                                                'Accept':'application/json, text/javascript, */*'}), timeout=25) as r:
                body = r.read().decode('utf-8-sig').strip()
            if body.startswith('angular.callbacks.'):
                body = body[body.index('(')+1:].rstrip('); \r\n')
            elif not body.startswith(('{','[')) and '(' in body and body.endswith(')'):
                body = body[body.index('(')+1:-1]
            value = json.loads(body)
            if not isinstance(value, (dict,list)):
                raise ValueError('Unexpected API response type')
            return value
        except Exception as e:
            last_error = e
            if attempt < 3:
                time.sleep(1.5*(attempt+1))
    raise RuntimeError(f'API request failed ({url}): {last_error}')


def cache_get(path, url, params=None, refresh=False):
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding='utf-8')), True
    obj = get_json(url, params)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)
    return obj, False


def label(obj):
    if isinstance(obj, dict):
        return str(obj.get('default') or obj.get('en') or next(iter(obj.values()), '') or '')
    return str(obj or '')


def dates_between(start, end):
    d = start
    while d <= end:
        yield d.isoformat()
        d += timedelta(days=1)


def normalized_status(league, raw, game=None):
    """Common status while retaining the league's original status in SourceStatus."""
    val = str(raw or '').strip().upper()
    if league == 'NHL':
        if val in ('OFF', 'FINAL'):
            return 'FINAL'
        if val in ('LIVE', 'CRIT'):
            return 'LIVE'
        if val in ('FUT', 'PRE'):
            return 'SCHEDULED'
        if val in ('POSTPONED', 'PPD'):
            return 'POSTPONED'
        if val in ('CANCELLED', 'CANCELED'):
            return 'CANCELLED'
    else:
        if game and str(game.get('final', '')).strip() == '1':
            return 'FINAL'
        if 'FINAL' in val:
            return 'FINAL'
        if 'POSTPON' in val:
            return 'POSTPONED'
        if 'CANCEL' in val:
            return 'CANCELLED'
        if game and str(game.get('started', '')).strip() == '1':
            return 'LIVE'
        if any(word in val for word in ('LIVE', 'PROGRESS', 'INTERMISSION', 'PERIOD')):
            return 'LIVE'
        if val in ('', 'SCHEDULED', 'PRE-GAME', 'PREGAME', 'NOT STARTED'):
            return 'SCHEDULED'
    return 'UNKNOWN'


def ahl_start_utc(game):
    """HockeyTech supplies an offset-aware GameDateISO8601; convert to UTC."""
    local_iso = str(getv(game, 'GameDateISO8601', 'gameDateISO8601')).strip()
    if local_iso:
        try:
            dt = datetime.fromisoformat(local_iso.replace('Z', '+00:00'))
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        except ValueError:
            pass
    # Do not assume date_time_played is UTC: some HockeyTech fields label local time with Z.
    return ''


def nhl_games(day, cache_dir, refresh):
    path = cache_dir/'NHL'/f'{day}.json'
    payload, cached = cache_get(path, NHL_URL+day, refresh=refresh)
    if not isinstance(payload, dict) or not isinstance(payload.get('gameWeek'), list):
        raise ValueError(f'NHL schedule missing gameWeek: {day}')
    result = []
    for week in payload['gameWeek']:
        if week.get('date') != day:
            continue
        for g in week.get('games', []):
            away, home = g.get('awayTeam') or {}, g.get('homeTeam') or {}
            result.append(dict(League='NHL', Date=day, GameID=g.get('id',''),
                Season=g.get('season',''), GameType=g.get('gameType',''),
                Status=normalized_status('NHL',g.get('gameState','')), SourceStatus=g.get('gameState',''),
                AwayTeam=label(away.get('placeName')) or label(away.get('commonName')),
                AwayCode=away.get('abbrev',''), AwayTeamID=away.get('id',''),
                HomeTeam=label(home.get('placeName')) or label(home.get('commonName')),
                HomeCode=home.get('abbrev',''), HomeTeamID=home.get('id',''),
                AwayScore=away.get('score',''), HomeScore=home.get('score',''),
                StartUTC=g.get('startTimeUTC',''), Source='NHL_API'))
    return result, cached


def nested_schedule(obj):
    """HockeyTech modulekit schedule has used multiple wrappers."""
    if isinstance(obj, dict):
        for key in ('Schedule','schedule','games','Games'):
            val = obj.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                for sub in ('games','Games','schedule'):
                    if isinstance(val.get(sub), list):
                        return val[sub]
        for key in ('SiteKit','ModuleKit','data'):
            if isinstance(obj.get(key), dict):
                found = nested_schedule(obj[key])
                if found is not None:
                    return found
    return None


def getv(g, *keys):
    for k in keys:
        if k in g and g[k] is not None:
            return g[k]
    return ''


def ahl_games(start, end, cache_dir, refresh, key, season_ids):
    rows=[]
    # Fetch entire season schedule once per season. HockeyTech season IDs aren't sequential by year.
    for season_id in season_ids:
        params={'feed':'modulekit','view':'schedule','key':key,'client_code':'ahl',
                'site_id':3,'season_id':season_id,'lang':'en','callback':'angular.callbacks._0'}
        payload, cached = cache_get(cache_dir/'AHL'/f'season_{season_id}.json', AHL_URL, params, refresh)
        games = nested_schedule(payload)
        if games is None:
            raise ValueError(f'AHL season {season_id}: unknown response structure. Raw JSON saved; inspect it.')
        added=0
        for g in games:
            if not isinstance(g,dict):
                continue
            raw_date=str(getv(g,'date_played','game_date','date','scheduled_date','gameDate'))
            day=raw_date[:10]
            if not (start<=day<=end):
                continue
            away=getv(g,'visiting_team','away_team','visitor_team','awayTeam')
            home=getv(g,'home_team','homeTeam')
            if isinstance(away,dict):
                away_name=getv(away,'name','team_name','city'); away_id=getv(away,'id','team_id'); away_code=getv(away,'code','abbreviation')
            else:
                away_name=getv(g,'visiting_team_name','away_team_name','visitor_name') or away
                away_id=getv(g,'visiting_team_id','away_team_id') or away; away_code=getv(g,'visiting_team_code','away_team_code')
            if isinstance(home,dict):
                home_name=getv(home,'name','team_name','city'); home_id=getv(home,'id','team_id'); home_code=getv(home,'code','abbreviation')
            else:
                home_name=getv(g,'home_team_name') or home
                home_id=getv(g,'home_team_id') or home; home_code=getv(g,'home_team_code')
            game_id=getv(g,'game_id','id','gameId')
            if not game_id:
                raise ValueError(f'AHL season {season_id}: game lacks ID: {str(g)[:200]}')
            rows.append(dict(League='AHL',Date=day,GameID=game_id,Season=season_id,
                GameType=getv(g,'game_type','gameType'),
                Status=normalized_status('AHL',getv(g,'game_status','status'),g),
                SourceStatus=getv(g,'game_status','status'),
                AwayTeam=away_name,AwayCode=away_code,AwayTeamID=away_id,
                HomeTeam=home_name,HomeCode=home_code,HomeTeamID=home_id,
                AwayScore=getv(g,'visiting_goal_count','visiting_team_score','away_score','visitor_score'),
                HomeScore=getv(g,'home_goal_count','home_team_score','home_score'),
                StartUTC=ahl_start_utc(g),Source='AHL_HOCKEYTECH'))
            added+=1
        print(f'INFO AHL season {season_id}: {len(games)} schedule rows, {added} in range'+(' (cached)' if cached else ''))
    return rows


def season_ids_for_range(start, end, explicit):
    if explicit:
        return list(dict.fromkeys(explicit))
    # Verified regular season ID for 2026-27 only; no guesswork for other seasons.
    if start >= '2026-09-01' and end <= '2027-06-30':
        return ['94']
    raise ValueError('AHL season ID unknown for this date range; pass --ahl-season-id (repeat for multiple seasons).')


def main():
    p=argparse.ArgumentParser(description='NHL/AHL games by league-local calendar date. Saves CSV and raw API JSON.')
    p.add_argument('-d','--date', nargs='+', required=True, metavar='YYYY-MM-DD',
                   help='One date or inclusive start and end dates')
    p.add_argument('-l','--leagues',default='NHL,AHL',help='NHL,AHL (default), NHL, or AHL')
    p.add_argument('-o','--out',help='CSV output (default data/games/Games_START[_END].csv)')
    p.add_argument('--cache-dir',default=str(DATA_DIR / 'raw' / 'schedules'),help='Raw schedule JSON cache')
    p.add_argument('--refresh',action='store_true',help='Re-download even if JSON is cached')
    p.add_argument('--ahl-season-id',action='append',help='Explicit AHL HockeyTech season ID; repeat as needed')
    p.add_argument('--ahl-key',default=os.environ.get('AHL_API_KEY',AHL_KEY),help='AHL public read-only API key')
    args=p.parse_args()
    if len(args.date) not in (1,2):
        p.error('-d accepts one date or start and end dates')
    try:
        start=date.fromisoformat(args.date[0]); end=date.fromisoformat(args.date[-1])
    except ValueError:
        p.error('Dates must be valid YYYY-MM-DD')
    if start>end:
        p.error('Start date must not be after end date')
    if (end-start).days>366:
        p.error('Maximum date range is 366 days per run')
    leagues={x.strip().upper() for x in args.leagues.split(',')}
    if not leagues or not leagues.issubset({'NHL','AHL'}):
        p.error('Use -l NHL,AHL, NHL, or AHL')
    cache_dir=Path(args.cache_dir)
    rows=[];errors=[]
    if 'NHL' in leagues:
        for day in dates_between(start,end):
            try:
                found,cached=nhl_games(day,cache_dir,args.refresh)
                rows.extend(found)
                print(f'INFO NHL {day}: {len(found)} games'+(' (cached)' if cached else ''))
            except Exception as e:
                errors.append(f'NHL {day}: {e}')
                print(f'ERROR {errors[-1]}',file=sys.stderr)
    if 'AHL' in leagues:
        try:
            seasons=season_ids_for_range(start.isoformat(),end.isoformat(),args.ahl_season_id)
            rows.extend(ahl_games(start.isoformat(),end.isoformat(),cache_dir,args.refresh,args.ahl_key,seasons))
        except Exception as e:
            errors.append(f'AHL: {e}')
            print(f'ERROR {errors[-1]}',file=sys.stderr)
    unique={}
    for row in rows:
        key=(row['League'],str(row['GameID']))
        if key in unique and unique[key]['Date']!=row['Date']:
            errors.append(f'Conflicting dates for {key}')
        unique[key]=row
    rows=sorted(unique.values(),key=lambda r:(r['Date'],r['League'],str(r['GameID'])))
    default=str(DATA_DIR / 'games' / f'Games_{start.isoformat()}')+(f'_{end.isoformat()}' if start!=end else '')+'.csv'
    out=Path(args.out or default)
    out.parent.mkdir(parents=True,exist_ok=True)
    if not errors:
        temp=out.with_suffix(out.suffix+'.tmp')
        with temp.open('w',newline='',encoding='utf-8-sig') as f:
            writer=csv.DictWriter(f,fieldnames=FIELDS,delimiter=';')
            writer.writeheader();writer.writerows(rows)
        temp.replace(out)
        print(f'INFO Saved {len(rows)} games: {out}')
        print('INFO Raw JSON: '+str(cache_dir))
    else:
        print(f'ERROR {len(errors)} fetch/validation errors; CSV NOT written to avoid partial output',file=sys.stderr)
        sys.exit(1)

if __name__=='__main__':
    main()
