"""Validate local snapshots; write only quality reports, never fetch or publish."""
import argparse,csv,json,datetime,os,tempfile
from pathlib import Path
from collections import Counter
from zoneinfo import ZoneInfo
from game_quality import validate
from test_data_mode import test_root

def rows(path):
    if not path.exists(): return []
    with path.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f,delimiter=';'))
def validate_date(root, date):
    gp=root/'games'/f'Games_{date}.csv'
    if not gp.is_file(): raise FileNotFoundError(f'Missing schedule: {gp}')
    games=rows(gp); tables=[rows(root/'playerstats'/f'{n}_{date}.csv') for n in ('PlayerStats','Goals','Shootout')]
    videos=[{r['GameID'] for r in rows(root/'recaps'/f'NHL_{n}.csv') if r.get('VideoURL','').startswith(('http://','https://'))} for n in ('Recaps','CondensedGames')]
    result=[]
    for g in games:
        result.append(validate(g,*[[r for r in t if r['GameID']==g['GameID'] and r['League']==g['League']] for t in tables],root/'raw/games',*videos))
    counts=Counter(r['qualityStatus'] for r in result); report=dict(schemaVersion=1,date=date,generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),summary=dict(counts),games=result)
    out=root/'quality'/f'Quality_{date}.json'; out.parent.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=out.parent,delete=False) as f:
        json.dump(report,f,ensure_ascii=False,indent=2); f.write('\n'); tmp=f.name
    os.replace(tmp,out)
    for r in result: print(r['league'],r['gameId'],r['qualityStatus'],', '.join(r['reasons']))
    print(dict(counts),'->',out)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('-d','--date',type=datetime.date.fromisoformat)
    group.add_argument('--recent',action='store_true',help='Validate existing schedules from today minus 3 days through today')
    p.add_argument('--anchor',type=datetime.date.fromisoformat,help='Reference date for --recent')
    p.add_argument('--test-mode',action='store_true')
    p.add_argument('--production',action='store_true',help='Explicitly write production quality reports')
    a=p.parse_args()
    if a.test_mode == a.production: p.error('Select exactly one of --test-mode or --production')
    if a.anchor and not a.recent: p.error('--anchor requires --recent')
    root=test_root(p) if a.test_mode else Path(__file__).resolve().parent.parent/'data'
    if not root.is_dir(): p.error(f'Missing data directory: {root}')
    if a.recent:
        anchor=a.anchor or datetime.datetime.now(ZoneInfo('Europe/Stockholm')).date()
        days=[anchor-datetime.timedelta(days=i) for i in (3,2,1,0)]
    else: days=[a.date]
    for day in days:
        date=day.isoformat()
        if a.recent and day < anchor-datetime.timedelta(days=1) and not (root/'games'/f'Games_{date}.csv').is_file():
            print(f'INFO Quality {date}: no historical schedule, skipping')
            continue
        validate_date(root,date)

if __name__=='__main__': main()
