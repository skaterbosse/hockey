#!/usr/bin/env python3
"""Import nationality-filtered Elite Prospects CSVs into NHL/AHL registers.

EP exports are *positive* nationality evidence, not a complete nationality list.
Never overwrites official Nationality, player ID, or manually maintained jersey numbers.
Use -nat SWE -if register.csv [...] -ep export.csv [...].
"""
import argparse
import csv
import glob
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

NHL_TEAMS = {
 'Anaheim Ducks':'ANA','Boston Bruins':'BOS','Buffalo Sabres':'BUF','Calgary Flames':'CGY',
 'Carolina Hurricanes':'CAR','Chicago Blackhawks':'CHI','Colorado Avalanche':'COL',
 'Columbus Blue Jackets':'CBJ','Dallas Stars':'DAL','Detroit Red Wings':'DET',
 'Edmonton Oilers':'EDM','Florida Panthers':'FLA','Los Angeles Kings':'LAK',
 'Minnesota Wild':'MIN','Montréal Canadiens':'MTL','Montreal Canadiens':'MTL',
 'Nashville Predators':'NSH','New Jersey Devils':'NJD','New York Islanders':'NYI',
 'New York Rangers':'NYR','Ottawa Senators':'OTT','Philadelphia Flyers':'PHI',
 'Pittsburgh Penguins':'PIT','San Jose Sharks':'SJS','Seattle Kraken':'SEA',
 'St. Louis Blues':'STL','St Louis Blues':'STL','Tampa Bay Lightning':'TBL',
 'Toronto Maple Leafs':'TOR','Utah Mammoth':'UTA','Utah Hockey Club':'UTA',
 'Vancouver Canucks':'VAN','Vegas Golden Knights':'VGK','Washington Capitals':'WSH',
 'Winnipeg Jets':'WPG',
}

def norm(value):
    value = unicodedata.normalize('NFKD', str(value or '').casefold())
    return re.sub(r'[^a-z0-9]', '', ''.join(c for c in value if not unicodedata.combining(c)))

def split_ep_player(value):
    value = (value or '').strip()
    match = re.fullmatch(r'(.*?)\s*\(([^()]*)\)\s*', value)
    if match:
        return match.group(1).strip(), match.group(2).strip().upper()
    return value, ''

def pos_class(value):
    v = (value or '').upper().strip()
    parts = re.split(r'[/,;|\s]+', v)
    if any(x in ('G', 'GK', 'GOALIE', 'GOALTENDER') for x in parts):
        return 'G'
    if any(x in ('D', 'LD', 'RD', 'DEFENSE', 'DEFENCE', 'DEFENSEMAN') for x in parts):
        return 'D'
    if any(x in ('F', 'C', 'LW', 'RW', 'W', 'FORWARD', 'CENTER', 'CENTRE') for x in parts):
        return 'F'
    return ''

def read_csv(path, delimiter):
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError(f'No header: {path}')
        return list(reader.fieldnames), list(reader)

def write_csv(path, fields, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=';', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

def parse_codes(value):
    return {x.strip().upper() for x in re.split(r'[|,;/ ]+', value or '') if x.strip()}

def league_of_register(fields, path):
    if 'AHLPlayerID' in fields:
        return 'AHL', 'AHLPlayerID'
    if 'NHLPlayerID' in fields:
        return 'NHL', 'NHLPlayerID'
    raise ValueError(f'Not a register (missing AHLPlayerID/NHLPlayerID): {path}')

def league_of_ep(path):
    name = Path(path).name.upper()
    ahl = bool(re.search(r'(^|[^A-Z])AHL([^A-Z]|$)', name))
    nhl = bool(re.search(r'(^|[^A-Z])NHL([^A-Z]|$)', name))
    if ahl == nhl:
        raise ValueError(f'EP filename must identify AHL or NHL: {path}')
    return 'AHL' if ahl else 'NHL'

def expand_paths(values):
    result = []
    for value in values:
        matches = sorted(glob.glob(value))
        if not matches:
            raise FileNotFoundError(value)
        result.extend(matches)
    return list(dict.fromkeys(str(Path(p)) for p in result))

def register_position(row):
    known = {'8480012': 'F', '8483678': 'D'}  # Elias Pettersson: manually verified NHL identities
    return (pos_class(row.get('Position')) or pos_class(row.get('Role'))
            or known.get((row.get('NHLPlayerID') or '').strip(), ''))

def team_matches(league, ep_team, row):
    if not ep_team:
        return None
    if league == 'AHL':
        team = row.get('AHLTeam', '')
        return norm(team) == norm(ep_team) if team else None
    code = NHL_TEAMS.get(ep_team)
    if not code:
        return None
    teams = {t.strip().upper() for field in ('NHLTeamsThisSeason','CurrentNHLTeam','LastNHLTeam','CurrentTeam')
             for t in re.split(r'[|,;/ ]+', row.get(field, '') or '') if t.strip()}
    return code in teams if teams else None

def merge_values(old, new):
    return '|'.join(sorted({x for x in (old or '').split('|') + (new or '').split('|') if x}))

def output_path(path):
    p = Path(path)
    return p.with_name(p.stem + ('' if p.stem.endswith('_EP') else '_EP') + p.suffix)

def main(argv=None):
    p = argparse.ArgumentParser(description='Import nationality-filtered EP exports with safe identity matching')
    p.add_argument('-nat', '--nationality', required=True)
    p.add_argument('-if', '--importfiles', nargs='+', required=True)
    p.add_argument('-ep', '--epfiles', nargs='+', help='EP CSVs; default: *Stats Regular Season.csv')
    p.add_argument('--overrides', default='EP_player_overrides.csv')
    p.add_argument('--review', default='EP_import_review.csv')
    args = p.parse_args(argv)
    nat = args.nationality.strip().upper()
    if not re.fullmatch(r'[A-Z]{3}', nat):
        p.error('-nat must be a three-letter code, e.g. SWE')
    try:
        targets = expand_paths(args.importfiles)
        epfiles = expand_paths(args.epfiles) if args.epfiles else sorted(set(glob.glob('*Stats Regular Season.csv') + glob.glob('*Stats_Regular_Season.csv')))
        if not epfiles:
            raise ValueError('No EP exports found; specify -ep')
        if set(map(lambda x: str(Path(x).resolve()), targets)) & set(map(lambda x: str(Path(x).resolve()), epfiles)):
            raise ValueError('A file cannot be both register and EP export')
        tasks = []
        index = defaultdict(lambda: defaultdict(dict))
        for filename in targets:
            fields, rows = read_csv(filename, ';')
            league, id_col = league_of_register(fields, filename)
            tasks.append((filename, fields, rows, league, id_col))
            for row in rows:
                player_id = (row.get(id_col) or '').strip()
                if player_id and row.get('Name'):
                    key = norm(row['Name'])
                    previous = index[league][key].get(player_id)
                    if previous is not None:
                        # Preserve different source versions; prefer a row with richer data.
                        if sum(bool(v) for v in previous.values()) >= sum(bool(v) for v in row.values()):
                            continue
                    index[league][key][player_id] = row
        override_path = Path(args.overrides)
        override_fields = ['League','PlayerID','Name','EP_Nationalities','EP_Source','EP_ImportFiles',
                           'EP_Position','EP_Team','EP_MatchMethod','JerseyNumber']
        overrides = {}
        if override_path.exists():
            existing_fields, existing_rows = read_csv(override_path, ';')
            if not {'League','PlayerID','EP_Nationalities'} <= set(existing_fields):
                raise ValueError(f'Invalid overrides file: {override_path}')
            override_fields = list(dict.fromkeys(existing_fields + override_fields))
            for row in existing_rows:
                key = ((row.get('League') or '').upper(), (row.get('PlayerID') or '').strip())
                if key[0] and key[1]:
                    overrides[key] = row
        review, summary = [], Counter()
        for filename in epfiles:
            league = league_of_ep(filename)
            fields, rows = read_csv(filename, ',')
            if not {'Player','Team'} <= set(fields):
                raise ValueError(f'EP export missing Player/Team: {filename}')
            goalie_export = 'GOALIE' in Path(filename).name.upper() or 'GOLIE' in Path(filename).name.upper()
            for ep in rows:
                name, position = split_ep_player(ep.get('Player'))
                team = (ep.get('Team') or '').strip()
                if not name:
                    continue
                ep_pos = pos_class(position) or ('G' if goalie_export else '')
                candidates = index[league].get(norm(name), {})
                match_id, method = None, ''
                if len(candidates) == 1:
                    match_id = next(iter(candidates))
                    method = 'UNIQUE_NAME'
                    # Reject definite contradictions rather than silently assigning.
                    row = candidates[match_id]
                    rp = register_position(row)
                    tm = team_matches(league, team, row)
                    if (ep_pos and rp and ep_pos != rp) or tm is False:
                        match_id, method = None, 'IDENTITY_CONFLICT'
                elif len(candidates) > 1:
                    filtered = []
                    for pid, row in candidates.items():
                        rp = register_position(row)
                        tm = team_matches(league, team, row)
                        if ep_pos and rp == ep_pos and tm is True:
                            filtered.append(pid)
                    if len(filtered) == 1:
                        match_id = filtered[0]
                        method = 'NAME_TEAM_POSITION'
                if match_id is None:
                    reason = method or ('NO_REGISTER_MATCH' if not candidates else 'AMBIGUOUS_PLAYER_IDS')
                    review.append({'League':league,'EP_Player':name,'EP_Position':position or ('G' if goalie_export else ''),
                                   'EP_Team':team,'EP_File':Path(filename).name,'Status':reason,
                                   'CandidateIDs':'|'.join(sorted(candidates))})
                    summary[reason] += 1
                    continue
                key = (league, match_id)
                old = overrides.get(key, {})
                # Preserve any manually maintained jersey number.
                overrides[key] = {**old, 'League':league,'PlayerID':match_id,
                    'Name':old.get('Name') or name,
                    'EP_Nationalities':'|'.join(sorted(parse_codes(old.get('EP_Nationalities')) | {nat})),
                    'EP_Source':'EliteProspects',
                    'EP_ImportFiles':merge_values(old.get('EP_ImportFiles'),Path(filename).name),
                    'EP_Position':merge_values(old.get('EP_Position'),position or ('G' if goalie_export else '')),
                    'EP_Team':merge_values(old.get('EP_Team'),team),
                    'EP_MatchMethod':method if method == 'NAME_TEAM_POSITION' or not old.get('EP_MatchMethod') else old['EP_MatchMethod'],
                    'JerseyNumber':old.get('JerseyNumber','')}
                summary['MATCHED_EP_ROWS'] += 1
                if method == 'NAME_TEAM_POSITION':
                    summary['RESOLVED_BY_POSITION_AND_TEAM'] += 1
            print(f'INFO EP {league}: {len(rows)} rows from {filename}')
        for filename, fields, rows, league, id_col in tasks:
            for col in ('EP_Nationalities','EP_Source','EP_ImportFiles',f'EP_{nat}',
                        'EP_Position','EP_Team','EP_MatchMethod','JerseyNumber'):
                if col not in fields:
                    fields.append(col)
            filled = 0
            for row in rows:
                item = overrides.get((league,(row.get(id_col) or '').strip()))
                if not item:
                    continue
                filled += 1
                codes = parse_codes(row.get('EP_Nationalities')) | parse_codes(item.get('EP_Nationalities'))
                row['EP_Nationalities'] = '|'.join(sorted(codes))
                for field in ('EP_Source','EP_ImportFiles','EP_Position','EP_Team','EP_MatchMethod'):
                    if item.get(field):
                        row[field] = merge_values(row.get(field),item[field]) if field in ('EP_ImportFiles','EP_Position','EP_Team') else item[field]
                # Existing manually entered jersey number wins; otherwise take override.
                if not row.get('JerseyNumber') and item.get('JerseyNumber'):
                    row['JerseyNumber'] = item['JerseyNumber']
                if nat in codes:
                    row[f'EP_{nat}'] = 'Yes'
                official = (row.get('Nationality') or '').strip().upper()
                if official and nat in codes and official != nat:
                    review.append({'League':league,'EP_Player':row.get('Name',''),
                                   'EP_Position':item.get('EP_Position',''),'EP_Team':item.get('EP_Team',''),
                                   'EP_File':item.get('EP_ImportFiles',''),
                                   'Status':f'OFFICIAL_NATIONALITY_{official}_EP_{nat}',
                                   'CandidateIDs':row.get(id_col,'')})
            output = output_path(filename)
            write_csv(output,fields,rows)
            print(f'INFO {league}: {filled}/{len(rows)} rows with EP overrides; saved {output}')
        write_csv(override_path,override_fields,[overrides[key] for key in sorted(overrides)])
        write_csv(args.review,['League','EP_Player','EP_Position','EP_Team','EP_File','Status','CandidateIDs'],review)
        print(f'INFO Overrides: {len(overrides)} player identities; saved {override_path}')
        print(f'INFO Review: {len(review)} rows; saved {args.review}')
        print('INFO Summary:',dict(summary))
    except (OSError,ValueError,csv.Error) as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
