"""Read-only consistency checks for StatsByDate snapshots."""
from collections import Counter
import re
from getGamePlayerStats import (ahl_root, ahl_goals, ahl_players, ahl_shootout,
    nhl_goals, nhl_players, nhl_shootout, ahl_final_problem, unpack_jsonp)

def s(v): return '' if v is None else str(v)
def signature(rows, fields):
    return Counter(tuple(s(r.get(k)) for k in fields) for r in rows)
def seconds(v):
    if not re.fullmatch(r'\d+:\d{2}',s(v)): raise ValueError('invalid time')
    m,n=map(int,v.split(':'))
    if n>=60: raise ValueError('invalid seconds')
    return m*60+n

def validate(g, players, goals, shots, rawdir, recaps, condensed):
    gid=g['GameID']; league=g['League']; checks={}; reasons=[]; actions=set(); details={}
    def check(name, ok, reason, *acts):
        checks[name]='PASS' if ok else 'FAIL'
        if not ok:
            if reason not in reasons: reasons.append(reason)
            actions.update(acts)
    def skip(name): checks[name]='NA'
    def raw(name): return unpack_jsonp((rawdir/league/gid/name).read_text(encoding='utf-8-sig'))
    final=g['Status'] in ('FINAL','OFF')
    check('final',final,'GAME_NOT_FINAL','FETCH_SCHEDULE','FETCH_MATCH_DATA')
    if final:
        try:
            if league=='NHL':
                box=raw('boxscore.json'); pbp=raw('play-by-play.json')
                so=(box.get('gameOutcome') or {}).get('lastPeriodType')=='SO'
                ot=(box.get('gameOutcome') or {}).get('lastPeriodType')=='OT'
                identity=all(s(x.get('id'))==gid for x in (box,pbp))
                finished=all(x.get('gameState') in ('OFF','FINAL') for x in (box,pbp))
                scores=all(s(x[side.lower()+'Team']['score'])==g[side+'Score'] and s(x[side.lower()+'Team']['id'])==g[side+'TeamID'] for x in (box,pbp) for side in ('Home','Away'))
                rp=nhl_players(g,box,({}, {}, {})); rg=nhl_goals(g,pbp); rs=nhl_shootout(g,pbp)
                if g.get('Decision')=='GWS' and not so: scores=False
            else:
                root=ahl_root(raw('gameSummary.json')); d=root['details']; so=root.get('hasShootout') is True; ot='OT' in s(d.get('status')).upper()
                identity=s(d['id'])==gid; finished=s(d['final'])=='1'
                scores=all(s(root[k]['stats']['goals'])==g[side+'Score'] and s(root[k]['info']['id'])==g[side+'TeamID'] for side,k in [('Home','homeTeam'),('Away','visitingTeam')])
                rp=ahl_players(g,root,({}, {}, {})); rg=ahl_goals(g,root); rs=ahl_shootout(g,root)
                problem=ahl_final_problem(g,root,rp,rg,rs)
                check('ahlSnapshot',not problem,'RAW_STATS_MISMATCH','FETCH_MATCH_DATA')
                if problem: details['ahlSnapshot']=problem
            check('rawIdentity',identity,'RAW_ID_MISMATCH','FETCH_MATCH_DATA')
            check('rawFinal',finished,'RAW_NOT_FINAL','FETCH_MATCH_DATA')
            check('rawScore',scores,'SCORE_MISMATCH','FETCH_SCHEDULE','FETCH_MATCH_DATA')
            regular=lambda rr:[r for r in rr if not (so and s(r.get('Period')).upper() in ('5','SO','GWS'))]
            gg=regular(goals); rr=regular(rg)
            home,away=g['HomeCode'],g['AwayCode']; hs,aw=int(g['HomeScore']),int(g['AwayScore']); winner=home if hs>aw else away
            expected={home:hs-int(so and winner==home),away:aw-int(so and winner==away)}
            actual=Counter(r['TeamCode'] for r in gg)
            check('score',all(actual[k]==v for k,v in expected.items()) and not(set(actual)-set(expected)) and (not so or abs(hs-aw)==1),'SCORE_MISMATCH','FETCH_MATCH_DATA')
            fields=('TeamCode','Period','Time','ScorerID','Assist1ID','Assist2ID')
            check('goalEvents',signature(gg,fields)==signature(rr,fields),'GOAL_EVENTS_MISMATCH','FETCH_MATCH_DATA')
            check('duplicateGoals',all(n==1 for n in signature(gg,fields).values()),'DUPLICATE_GOALS','FETCH_MATCH_DATA')
            check('goalTimes',all(1<=int(r['Period'])<= (4 if ot or so else 3) and 0<=seconds(r['Time'])<=(300 if int(r['Period'])==4 else 1200) for r in gg),'INVALID_GOAL_TIME','FETCH_MATCH_DATA')
            ids={(r['TeamCode'],r['PlayerID']) for r in players}
            check('goalIdentities',all(r.get('Scorer') and (r['TeamCode'],r['ScorerID']) in ids and all(not r.get(k+'ID') or (r['TeamCode'],r[k+'ID']) in ids and r.get(k) for k in ('Assist1','Assist2')) for r in gg),'MISSING_PLAYER_IDENTITY','FETCH_MATCH_DATA')
            pf=('TeamCode','PlayerID','Role','Goals','Assists','Points','TimeOnIce','Saves','ShotsAgainst','GoalsAgainst')
            check('playerStats',all(any(r['TeamCode']==k and r['Role']=='skater' for r in players) for k in expected) and signature(players,pf)==signature(rp,pf),'PLAYER_STATS_MISMATCH','FETCH_MATCH_DATA')
            gc=Counter((r['TeamCode'],r['ScorerID']) for r in gg); ac=Counter((r['TeamCode'],r[k]) for r in gg for k in ('Assist1ID','Assist2ID') if r.get(k))
            check('individualScoring',all((r['Role']=='goalie' and r.get('Goals') in ('',None) or int(r.get('Goals') or 0)==gc[r['TeamCode'],r['PlayerID']]) and (r['Role']=='goalie' and r.get('Assists') in ('',None) or int(r.get('Assists') or 0)==ac[r['TeamCode'],r['PlayerID']]) for r in players),'PLAYER_SCORING_MISMATCH','FETCH_MATCH_DATA')
            limit=3900 if so or ot else 3600
            def goalie_ok(k):
                played=[r for r in players if r['TeamCode']==k and r['Role']=='goalie' and r.get('TimeOnIce') and seconds(r['TimeOnIce'])>0]
                return bool(played) and sum(seconds(r['TimeOnIce']) for r in played)<=limit and all(all(r.get(f) not in ('',None) for f in ('Saves','ShotsAgainst','GoalsAgainst')) and int(r['Saves'])+int(r['GoalsAgainst'])==int(r['ShotsAgainst']) for r in played)
            check('goalies',all(goalie_ok(k) for k in expected),'GOALIE_STATS_INCOMPLETE','FETCH_MATCH_DATA')
            sf=('TeamCode','PlayerID','Result','Attempt')+ (('Round','GameWinningGoal') if league=='AHL' else ())
            sc=Counter(r['TeamCode'] for r in shots if r['Result']=='Scored')
            check('shootout',signature(shots,sf)==signature(rs,sf) and (bool(shots) and sc[winner]>sc[away if winner==home else home] if so else not shots),'SHOOTOUT_INCOMPLETE','FETCH_MATCH_DATA')
            if league=='NHL':
                missing=[{'period':r['Period'],'time':r['Time'],'scorerId':r['ScorerID']} for r in gg if not r.get('VideoURL','').startswith(('https://','http://'))]
                details['missingGoalVideos']=missing
                check('goalVideos',not missing,'MISSING_GOAL_VIDEOS','FETCH_GOAL_VIDEOS')
        except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError) as e:
            check('snapshotReadable',False,'MISSING_OR_INVALID_GAME_DATA','FETCH_MATCH_DATA'); details['error']=str(e)
        if league=='NHL':
            check('recap',gid in recaps,'MISSING_RECAP','FETCH_RECAP')
            check('condensed',gid in condensed,'MISSING_CONDENSED','FETCH_CONDENSED')
        else:
            for name in ('goalVideos','recap','condensed'): skip(name)
    return dict(gameId=gid,league=league,gameDate=g['Date'],gameStatus=g['Status'],qualityStatus='INCOMPLETE' if reasons else 'COMPLETE',checks=checks,reasons=reasons,requiredActions=sorted(actions),details=details)
