#!/usr/bin/env python3
"""v4.3: Historical NHL bios -> AHL nationality. Corrects NHL API's 100-row page cap.
Keeps existing AHL/EP fields, and matches on normalized full name + exact birth date.
"""
import argparse, csv, json, re, time, unicodedata
from collections import defaultdict
from pathlib import Path
import requests

BASE = 'https://api.nhle.com/stats/rest/en'

def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        return list(reader.fieldnames or []), list(reader)

def save_csv(path, fields, rows):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=';', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

def norm(s):
    s = unicodedata.normalize('NFKD', str(s).casefold())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]', '', s)

def request_json(session, url, params, retries=6):
    for attempt in range(retries):
        try:
            response = session.get(url, params=params, timeout=40)
            if response.status_code in (429, 500, 502, 503, 504):
                try:
                    retry_after = float(response.headers.get('Retry-After', 0))
                except ValueError:
                    retry_after = 0
                time.sleep(min(90, max(retry_after, 2 ** attempt * 2)))
                continue
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(min(60, 2 ** attempt * 2))
    raise RuntimeError('Request retries exhausted')

def fetch_bios(session, year, kind, cache_dir, delay, refresh=False):
    cache = cache_dir / f'{year}_{kind}_bios.json'
    # v4 stored a truncated first page (usually 100 rows) as a plain JSON list.
    # Re-fetch all old caches with >=100 rows; a short old cache is kept.
    if cache.exists() and not refresh:
        try:
            old = json.loads(cache.read_text(encoding='utf-8'))
            if isinstance(old, dict) and old.get('cache_version') in (2, 3) and old.get('complete') is True:
                return old['data'], True, old.get('pages', 0)
            if isinstance(old, list) and len(old) < 100:
                # An old <100-row file is likely complete, but we cannot prove it.
                # Re-fetch to validate total and page boundaries.
                pass
        except (OSError, ValueError, KeyError, TypeError):
            pass

    season = f'{year}{year+1}'
    url = f'{BASE}/{kind}/bios'
    data = []
    seen_page_fingerprints = set()
    start = 0
    pages = 0
    page_size = 100  # NHL stats endpoint commonly caps at 100 regardless of larger limit
    expected_total = None
    while True:
        payload = request_json(session, url, {
            'cayenneExp': f'seasonId={season}', 'start': start, 'limit': page_size,
        })
        page = payload.get('data')
        if not isinstance(page, list):
            raise ValueError(f'Unexpected {kind} bios response for {season} at offset {start}')
        pages += 1
        total = payload.get('total')
        if isinstance(total, int) and total >= 0:
            expected_total = total
        if not page:
            if expected_total is not None and start < expected_total:
                raise ValueError(f'Premature empty page for {season} {kind}: offset {start}, total {expected_total}')
            break
        # One player may legitimately have multiple rows (e.g. team changes).
        # Detect repeated *pages*, not repeated player IDs.
        fingerprint = json.dumps(page, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        if fingerprint in seen_page_fingerprints:
            raise ValueError(f'Repeated identical page at offset {start} for {season} {kind}; refusing partial cache')
        seen_page_fingerprints.add(fingerprint)
        data.extend(page)
        start += len(page)
        if expected_total is not None:
            if start >= expected_total:
                break
        elif len(page) < page_size:
            break
        if pages >= 100:
            raise ValueError(f'Pagination safety limit reached for {season} {kind}')
        time.sleep(delay)

    if expected_total is not None and len(data) != expected_total:
        raise ValueError(f'Incomplete {season} {kind}: received {len(data)}, expected {expected_total}')
    # Atomic cache write only after the complete download succeeds.
    tmp = cache.with_suffix('.json.tmp')
    tmp.write_text(json.dumps({
        'cache_version': 3, 'complete': True, 'season': season,
        'kind': kind, 'pages': pages, 'total': expected_total, 'data': data,
    }, ensure_ascii=False), encoding='utf-8')
    tmp.replace(cache)
    return data, False, pages

def main():
    p = argparse.ArgumentParser(description='v4.3: NHL bios + EP nationality -> AHL')
    p.add_argument('--ahl', default='AHL_players_nationality_v4.csv')
    p.add_argument('--nhl', default='NHL_players.csv', help='Read-only; retained for CLI compatibility')
    p.add_argument('--out', default='AHL_players_nationality_v4_3.csv')
    p.add_argument('--start-year', type=int, default=2005)
    p.add_argument('--end-year', type=int, default=2026)
    p.add_argument('--delay', type=float, default=0.5)
    p.add_argument('--cache-dir', default='nationality_diagnostics/nhl_historical_bios')
    p.add_argument('--report', default='nationality_diagnostics/enrichment_v4_3_report.json')
    p.add_argument('--ep-overrides', default='EP_player_overrides.csv')
    p.add_argument('--ep-only', action='store_true', help='Apply EP to already enriched CSV without API calls')
    p.add_argument('--refresh-cache', action='store_true', help='Re-download all seasons')
    a = p.parse_args()
    if a.start_year > a.end_year or a.delay < 0:
        p.error('Invalid year range or delay')
    if Path(a.ahl).resolve() == Path(a.out).resolve():
        p.error('Output must differ from AHL input')
    fields, ahl = read_csv(a.ahl)
    if not Path(a.nhl).exists():
        p.error(f'NHL file not found: {a.nhl}')
    if 'BirthDate' not in fields:
        p.error('AHL input lacks BirthDate; run v3 first')
    have = sum(bool(r.get('BirthDate', '').strip()) for r in ahl)
    if have != len(ahl):
        p.error(f'Only {have}/{len(ahl)} AHL birthdates available')

    matched_new = verified = conflicts = ambiguous = unmatched = 0
    count = pages_total = 0
    history = {}
    errors = []
    by_key = {}
    examples = []
    if not a.ep_only:
        cache_dir = Path(a.cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        history = defaultdict(dict)
        errors = []
        count = 0
        pages_total = 0
        with requests.Session() as session:
            session.headers.update({'User-Agent': 'LocalSport-hockey-data/1.0 (public NHL statistics)'})
            for year in range(a.start_year, a.end_year + 1):
                for kind in ('skater', 'goalie'):
                    try:
                        rows, cached, pages = fetch_bios(session, year, kind, cache_dir, a.delay, a.refresh_cache)
                        for r in rows:
                            pid = str(r.get('playerId') or '').strip()
                            if pid:
                                history[pid].update({k: v for k, v in r.items() if v not in ('', None)})
                        count += len(rows)
                        pages_total += pages
                        print(f'INFO {year}-{year+1} {kind}: {len(rows)} records, {pages} pages' +
                              (' (cached)' if cached else ''), flush=True)
                    except Exception as exc:
                        errors.append({'season': year, 'kind': kind, 'error': str(exc)[:300]})
                        print(f'WARNING {year} {kind}: {exc}', flush=True)
                    time.sleep(a.delay)
        if not history:
            p.error('No NHL history loaded')

        by_key = defaultdict(list)
        for pid, r in history.items():
            name = r.get('skaterFullName') or r.get('goalieFullName') or r.get('playerName') or r.get('fullName') or ''
            dob = str(r.get('birthDate') or '')[:10]
            if name and re.fullmatch(r'\d{4}-\d{2}-\d{2}', dob):
                by_key[(norm(name), dob)].append((pid, r))
        for field in ('NationalitySource', 'NationalityStatus', 'MatchedNHLPlayerID', 'NHLHistoricalBirthDate'):
            if field not in fields:
                fields.append(field)

        for row in ahl:
            key = (norm(row.get('Name', '')), row.get('BirthDate', '').strip()[:10])
            candidates = by_key.get(key, [])
            options = {(pid, str(r.get('nationalityCode') or r.get('nationality') or '').strip().upper())
                       for pid, r in candidates}
            options = {(pid, nat) for pid, nat in options if nat}
            if len(options) == 1:
                pid, nat = next(iter(options))
                old = row.get('Nationality', '').strip().upper()
                if old and old != nat:
                    conflicts += 1
                    row['NationalityStatus'] = 'CONFLICT_REVIEW'
                    examples.append({'name': row.get('Name'), 'ahl': old, 'nhl_historical': nat, 'nhl_id': pid})
                    continue
                if old:
                    verified += 1
                else:
                    matched_new += 1
                    row['Nationality'] = nat
                row['NationalitySource'] = 'NHL_HISTORICAL_BIOS'
                row['NationalityStatus'] = 'MATCH_EXACT_NAME_BIRTHDATE'
                row['MatchedNHLPlayerID'] = pid
                row['NHLHistoricalBirthDate'] = key[1]
            elif len(options) > 1:
                ambiguous += 1
                row['NationalityStatus'] = 'HISTORICAL_AMBIGUOUS'
            else:
                unmatched += 1
                if not row.get('Nationality', '').strip():
                    row['NationalityStatus'] = 'NO_NHL_HISTORICAL_MATCH'

    # Merge EP overrides using league-specific AHL PlayerID; never guess by name.
    ep_new = ep_verified = ep_conflicts = ep_ambiguous = 0
    ep_examples = []
    ep_path = Path(a.ep_overrides)
    if not ep_path.is_file():
        p.error(f'EP overrides file not found: {ep_path}')
    ep_fields, ep_rows = read_csv(ep_path)
    needed = {'League', 'PlayerID', 'EP_Nationalities'}
    if not needed.issubset(ep_fields):
        p.error(f'EP overrides missing columns: {sorted(needed - set(ep_fields))}')
    ep_by_id = defaultdict(set)
    ep_files = defaultdict(set)
    for ep in ep_rows:
        if ep.get('League', '').strip().upper() != 'AHL':
            continue
        pid = ep.get('PlayerID', '').strip()
        nats = [v.strip().upper() for v in re.split(r'[,|/]', ep.get('EP_Nationalities', '')) if v.strip()]
        if pid and nats:
            ep_by_id[pid].update(nats)
            ep_files[pid].update(v for v in ep.get('EP_ImportFiles', '').split('|') if v)
    for field in ('NationalitySource', 'NationalityStatus', 'EP_Nationalities',
                  'EP_Source', 'EP_ImportFiles', 'JerseyNumber'):
        if field not in fields:
            fields.append(field)
    seen_ids = set()
    for row in ahl:
        pid = row.get('AHLPlayerID', '').strip()
        if pid not in ep_by_id:
            continue
        seen_ids.add(pid)
        nats = ep_by_id[pid]
        if len(nats) != 1:
            ep_ambiguous += 1
            ep_examples.append({'player_id': pid, 'name': row.get('Name'), 'ep': sorted(nats), 'reason': 'MULTIPLE_EP_NATIONALITIES'})
            continue
        nat = next(iter(nats))
        old = row.get('Nationality', '').strip().upper()
        if old and old != nat:
            ep_conflicts += 1
            ep_examples.append({'player_id': pid, 'name': row.get('Name'), 'existing': old, 'ep': nat, 'reason': 'NATIONALITY_CONFLICT'})
            continue
        if old:
            ep_verified += 1
        else:
            ep_new += 1
            row['Nationality'] = nat
            row['NationalitySource'] = 'ELITE_PROSPECTS'
            row['NationalityStatus'] = 'MATCH_EP_PLAYER_ID'
        row['EP_Nationalities'] = nat
        row['EP_Source'] = 'EliteProspects'
        existing_files = {v for v in row.get('EP_ImportFiles', '').split('|') if v}
        row['EP_ImportFiles'] = '|'.join(sorted(existing_files | ep_files[pid]))
    ep_missing = len(set(ep_by_id) - seen_ids)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    save_csv(a.out, fields, ahl)
    report = {
        'ahl_players': len(ahl), 'ahl_birthdates': have,
        'nhl_historical_seasons': f'{a.start_year}-{a.end_year}',
        'nhl_historical_rows': count, 'nhl_unique_ids': len(history),
        'nhl_pages': pages_total, 'historical_name_dob_keys': len(by_key),
        'new_nationalities': matched_new, 'existing_nationalities_verified': verified,
        'conflicts_review': conflicts, 'ambiguous': ambiguous,
        'no_historical_match': unmatched,
        'nationality_total': sum(bool(r.get('Nationality', '').strip()) for r in ahl),
        'api_errors': errors, 'conflict_examples': examples[:30],
        'complete_history': len(errors) == 0 if not a.ep_only else 'skipped_ep_only',
        'ep_new_nationalities': ep_new, 'ep_existing_verified': ep_verified,
        'ep_conflicts_review': ep_conflicts, 'ep_ambiguous': ep_ambiguous,
        'ep_ids_not_in_ahl': ep_missing, 'ep_conflict_examples': ep_examples[:50],
    }
    report_path = Path(a.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'INFO Historical NHL: {len(history)} unique player IDs; {count} season rows; {pages_total} pages; errors {len(errors)}')
    print(f'INFO AHL: {matched_new} new nationalities, {verified} verified existing, {conflicts} conflicts, {ambiguous} ambiguous')
    print(f'INFO AHL: nationality {report["nationality_total"]}/{len(ahl)}; saved {a.out}')
    print(f'INFO EP: {ep_new} new, {ep_verified} verified, {ep_conflicts} conflicts, {ep_ambiguous} ambiguous, {ep_missing} IDs absent')
    print(f'INFO Final AHL: {report["nationality_total"]}/{len(ahl)} with nationality')
    print(f'INFO Diagnostics: {a.report}')
    if errors:
        print('WARNING Some seasons failed; historical coverage is incomplete. See report.')

if __name__ == '__main__':
    main()
