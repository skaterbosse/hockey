#!/usr/bin/env python3
"""Merge Swedish identities into a persistent, season-independent CSV; never delete rows."""
import argparse, csv, re, unicodedata, tempfile, os
from pathlib import Path
FIELDS=['Name','Nationality','BirthDate','BirthYear','NHLPlayerID','AHLPlayerID','EliteProspectsPlayerID']
IDS=FIELDS[4:]
BASE=Path(__file__).resolve().parent.parent/'data'/'players'
def key(s):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD',s.casefold()) if not unicodedata.combining(c)).split())
def read(p):
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f,delimiter=';'))
def swe(s): return 'SWE' in re.split(r'[^A-Z]+',s.upper())
def compatible(a,b):
    return all(not a[k] or not b[k] or a[k]==b[k] for k in IDS+['BirthDate','BirthYear'])
def merge(rows,r):
    exact=[x for x in rows if any(r[k] and r[k]==x[k] for k in IDS)]
    names=[x for x in rows if key(x['Name'])==key(r['Name']) and compatible(x,r)]
    candidates=exact or names
    if len(candidates)>1 or any(not compatible(x,r) for x in candidates):
        raise ValueError(f'Ambiguous identity: {r["Name"]}; resolve manually before updating')
    if not candidates: rows.append(r); return
    x=candidates[0]
    for k in FIELDS:
        if not x[k]: x[k]=r[k]
    if r['Name'] and r['Name']!=x['Name'] and key(r['Name'])==key(x['Name']) and any(ord(c)>127 for c in r['Name']): x['Name']=r['Name']
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--nhl',type=Path,default=BASE/'NHL_players_nationality_EP.csv'); p.add_argument('--ahl',type=Path,default=BASE/'AHL_players_nationality_v4_3.csv'); p.add_argument('--ep',type=Path,default=BASE/'EP_player_overrides.csv'); p.add_argument('--out',type=Path,default=BASE/'SWE_players.csv'); a=p.parse_args()
    if a.out.resolve() in [x.resolve() for x in (a.nhl,a.ahl,a.ep)]: p.error('Output must not overwrite source')
    rows=read(a.out) if a.out.exists() else []; before=len(rows)
    for r in rows:
        if set(r)!=set(FIELDS) or r['Nationality']!='SWE' or not r['Name']: raise ValueError('Invalid existing register')
    for path,league in [(a.nhl,'NHL'),(a.ahl,'AHL'),(a.ep,'')]:
        for v in read(path):
            if not any(swe(v.get(k,'') or '') for k in ['Nationality','EP_Nationalities']): continue
            r={k:v.get(k,'') or '' for k in FIELDS}; r['Nationality']='SWE'; lg=league or v.get('League','');
            if lg not in ('NHL','AHL') or not r['Name']: raise ValueError(f'Invalid source row: {v}')
            r[lg+'PlayerID']=r[lg+'PlayerID'] or v.get('PlayerID',''); r['NHLPlayerID']=r['NHLPlayerID'] or v.get('MatchedNHLPlayerID',''); r['BirthYear']=r['BirthYear'] or r['BirthDate'][:4]
            merge(rows,r)
    rows.sort(key=lambda r:(key(r['Name']),r['BirthYear'],r['NHLPlayerID'],r['AHLPlayerID']))
    a.out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',encoding='utf-8-sig',newline='',dir=a.out.parent,delete=False) as f:
        tmp=f.name; w=csv.DictWriter(f,fieldnames=FIELDS,delimiter=';'); w.writeheader(); w.writerows(rows)
    os.replace(tmp,a.out); print(f'SWE: {before} -> {len(rows)} (+{len(rows)-before}); {a.out}')
if __name__=='__main__': main()
