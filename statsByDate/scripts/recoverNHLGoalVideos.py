"""Refresh missing NHL goal links without fetching boxscore or play-by-play."""
import argparse,csv,copy,datetime
from pathlib import Path
from collections import Counter
from zoneinfo import ZoneInfo
from getGamePlayerStats import fetch, NHL_URL, attach_nhl_goal_videos, save_csv
from validateGameQuality import rows
from test_data_mode import test_root

def recover_day(root, day, dry=False):
    path=root/'playerstats'/f'Goals_{day}.csv'
    if not path.is_file(): return 0
    with path.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f,delimiter=';'); fields=reader.fieldnames; goals=list(reader)
    final={g['GameID'] for g in rows(root/'games'/f'Games_{day}.csv') if g['League']=='NHL' and g['Status'] in ('FINAL','OFF') and g['GameID'].isdigit()}
    changed=0
    for gid in sorted(final):
        group=[r for r in goals if r['League']=='NHL' and r['GameID']==gid]
        key=lambda r: (r['Period'],r['Time'],r['ScorerID'])
        counts=Counter(map(key,group))
        missing=[r for r in group if not r.get('VideoURL','').startswith(('http://','https://')) and r['Period'] not in ('5','SO','GWS') and counts[key(r)]==1 and all(key(r))]
        if not missing: continue
        print(f'NHL {gid}: missing goal videos {len(missing)}')
        if dry: continue
        try:
            landing=fetch(f'{NHL_URL}/{gid}/landing')
            if str(landing.get('id'))!=gid: raise ValueError('Wrong landing GameID')
            candidates=copy.deepcopy(missing)
            attach_nhl_goal_videos(candidates,landing)
            for old,new in zip(missing,candidates):
                if new.get('VideoURL','').startswith(('https://nhl.com/video/','https://www.nhl.com/video/')):
                    old['VideoURL']=new['VideoURL']; old['HighlightClipID']=new.get('HighlightClipID',''); changed+=1
        except Exception as exc: print(f'WARNING NHL {gid}: {exc}')
    if changed: save_csv(path,fields,goals)
    return changed

def main():
    p=argparse.ArgumentParser(description=__doc__); m=p.add_mutually_exclusive_group(required=True)
    m.add_argument('--test-mode',action='store_true'); m.add_argument('--production',action='store_true'); p.add_argument('--dry-run',action='store_true'); p.add_argument('--date',type=datetime.date.fromisoformat)
    a=p.parse_args(); root=test_root(p) if a.test_mode else Path(__file__).resolve().parent.parent/'data'
    if not root.is_dir(): p.error('Missing data root')
    anchor=a.date or datetime.datetime.now(ZoneInfo('Europe/Stockholm')).date()
    print('Updated goal links:',sum(recover_day(root,(anchor-datetime.timedelta(days=i)).isoformat(),a.dry_run) for i in (3,2,1,0)))
if __name__=='__main__': main()
