#!/usr/bin/env python3
"""Audit Swedish EP overrides vs NHL/AHL registries and ALL PlayerStats_*.csv.
No API calls. Strict ID matching; name matches only flagged for manual review.
"""
import argparse, csv, re, sys
from collections import Counter, defaultdict
from pathlib import Path

FIELDS=['Category','League','EPPlayerID','EPName','EP_Nationalities','RegistryPlayerID','RegistryName','RegistryNationality','RegistrySource','StatsPlayerID','StatsName','StatsNationality','StatsDate','StatsGameID','Details']

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        sample=f.read(4096); f.seek(0)
        delim=';' if sample.count(';')>=sample.count(',') else ','
        return list(csv.DictReader(f,delimiter=delim))

def clean(v):return str(v or '').strip()
def norm(v):return re.sub(r'[^\w]+','',clean(v).casefold())
def swe(v):return 'SWE' in re.split(r'[,;/|\s]+',clean(v).upper())
def write(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,delimiter=';',extrasaction='ignore');w.writeheader();w.writerows(rows)

def locate(path,search_dirs):
    if path.is_file():return path
    if len(path.parts)==1:
        for base in search_dirs:
            q=base/path
            if q.is_file():return q
    return path

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ep',type=Path,default=Path('EP_player_overrides.csv'))
    ap.add_argument('--nhl',type=Path,default=Path('NHL_players_nationality_EP.csv'))
    ap.add_argument('--ahl',type=Path,default=Path('AHL_players_nationality_v4_3.csv'))
    ap.add_argument('--stats-dir',type=Path,default=Path('data/playerstats'))
    ap.add_argument('--out-dir',type=Path,default=Path('data/audit'))
    args=ap.parse_args()
    bases=[Path('.'),Path('data'),Path('data/nationality'),Path('data/raw'),Path('data/players')]
    paths={key:locate(getattr(args,key),bases) for key in ('ep','nhl','ahl')}
    for key,p in paths.items():
        if not p.is_file():sys.exit(f'ERROR: Missing {key}: {p} (specify --{key} PATH)')
    ep=[r for r in read(paths['ep']) if swe(r.get('EP_Nationalities'))]
    reg={league:read(paths[league.lower()]) for league in ('NHL','AHL')}
    reg_id={'NHL':'NHLPlayerID','AHL':'AHLPlayerID'}
    by_reg=defaultdict(list); reg_names=defaultdict(list)
    for league,records in reg.items():
        for r in records:
            pid=clean(r.get(reg_id[league]));name=norm(r.get('Name'))
            if pid:by_reg[(league,pid)].append(r)
            if name:reg_names[(league,name)].append(r)
    stats_files=sorted(args.stats_dir.glob('PlayerStats_*.csv')) if args.stats_dir.is_dir() else []
    by_stats=defaultdict(list);stats_names=defaultdict(list)
    stats_count=0
    for file in stats_files:
        for r in read(file):
            league=clean(r.get('League')).upper();pid=clean(r.get('PlayerID'))
            if league not in ('NHL','AHL'):continue
            r=dict(r);r['_file']=file.name;stats_count+=1
            if pid:by_stats[(league,pid)].append(r)
            if norm(r.get('Name')):stats_names[(league,norm(r.get('Name')))].append(r)
    report=[];counts=Counter();unique=set()
    for e in ep:
        league=clean(e.get('League')).upper();pid=clean(e.get('PlayerID'));name=clean(e.get('Name'))
        if league not in ('NHL','AHL') or not pid:
            report.append(dict(Category='INVALID_EP',League=league,EPPlayerID=pid,EPName=name,Details='Invalid league or missing ID'));counts['INVALID_EP']+=1;continue
        key=(league,pid)
        if key in unique:
            report.append(dict(Category='DUPLICATE_EP',League=league,EPPlayerID=pid,EPName=name,Details='Duplicate EP record'));counts['DUPLICATE_EP']+=1;continue
        unique.add(key)
        base=dict(League=league,EPPlayerID=pid,EPName=name,EP_Nationalities=clean(e.get('EP_Nationalities')))
        regs=by_reg.get(key,[])
        if not regs:
            alt=reg_names.get((league,norm(name)),[])
            report.append(dict(base,Category='REGISTRY_ID_MISSING',Details='Name candidates: '+', '.join(clean(x.get(reg_id[league])) for x in alt) if alt else 'No registry record'))
            counts['REGISTRY_ID_MISSING']+=1
        else:
            for r in regs:
                rbase=dict(base,RegistryPlayerID=clean(r.get(reg_id[league])),RegistryName=clean(r.get('Name')),RegistryNationality=clean(r.get('Nationality')),RegistrySource=clean(r.get('NationalitySource')))
                if not swe(r.get('Nationality')):
                    report.append(dict(rbase,Category='REGISTRY_WRONG_NATIONALITY',Details='EP SWE, registry not SWE'));counts['REGISTRY_WRONG_NATIONALITY']+=1
                elif norm(name)!=norm(r.get('Name')):
                    report.append(dict(rbase,Category='REGISTRY_NAME_MISMATCH',Details='ID matches; name differs'));counts['REGISTRY_NAME_MISMATCH']+=1
                else:counts['REGISTRY_OK']+=1
        matches=by_stats.get(key,[])
        if not matches:
            alt=stats_names.get((league,norm(name)),[])
            if alt:
                for s in alt:
                    report.append(dict(base,Category='STATS_ID_MISMATCH',StatsPlayerID=clean(s.get('PlayerID')),StatsName=clean(s.get('Name')),StatsNationality=clean(s.get('Nationality')),StatsDate=clean(s.get('Date')),StatsGameID=clean(s.get('GameID')),Details=s['_file']))
                counts['STATS_ID_MISMATCH']+=1
            else:counts['NOT_IN_COLLECTED_MATCHES']+=1
            continue
        counts['EP_PLAYERS_IN_STATS']+=1
        for s in matches:
            sb=dict(base,StatsPlayerID=clean(s.get('PlayerID')),StatsName=clean(s.get('Name')),StatsNationality=clean(s.get('Nationality')),StatsDate=clean(s.get('Date')),StatsGameID=clean(s.get('GameID')),Details=s['_file'])
            if not swe(s.get('Nationality')):
                report.append(dict(sb,Category='STATS_WRONG_NATIONALITY'));counts['STATS_WRONG_NATIONALITY']+=1
            elif norm(name)!=norm(s.get('Name')):
                report.append(dict(sb,Category='STATS_NAME_MISMATCH'));counts['STATS_NAME_MISMATCH']+=1
            else:counts['STATS_OK_ROWS']+=1
    # All match records flagged SWE should map to a Swedish registry identity.
    for key,rows in by_stats.items():
        if key in unique:continue
        for s in rows:
            if swe(s.get('Nationality')):
                report.append(dict(Category='SWE_STATS_NOT_IN_EP',League=key[0],StatsPlayerID=key[1],StatsName=clean(s.get('Name')),StatsNationality=clean(s.get('Nationality')),StatsDate=clean(s.get('Date')),StatsGameID=clean(s.get('GameID')),Details=s['_file']))
                counts['SWE_STATS_NOT_IN_EP']+=1
    args.out_dir.mkdir(parents=True,exist_ok=True)
    outfile=args.out_dir/'EP_SWE_audit.csv';write(outfile,report)
    print('EP Swedish records:',len(ep),'unique:',len(unique))
    print('PlayerStats files:',len(stats_files),'rows:',stats_count)
    for k in ('REGISTRY_OK','REGISTRY_ID_MISSING','REGISTRY_WRONG_NATIONALITY','REGISTRY_NAME_MISMATCH','EP_PLAYERS_IN_STATS','STATS_OK_ROWS','NOT_IN_COLLECTED_MATCHES','STATS_WRONG_NATIONALITY','STATS_ID_MISMATCH','STATS_NAME_MISMATCH','SWE_STATS_NOT_IN_EP','DUPLICATE_EP','INVALID_EP'):
        print(f'{k}: {counts[k]}')
    print('Detailed findings:',outfile)
    if not stats_files:print('WARNING: No PlayerStats files found; only registry check was possible.')
    errors=sum(counts[k] for k in ('REGISTRY_ID_MISSING','REGISTRY_WRONG_NATIONALITY','STATS_WRONG_NATIONALITY','STATS_ID_MISMATCH','DUPLICATE_EP','INVALID_EP'))
    return 1 if errors else 0
if __name__=='__main__':sys.exit(main())
