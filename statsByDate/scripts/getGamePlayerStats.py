#!/usr/bin/env python3
"""Fetch per-game NHL/AHL boxscores and scoring for Games_YYYY-MM-DD.csv.

Version 5: preferred full player names from registry and EP overrides for
both PlayerStats and Goals, keyed by (league, player ID).

Python 3.10+, standard library only. Raw JSON is cached per league/game.
Missing fields remain blank (not zero). AHL skater TOI is deliberately omitted.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import sys
import time
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / 'data'
PLAYERS_DIR = DATA_DIR / 'players'

AHL_KEY = 'ccb91f29d6744675'  # public read-only site key
AHL_URL = 'https://lscluster.hockeytech.com/feed/index.php'
NHL_URL = 'https://api-web.nhle.com/v1/gamecenter'
PLAYER_FIELDS = ['League','Date','GameID','Team','TeamCode','PlayerID','Name','JerseyNumber','Position','Role',
                 'Nationality','NationalitySource','Goals','Assists','Points','PlusMinus','TimeOnIce',
                 'Shots','PenaltyMinutes','Saves','ShotsAgainst','GoalsAgainst','SavePct','Source']
GOAL_FIELDS = ['League','Date','GameID','Period','Time','Team','TeamCode','ScorerID','Scorer',
               'Assist1ID','Assist1','Assist2ID','Assist2','ScorerJerseyNumber','Assist1JerseyNumber','Assist2JerseyNumber','Strength','EmptyNet','VideoURL','HighlightClipID','Source']


def val(d, *keys):
    if not isinstance(d, dict):
        return None
    for key in keys:
        x = d.get(key)
        if x is not None and x != '':
            return x
    return None


def display(x):
    if isinstance(x, dict):
        return str(val(x,'default','en','name','value') or '')
    return str(x) if x is not None else ''


def first(d,*keys):
    return display(val(d,*keys))


def listify(x):
    if isinstance(x,list): return x
    if isinstance(x,dict):
        for k in ('players','data','rows','items','skaters','goalies'):
            if isinstance(x.get(k),list): return x[k]
    return []


def unpack_jsonp(s):
    """Accept JSON, callback(JSON), and HockeyTech's (JSON) envelope."""
    s = s.strip().lstrip('\ufeff')
    if s.startswith(('{', '[')):
        return json.loads(s)
    if s.startswith('(') and s.rstrip('; \r\n ').endswith(')'):
        return json.loads(s[1:].rstrip('; \r\n ')[:-1])
    m = re.match(r'^[\w.$]+\s*\(', s)
    if m:
        tail = s[m.end():].rstrip('; \r\n ')
        if not tail.endswith(')'):
            raise ValueError('Incomplete JSONP response')
        return json.loads(tail[:-1])
    raise ValueError('Unknown JSON/JSONP response: ' + repr(s[:100]))


def fetch(url,params=None):
    if params: url+='?'+urlencode(params)
    for attempt in range(3):
        try:
            req=Request(url,headers={'User-Agent':'Mozilla/5.0 StatsByDate/1.0','Accept':'application/json, */*'})
            with urlopen(req,timeout=35) as r: body=r.read().decode('utf-8-sig')
            result=unpack_jsonp(body)
            if isinstance(result,dict) and result.get('error'):
                raise ValueError(f"API error: {result['error']}")
            return result
        except Exception:
            if attempt==2: raise
            time.sleep(1.5*(attempt+1))


def cached(path,url,params,refresh):
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding='utf-8')), 'cached'
    obj=fetch(url,params)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(path)
    return obj,'downloaded'


def full_name(name):
    """Avoid replacing a complete name with an abbreviated registry name."""
    parts = str(name or '').strip().split()
    return len(parts) >= 2 and not any(re.fullmatch(r"[A-Za-zÅÄÖåäö]\.?", x) for x in parts)


def load_nationalities(paths, ep_overrides=None):
    ids={}; names={}; canonical={}
    for league,path in paths.items():
        if not path or not path.exists():
            print(f'WARNING {league} nationality file not found: {path}',file=sys.stderr)
            continue
        with path.open(encoding='utf-8-sig',newline='') as f:
            for r in csv.DictReader(f,delimiter=';'):
                pid=first(r,'NHLPlayerID' if league=='NHL' else 'AHLPlayerID','PlayerID')
                nat=first(r,'Nationality','EP_Nationalities').upper()
                name=first(r,'Name').strip()
                if nat:
                    if pid: ids[(league,pid)]=(nat,first(r,'NationalitySource'))
                    if name: names.setdefault((league,name.casefold()),set()).add(nat)
                if pid and full_name(name): canonical[(league,pid)]=name
    if ep_overrides and ep_overrides.exists():
        with ep_overrides.open(encoding='utf-8-sig',newline='') as f:
            for r in csv.DictReader(f,delimiter=';'):
                league=first(r,'League').upper()
                pid=first(r,'PlayerID','NHLPlayerID','AHLPlayerID')
                name=first(r,'Name').strip()
                if league in ('NHL','AHL') and pid and full_name(name):
                    canonical[(league,pid)]=name
        print(f'INFO Loaded preferred names from {ep_overrides}')
    elif ep_overrides:
        print(f'WARNING Preferred-name file not found: {ep_overrides}',file=sys.stderr)
    return ids,names,canonical


def canonical_name(league,pid,api_name,lookups):
    preferred=lookups[2].get((league,str(pid or '')))
    return preferred if preferred else str(api_name or '')


def nationality(league,pid,name,lookups):
    ids,names,_canonical=lookups
    if (league,str(pid)) in ids: return ids[(league,str(pid))]
    found=names.get((league,str(name).casefold().strip()),set())
    if len(found)==1: return (next(iter(found)),'NAME_FALLBACK')
    return ('','')


def player_base(game,team,code,pid,name,pos,role,lookups,source):
    nat,nat_src=nationality(game['League'],pid,name,lookups)
    name=canonical_name(game['League'],pid,name,lookups)
    return dict(League=game['League'],Date=game['Date'],GameID=game['GameID'],Team=team,
                TeamCode=code,PlayerID=str(pid or ''),Name=name,JerseyNumber='',Position=pos,Role=role,
                Nationality=nat,NationalitySource=nat_src,Source=source)


def nhl_players(game,box,lookups):
    result=[]
    bx=box.get('playerByGameStats') or box.get('boxscore') or {}
    roster_numbers={str(x.get('playerId')):x.get('sweaterNumber',x.get('jerseyNumber','')) for x in box.get('rosterSpots',[]) if isinstance(x,dict) and x.get('playerId') is not None}
    for side in ('away','home'):
        info=box.get(side+'Team') or {}
        team=game['AwayTeam' if side=='away' else 'HomeTeam']
        code=game['AwayCode' if side=='away' else 'HomeCode']
        groups=bx.get(side+'Team') or bx.get(side) or {}
        if not isinstance(groups,dict): continue
        for role,keys in [('skater',('forwards','defense','defensemen','skaters')),('goalie',('goalies',))]:
            for key in keys:
                for p in listify(groups.get(key)):
                    if not isinstance(p,dict): continue
                    pid=first(p,'playerId','id')
                    name=(' '.join(x for x in (first(p,'firstName'),first(p,'lastName')) if x)).strip() or first(p,'name')
                    pos=first(p,'position','positionCode')
                    r=player_base(game,team,code,pid,name,pos,role,lookups,'NHL_API')
                    r['JerseyNumber']=first(p,'sweaterNumber','jerseyNumber','jersey','number') or roster_numbers.get(str(pid),'')
                    r.update(Goals=val(p,'goals'),Assists=val(p,'assists'),Points=val(p,'points'),
                             PlusMinus=val(p,'plusMinus'),TimeOnIce=val(p,'toi','timeOnIce'),
                             Shots=val(p,'sog','shots'),PenaltyMinutes=val(p,'pim','penaltyMinutes'))
                    if role=='goalie':
                        r.update(Saves=val(p,'saves'),ShotsAgainst=val(p,'shotsAgainst'),
                                 GoalsAgainst=val(p,'goalsAgainst'),SavePct=(round(float(val(p,'savePctg','savePercentage','savePct'))*100,2) if val(p,'savePctg','savePercentage','savePct') is not None and float(val(p,'savePctg','savePercentage','savePct'))<=1 else val(p,'savePctg','savePercentage','savePct')))
                    result.append(r)
    return result


def nhl_goals(game,pbp):
    rows=[]
    for e in pbp.get('plays',[]):
        if first(e,'typeDescKey','type') not in ('goal','GOAL'): continue
        d=e.get('details') or {}
        teamid=str(val(d,'eventOwnerTeamId') or '')
        home=str(game['HomeTeamID']); away=str(game['AwayTeamID'])
        team,code=(game['HomeTeam'],game['HomeCode']) if teamid==home else ((game['AwayTeam'],game['AwayCode']) if teamid==away else ('',''))
        period=e.get('periodDescriptor') or e.get('period') or {}
        rows.append(dict(League='NHL',Date=game['Date'],GameID=game['GameID'],
            Period=val(period,'number','periodNumber'),Time=val(e,'timeInPeriod'),Team=team,TeamCode=code,
            ScorerID=val(d,'scoringPlayerId'),Scorer='',Assist1ID=val(d,'assist1PlayerId'),Assist1='',
            Assist2ID=val(d,'assist2PlayerId'),Assist2='',Strength=val(d,'strength'),
            EmptyNet=val(d,'emptyNet'),Source='NHL_API'))
    return rows


SHOOTOUT_FIELDS = ['League','Date','GameID','Attempt','Team','TeamCode','PlayerID','Player',
                   'JerseyNumber','Result','Time','Source']


def attach_nhl_goal_videos(rows, landing):
    """Enrich NHL goals from landing summary; match uniquely, never guess clips."""
    clips = {}
    for period in (landing.get('summary') or {}).get('scoring', []):
        pn = str((period.get('periodDescriptor') or {}).get('number') or '')
        for goal in period.get('goals', []):
            if not isinstance(goal, dict):
                continue
            key = (pn, str(goal.get('timeInPeriod') or ''), str(goal.get('playerId') or ''))
            # Duplicate keys are ambiguous and must not be assigned arbitrarily.
            if key in clips:
                clips[key] = None
            else:
                clips[key] = goal

    matched = 0
    for row in rows:
        key = (str(row.get('Period') or ''), str(row.get('Time') or ''), str(row.get('ScorerID') or ''))
        goal = clips.get(key)
        if goal is None and not key[0]:
            # Older cached play-by-play records may have no period. A fallback
            # is safe only when scorer ID + time identify exactly one goal.
            candidates = [(k, v) for k, v in clips.items()
                          if k[1:] == key[1:] and v is not None]
            if len(candidates) == 1:
                key, goal = candidates[0]
                row['Period'] = key[0]
        if not goal:
            continue
        matched += 1
        if not row.get('Strength'):
            strength = str(goal.get('strength') or '').upper()
            row['Strength'] = {'EV': 'EQ', 'PP': 'PP', 'SH': 'SH'}.get(strength, strength)
        if row.get('EmptyNet') in (None, ''):
            row['EmptyNet'] = '1' if goal.get('goalModifier') == 'empty-net' else '0'
        url = goal.get('highlightClipSharingUrl') or ''
        if isinstance(url, str) and url.startswith(('https://nhl.com/video/', 'https://www.nhl.com/video/')):
            row['VideoURL'] = url
            row['HighlightClipID'] = goal.get('highlightClip') or ''
    return matched


def nhl_shootout(game, pbp):
    """NHL SO-period events; only recognized attempt events, not regular-time penalty shots."""
    out=[]
    types={'goal':'Scored','shot-on-goal':'Missed','missed-shot':'Missed',
           'blocked-shot':'Missed'}
    # NHL team IDs are authoritative in play-by-play.json.
    # Games CSV may omit HomeTeamID/AwayTeamID or contain blank values.
    home_id=str((pbp.get('homeTeam') or {}).get('id') or game.get('HomeTeamID') or '')
    away_id=str((pbp.get('awayTeam') or {}).get('id') or game.get('AwayTeamID') or '')
    for e in pbp.get('plays', []):
        period=e.get('periodDescriptor') or e.get('period') or {}
        if str(period.get('periodType','')).upper() not in ('SO','SHOOTOUT'):
            continue
        kind=str(e.get('typeDescKey') or '').lower()
        if kind not in types: continue
        d=e.get('details') or {}
        tid=str(d.get('eventOwnerTeamId') or '')
        if tid==home_id:
            team,code=game['HomeTeam'],game['HomeCode']
        elif tid==away_id:
            team,code=game['AwayTeam'],game['AwayCode']
        else: continue
        pid=d.get('scoringPlayerId') if kind=='goal' else d.get('shootingPlayerId')
        if pid is None: continue
        out.append(dict(League='NHL',Date=game['Date'],GameID=game['GameID'],
            Attempt=len(out)+1,Team=team,TeamCode=code,PlayerID=str(pid),Player='',
            JerseyNumber='',Result=types[kind],Time=e.get('timeInPeriod') or '',Source='NHL_API'))
    return out


def ahl_shootout(game, raw):
    """Extract AHL shootout attempts from HockeyTech gameSummary.

    AHL gameSummary groups attempts by home/visiting team rather than by
    chronological order. Interleave the two lists, home first, to reconstruct
    the alternating attempts. Only use this data when hasShootout is true.
    """
    root=ahl_root(raw)
    if not root.get('hasShootout'):
        return []
    details=root.get('shootoutDetails') or {}
    home_shots=details.get('homeTeamShots') or []
    away_shots=details.get('visitingTeamShots') or []
    if not isinstance(home_shots,list) or not isinstance(away_shots,list):
        return []
    out=[]
    home_info=((root.get('homeTeam') or {}).get('info') or {})
    away_info=((root.get('visitingTeam') or {}).get('info') or {})
    for i in range(max(len(home_shots),len(away_shots))):
        for shots, fallback_info, side in ((home_shots,home_info,'home'),(away_shots,away_info,'away')):
            if i>=len(shots):
                continue
            e=shots[i]
            if not isinstance(e,dict) or not isinstance(e.get('isGoal'),bool):
                continue
            shooter=e.get('shooter') or {}
            if not isinstance(shooter,dict):
                continue
            pid=shooter.get('id')
            name=' '.join(str(shooter.get(k) or '').strip() for k in ('firstName','lastName')).strip()
            team_obj=e.get('shooterTeam') or fallback_info
            tid=str(team_obj.get('id') or '')
            home_id=str(home_info.get('id') or game.get('HomeTeamID') or '')
            away_id=str(away_info.get('id') or game.get('AwayTeamID') or '')
            if tid==home_id:
                team,code=game['HomeTeam'],game['HomeCode']
            elif tid==away_id:
                team,code=game['AwayTeam'],game['AwayCode']
            else:
                continue
            if not pid and not name:
                continue
            out.append(dict(League='AHL',Date=game['Date'],GameID=game['GameID'],
                Attempt=len(out)+1,Team=team,TeamCode=code,PlayerID=str(pid or ''),
                Player=name,JerseyNumber=str(shooter.get('jerseyNumber') or ''),
                Result='Scored' if e['isGoal'] else 'Missed',Time='',Source='AHL_HOCKEYTECH'))
    return out


def ahl_root(raw):
    if isinstance(raw,dict):
        return raw.get('SiteKit') or raw.get('GC') or raw
    if isinstance(raw,list):
        return raw[0] if len(raw)==1 and isinstance(raw[0],dict) else {'events':raw}
    return {}


def ahl_players(game,raw,lookups):
    """HockeyTech gameSummary: team.skaters/goalies entries have info + stats."""
    root=ahl_root(raw)
    out=[]
    for side,aliases in [('home',('homeTeam','home_team')),('away',('visitingTeam','awayTeam','visiting_team'))]:
        team_obj=next((root[k] for k in aliases if isinstance(root.get(k),dict)),{})
        team=game['HomeTeam' if side=='home' else 'AwayTeam']
        code=game['HomeCode' if side=='home' else 'AwayCode']
        for role,key in [('skater','skaters'),('goalie','goalies')]:
            for entry in listify(team_obj.get(key)):
                if not isinstance(entry,dict): continue
                info=entry.get('info') if isinstance(entry.get('info'),dict) else entry
                stats=entry.get('stats') if isinstance(entry.get('stats'),dict) else entry
                pid=first(info,'id','playerId','player_id','personId')
                name=first(info,'name','playerName','fullName')
                if not name:
                    name=' '.join(filter(None,(first(info,'firstName','first_name'),first(info,'lastName','last_name'))))
                if not pid or not name:
                    raise ValueError(f'AHL {game["GameID"]} {side} {role}: missing player ID/name; fields={list(entry)}')
                pos=first(info,'position','position_code')
                r=player_base(game,team,code,pid,name,pos,role,lookups,'AHL_HOCKEYTECH')
                r['JerseyNumber']=first(info,'jerseyNumber','sweaterNumber','jersey','number','uniformNumber')
                r.update(Goals=val(stats,'goals','g'),Assists=val(stats,'assists','a'),
                         Points=val(stats,'points','pts'),PlusMinus=val(stats,'plusMinus','plus_minus','plusminus'),
                         TimeOnIce=(val(stats,'timeOnIce','toi') if role=='goalie' else None),Shots=val(stats,'shots','shots_on_goal','sog'),
                         PenaltyMinutes=val(stats,'penaltyMinutes','penalty_minutes','pim'))
                if role=='goalie':
                    saves=val(stats,'saves'); shots=val(stats,'shotsAgainst','shots_against')
                    r.update(Saves=saves,ShotsAgainst=shots,
                             GoalsAgainst=val(stats,'goalsAgainst','goals_against'),
                             SavePct=(round(100*float(saves)/float(shots),2) if shots and saves is not None else None))
                out.append(r)
    if not out: raise ValueError(f'AHL {game["GameID"]}: no player entries in homeTeam/visitingTeam')
    return out


def ahl_goals(game, raw):
    """Parse HockeyTech statviewfeed/gameSummary periods[].goals[]."""
    root = ahl_root(raw)
    goals = []

    def player_info(p):
        if not isinstance(p, dict):
            return '', ''
        return str(p.get('id') or ''), ' '.join(str(p.get(k) or '').strip()
                                               for k in ('firstName', 'lastName')).strip() or first(p, 'name')

    for period in root.get('periods', []):
        if not isinstance(period, dict):
            continue
        info = period.get('info') or {}
        period_number = str(info.get('id') or info.get('shortName') or '')
        for e in period.get('goals', []):
            if not isinstance(e, dict):
                continue
            scorer_id, scorer = player_info(e.get('scoredBy'))
            if not scorer_id and not scorer:
                continue
            assists = e.get('assists') or []
            a1id, a1 = player_info(assists[0]) if len(assists) > 0 else ('', '')
            a2id, a2 = player_info(assists[1]) if len(assists) > 1 else ('', '')
            team_obj = e.get('team') or {}
            tid = str(team_obj.get('id') or '')
            if tid == str(game.get('HomeTeamID')):
                team, code = game['HomeTeam'], game['HomeCode']
            elif tid == str(game.get('AwayTeamID')):
                team, code = game['AwayTeam'], game['AwayCode']
            else:
                team = team_obj.get('name') or ''
                code = team_obj.get('abbreviation') or ''
            props = e.get('properties') or {}
            is_pp = str(props.get('isPowerPlay', '0')) == '1'
            is_sh = str(props.get('isShortHanded', '0')) == '1'
            is_ps = str(props.get('isPenaltyShot', '0')) == '1'
            strength = 'PS' if is_ps else 'PP' if is_pp else 'SH' if is_sh else 'EQ'
            goals.append(dict(
                League='AHL', Date=game['Date'], GameID=game['GameID'],
                Period=period_number, Time=e.get('time') or '',
                Team=team, TeamCode=code,
                ScorerID=scorer_id, Scorer=scorer,
                Assist1ID=a1id, Assist1=a1,
                Assist2ID=a2id, Assist2=a2,
                Strength=strength,
                EmptyNet='1' if str(props.get('isEmptyNet', '0')) == '1' else '0',
                Source='AHL_HOCKEYTECH'))
    return goals


def ahl_find_player_groups(root):
    """Find player arrays in multiple HockeyTech gameSummary layouts."""
    candidates=[]
    def walk(obj,path=(),depth=0):
        if depth>7: return
        if isinstance(obj,dict):
            for k,v in obj.items():
                key=str(k).lower()
                if isinstance(v,list) and v and isinstance(v[0],dict):
                    if any(word in key for word in ('skater','goalie','roster','player','lineup')):
                        candidates.append((path+(k,),v))
                if isinstance(v,(dict,list)): walk(v,path+(k,),depth+1)
        elif isinstance(obj,list):
            for item in obj[:5]:
                if isinstance(item,(dict,list)): walk(item,path,depth+1)
    walk(root)
    return candidates


def ahl_players_v2(game,raw,lookups):
    root=ahl_root(raw)
    result=ahl_players(game,raw,lookups)
    if result: return result
    for path,entries in ahl_find_player_groups(root):
        low='/'.join(map(str,path)).lower()
        side=('home' if 'home' in low else 'away' if any(x in low for x in ('away','visiting','visitor')) else '')
        if not side: continue
        team=game['HomeTeam' if side=='home' else 'AwayTeam']
        code=game['HomeCode' if side=='home' else 'AwayCode']
        for p in entries:
            if not isinstance(p,dict): continue
            obj=p.get('player') if isinstance(p.get('player'),dict) else p
            pid=first(obj,'player_id','playerId','id','personId')
            name=first(obj,'name','player_name','playerName','fullName')
            if not name: name=' '.join(x for x in (first(obj,'firstName','first_name'),first(obj,'lastName','last_name')) if x)
            if not name and not pid: continue
            role='goalie' if ('goalie' in low or first(obj,'position','position_code').upper()=='G') else 'skater'
            pos=first(obj,'position','position_code')
            stats=p.get('stats') if isinstance(p.get('stats'),dict) else p
            r=player_base(game,team,code,pid,name,pos,role,lookups,'AHL_HOCKEYTECH')
            r.update(Goals=val(stats,'goals','g'),Assists=val(stats,'assists','a'),
                     Points=val(stats,'points','pts'),PlusMinus=val(stats,'plus_minus','plusMinus','plusminus'),
                     TimeOnIce=(val(stats,'timeOnIce','toi') if role=='goalie' else None),Shots=val(stats,'shots','shots_on_goal','sog'),
                     PenaltyMinutes=val(stats,'penalty_minutes','penaltyMinutes','pim'))
            if role=='goalie':
                r.update(Saves=val(stats,'saves'),ShotsAgainst=val(stats,'shots_against','shotsAgainst'),
                         GoalsAgainst=val(stats,'goals_against','goalsAgainst'),SavePct=val(stats,'save_percentage','savePct'))
            result.append(r)
    unique={}
    for r in result:
        key=(r['TeamCode'],r['PlayerID'] or r['Name'])
        unique.setdefault(key,r)
    return list(unique.values())


def diagnostic_structure(raw):
    root=ahl_root(raw)
    groups=ahl_find_player_groups(root)
    return 'top-level keys=' + ','.join(map(str,list(root)[:35])) + '; player arrays=' + ','.join('/'.join(map(str,p)) for p,_ in groups[:20])

def fill_goal_names(goals,players,lookups):
    names={(p['League'],str(p['PlayerID'])):p['Name'] for p in players if p['PlayerID']}
    jerseys={(p['League'],str(p['PlayerID'])):p.get('JerseyNumber','') for p in players if p['PlayerID']}
    for g in goals:
        league=g['League']
        for field,idfield in [('Scorer','ScorerID'),('Assist1','Assist1ID'),('Assist2','Assist2ID')]:
            pid=str(g.get(idfield) or '')
            if not pid: continue
            current=g.get(field) or ''
            g[field]=canonical_name(league,pid,names.get((league,pid),current),lookups)
            g[field+'JerseyNumber']=jerseys.get((league,pid),'')


def save_csv(path,fields,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.csv.tmp')
    with temp.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter=';',extrasaction='ignore')
        w.writeheader();w.writerows(rows)
    temp.replace(path)


def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-d','--date',required=True,help='YYYY-MM-DD (reads data/games/Games_DATE.csv)')
    ap.add_argument('--games-file',type=Path,help='Override match CSV')
    ap.add_argument('--data-dir',type=Path,default=DATA_DIR)
    ap.add_argument('-l','--league',choices=('NHL','AHL','ALL'),default='ALL')
    ap.add_argument('--nhl-players',type=Path,default=PLAYERS_DIR / 'NHL_players_nationality_EP.csv')
    ap.add_argument('--ahl-players',type=Path,default=PLAYERS_DIR / 'AHL_players_nationality_v4_3.csv')
    ap.add_argument('--ep-overrides',type=Path,default=PLAYERS_DIR / 'EP_player_overrides.csv',help='Preferred full names by league/player ID')
    ap.add_argument('--ahl-key',default=os.getenv('AHL_API_KEY',AHL_KEY))
    ap.add_argument('--refresh',action='store_true')
    ap.add_argument('--include-unfinished',action='store_true',help='Include LIVE/SCHEDULED games')
    ap.add_argument('--strict',action='store_true',help='Stop on first API or parsing error')
    args=ap.parse_args()
    gamefile=args.games_file or args.data_dir/'games'/f'Games_{args.date}.csv'
    if not gamefile.exists(): ap.error(f'Games file not found: {gamefile}')
    with gamefile.open(encoding='utf-8-sig',newline='') as f:
        games=list(csv.DictReader(f,delimiter=';'))
    # Include games already underway, but do not request statistics for future games.
    active_statuses = ('LIVE', 'IN_PROGRESS', 'INTERMISSION', 'CRIT')
    completed_statuses = ('FINAL', 'OFF')
    games=[g for g in games if g.get('Date')==args.date and (args.league=='ALL' or g['League']==args.league)
           and (args.include_unfinished or str(g.get('Status','')).strip().upper() in completed_statuses + active_statuses)]
    lookups=load_nationalities({'NHL':args.nhl_players,'AHL':args.ahl_players},args.ep_overrides)
    players=[];goals=[];shootouts=[];errors=[];successful_games=set()
    for g in games:
        league=g['League'];gid=g['GameID']
        base=args.data_dir/'raw'/'games'/league/gid
        # Always update ongoing games; reuse finished-game cache as before.
        refresh_game = args.refresh or str(g.get('Status','')).strip().upper() in active_statuses
        try:
            if league=='NHL':
                box,state1=cached(base/'boxscore.json',f'{NHL_URL}/{gid}/boxscore',None,refresh_game)
                pbp,state2=cached(base/'play-by-play.json',f'{NHL_URL}/{gid}/play-by-play',None,refresh_game)
                p=nhl_players(g,box,lookups);sc=nhl_goals(g,pbp);so=nhl_shootout(g,pbp)
                try:
                    landing,landing_state=cached(base/'landing.json',f'{NHL_URL}/{gid}/landing',None,refresh_game)
                    matched=attach_nhl_goal_videos(sc,landing)
                    video_count=sum(bool(r.get('VideoURL')) for r in sc)
                    print(f'INFO NHL {gid}: matched {matched}/{len(sc)} landing goals; {video_count} video links ({landing_state})')
                except Exception as video_error:
                    print(f'WARNING NHL {gid}: goal video links unavailable: {video_error}',file=sys.stderr)
            elif league=='AHL':
                params=dict(feed='statviewfeed',view='gameSummary',key=args.ahl_key,
                            client_code='ahl',league_id='4',site_id='3',lang='en',game_id=gid)
                box,state1=cached(base/'gameSummary.json',AHL_URL,params,refresh_game)
                p=ahl_players(g,box,lookups);sc=ahl_goals(g,box);so=ahl_shootout(g,box)
                state2=''
            else: continue
            if not p and not (refresh_game and (sc or so)):
                raise ValueError('No players parsed; ' + (diagnostic_structure(box) if league=='AHL' else 'inspect cached boxscore.json'))
            if league=='AHL' and any(not r.get('PlayerID') or not r.get('Name') for r in p):
                raise ValueError('AHL player validation failed: missing PlayerID or Name')
            players.extend(p);goals.extend(sc);shootouts.extend(so)
            successful_games.add((league, gid))
            print(f'INFO {league} {gid}: {len(p)} players, {len(sc)} goals, {len(so)} shootout attempts ({state1}{", "+state2 if state2 else ""})')
            if league=='AHL' and not sc:
                print(f'WARNING AHL {gid}: goal summary could not be parsed; raw gameSummary.json retained',file=sys.stderr)
        except Exception as e:
            msg=f'{league} {gid}: {e}';errors.append(msg)
            print(f'ERROR {msg}',file=sys.stderr)
            if args.strict: break
    fill_goal_names(goals,players,lookups)
    names={(r['League'],str(r['PlayerID'])):r for r in players if r.get('PlayerID')}
    for row in shootouts:
        player=names.get((row['League'],row['PlayerID']))
        if player:
            row['Player']=player.get('Name') or row['Player']
            row['JerseyNumber']=player.get('JerseyNumber') or ''
    out=args.data_dir/'playerstats'
    out.mkdir(parents=True,exist_ok=True)
    if errors:
        errorfile=out/f'Errors_{args.date}.txt'
        errorfile.write_text('\n'.join(errors)+'\n',encoding='utf-8')
    if errors and not players:
        print('ERROR No successful games: existing CSV files preserved',file=sys.stderr)
        return 1
    def merged_rows(filename,fields,newrows):
        path=out/filename
        previous=[]
        if path.exists():
            with path.open(encoding='utf-8-sig',newline='') as f:
                previous=list(csv.DictReader(f,delimiter=';'))
        successful=successful_games
        previous=[r for r in previous if (r.get('League'),r.get('GameID')) not in successful]
        return previous+newrows
    playerfile=f'PlayerStats_{args.date}.csv'
    goalfile=f'Goals_{args.date}.csv'
    allplayers=merged_rows(playerfile,PLAYER_FIELDS,players)
    allgoals=merged_rows(goalfile,GOAL_FIELDS,goals)
    save_csv(out/playerfile,PLAYER_FIELDS,allplayers)
    save_csv(out/goalfile,GOAL_FIELDS,allgoals)
    shootfile=f'Shootout_{args.date}.csv'
    allshootouts=merged_rows(shootfile,SHOOTOUT_FIELDS,shootouts)
    save_csv(out/shootfile,SHOOTOUT_FIELDS,allshootouts)
    print(f'INFO Saved {len(allshootouts)} shootout attempts to {out/shootfile}')
    print(f'INFO Saved {len(allplayers)} player rows, {len(allgoals)} goal rows to {out} (merged)')
    if errors:
        errorfile=out/f'Errors_{args.date}.txt'
        print(f'WARNING {len(errors)} games failed; see {errorfile}',file=sys.stderr)
        return 1
    return 0

if __name__=='__main__':
    sys.exit(main())
