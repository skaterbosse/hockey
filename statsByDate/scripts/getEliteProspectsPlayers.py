#!/usr/bin/env python3
"""Extract Swedish player profile URLs from saved EliteProspects league HTML pages.

Usage: python3 getEliteProspectsPlayers.py --dir data/ep
Requires: beautifulsoup4 (pip install beautifulsoup4)
"""
import argparse
import csv
import re
import unicodedata
from pathlib import Path
from bs4 import BeautifulSoup

HEADERS=['NameKey','PlayerName','EPPlayerID','EPProfile','League','Position']
PROFILE=re.compile(r'^/player/(\d+)/([a-z0-9-]+)(?:[/?#].*)?$',re.I)

def key(value):
    value=unicodedata.normalize('NFKD',value)
    return re.sub('[^a-z0-9]','', ''.join(c for c in value if not unicodedata.combining(c)).lower())

def clean_name(value):
    return re.sub(r'\s*\([^)]*\)\s*$','',value).strip()

def classify(path):
    name=path.name.lower()
    league='AHL' if 'league_ahl_' in name else 'NHL' if 'league_nhl_' in name else None
    position='Goalie' if 'goalies' in name else 'Skater'
    # Some older captures used nation=swe&tab=goalies in this order.
    return league,position

def read_html(path):
    league,position=classify(path)
    if not league:return []
    soup=BeautifulSoup(path.read_text(encoding='utf-8',errors='replace'),'html.parser')
    found=[]
    for a in soup.select('a[href^="/player/"]'):
        match=PROFILE.fullmatch(a.get('href',''))
        if not match:continue
        name=clean_name(a.get_text(' ',strip=True))
        if not name or not re.search('[A-Za-zÅÄÖåäö]',name):continue
        found.append(dict(NameKey=key(name),PlayerName=name,EPPlayerID=match[1],EPProfile=f'https://www.eliteprospects.com/player/{match[1]}/{match[2]}',League=league,Position=position))
    return found

def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        sample=f.read(2048);f.seek(0)
        delimiter=';' if sample.count(';')>sample.count(',') else ','
        return list(csv.DictReader(f,delimiter=delimiter)),delimiter

def write_csv(path,rows,columns,delimiter=','):
    with path.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns,delimiter=delimiter,extrasaction='ignore')
        writer.writeheader();writer.writerows(rows)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dir',default='data/ep',type=Path,help='Directory with saved EP HTML and nationality CSVs')
    args=parser.parse_args();folder=args.dir
    files=sorted(folder.glob('*.html'))
    if not files:parser.error(f'No HTML files found in {folder}')
    records={};conflicts=set()
    for path in files:
        found=read_html(path)
        print(f'{path.name}: {len(found)} profile links')
        for item in found:
            namekey=item['NameKey']
            if not namekey:continue
            previous=records.get(namekey)
            if previous and previous['EPPlayerID']!=item['EPPlayerID']:
                conflicts.add(namekey);continue
            if previous:
                for col in ('League','Position'):
                    if item[col] not in previous[col].split('|'):previous[col]+='|'+item[col]
            else:records[namekey]=item
    for namekey in conflicts:records.pop(namekey,None)
    rows=sorted(records.values(),key=lambda r:r['NameKey'])
    write_csv(folder/'EP_profiles.csv',rows,HEADERS)
    print(f'EP_profiles.csv: {len(rows)} unique profiles; {len(conflicts)} ambiguous names excluded')
    for path in sorted(folder.glob('*_swe_nationality.csv')):
        data,delimiter=read_csv(path)
        if not data:continue
        columns=list(data[0]);columns=[c for c in columns if c!='EPProfileURL']+['EPProfileURL']
        matched=0
        for item in data:
            player=clean_name(item.get('Player') or item.get('Name') or item.get('PlayerName') or '')
            profile=records.get(key(player))
            item['EPProfileURL']=profile['EPProfile'] if profile else ''
            matched+=bool(profile)
        write_csv(path,data,columns,delimiter)
        print(f'{path.name}: {matched}/{len(data)} profile URLs')
    if conflicts:print('Ambiguous names skipped:',', '.join(sorted(conflicts)))

if __name__=='__main__':main()
