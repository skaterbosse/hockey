"""Validate local snapshots; write only quality reports, never fetch or publish."""
import argparse,csv,json,datetime,os,tempfile
from pathlib import Path
from collections import Counter
from game_quality import validate
from test_data_mode import test_root

def rows(path):
    if not path.exists(): return []
    with path.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f,delimiter=';'))
def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('-d','--date',required=True,type=datetime.date.fromisoformat); p.add_argument('--test-mode',action='store_true'); a=p.parse_args()
    if not a.test_mode: p.error('F7 v1 requires --test-mode; production integration is not enabled')
    root=test_root(p); date=a.date.isoformat(); gp=root/'games'/f'Games_{date}.csv'
    if not gp.is_file(): p.error(f'Missing schedule: {gp}')
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
if __name__=='__main__': main()
