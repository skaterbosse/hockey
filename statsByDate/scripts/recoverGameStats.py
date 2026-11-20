"""Standalone test-only targeted recovery. No Git actions. Dry-run does not write."""
import argparse, json, subprocess, sys, os, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from test_data_mode import test_root
from validateGameQuality import rows, validate_date
from game_recovery import timestamp, end_reference, decision
HERE = Path(__file__).resolve().parent

def save(path, data):
    path.parent.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
        json.dump(data,f,indent=2); f.write('\n'); tmp=f.name
    os.replace(tmp,path)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--test-mode',action='store_true',required=True)
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--now',help='ISO timestamp for reproducible dry-run only')
    a=p.parse_args()
    if a.now and not a.dry_run: p.error('--now requires --dry-run')
    root=test_root(p)
    now=timestamp(a.now) if a.now else datetime.now(timezone.utc)
    cfg=json.loads((HERE/'scheduler_config.json').read_text())
    hours=cfg['maxStatsRecoveryHoursAfterFinal']; interval=cfg['statsRecoveryIntervalMinutes']
    if not 0<hours<=48 or not 0<interval<=1440: p.error('Invalid recovery configuration')
    statepath=root/'quality/recovery_state.json'
    state=json.loads(statepath.read_text()) if statepath.exists() else {}
    anchor=now.astimezone(ZoneInfo('Europe/Stockholm')).date()
    failures=0; selected=0
    for i in (3,2,1,0):
        date=(anchor-timedelta(days=i)).isoformat()
        report=root/'quality'/f'Quality_{date}.json'; schedule=root/'games'/f'Games_{date}.csv'
        if not report.exists() or not schedule.exists():
            print(date,'SKIP missing schedule or quality report'); continue
        # Refresh report before making live decisions; dry run uses existing reports.
        if not a.dry_run: validate_date(root,date)
        data=json.loads(report.read_text())
        if data['date']!=date or data['schemaVersion']!=1: raise ValueError('Unexpected report')
        games={(g['League'],g['GameID']):g for g in rows(schedule)}
        seen=set()
        for q in data['games']:
            key=(q['league'],q['gameId']); g=games.get(key)
            if key in seen or not g or q['gameDate']!=date or g['Date']!=date: raise ValueError('Report/schedule identity mismatch')
            seen.add(key)
            if key[0] not in ('NHL','AHL') or not key[1].isdigit(): raise ValueError('Invalid game identity')
            skey=':'.join(key); last=state.get(skey,{}).get('lastAttempt')
            try: ref,source=end_reference(g,root)
            except (ValueError,KeyError,TypeError): ref,source=None,'UNKNOWN'
            current=now if a.dry_run else datetime.now(timezone.utc)
            action=decision(g,q,current,ref,hours,timestamp(last) if last else None,interval)
            print(date,*key,action,source, 'deadline='+ (ref+timedelta(hours=hours)).isoformat() if ref else '')
            if action!='RECOVER': continue
            selected+=1
            cmd=[sys.executable,str(HERE/'getGamePlayerStats.py'),'-d',date,'-l',key[0],'--game-id',key[1],'--refresh','--strict','--test-mode']
            if a.dry_run: continue
            state[skey]={'lastAttempt':current.isoformat(),'result':'STARTED'}; save(statepath,state)
            rc=subprocess.run(cmd).returncode
            state[skey]['result']='FETCH_FAILED' if rc else 'FETCH_OK'; save(statepath,state)
            failures+=bool(rc)
            validate_date(root,date)
    print(f'Selected: {selected}; failed fetches: {failures}; dry-run: {a.dry_run}')
    return int(bool(failures))

if __name__=='__main__': sys.exit(main())
