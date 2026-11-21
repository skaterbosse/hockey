#!/usr/bin/env python3
"""Read-only StatsByDate run report. Unknown metrics are explicitly null."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess


def utc(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def report(root, started, finished, base_sha=None, published_sha=None):
    data = root / 'statsByDate/data'
    counts = Counter()
    reasons = Counter()
    by_league = {}
    latest_dates = []
    for p in (data / 'quality').glob('Quality_????-??-??.json'):
        try:
            day = datetime.strptime(p.stem[8:], '%Y-%m-%d').date()
        except ValueError:
            continue
        latest_dates.append((day, p))
    for _, p in sorted(latest_dates, reverse=True)[:4]:
        q = json.loads(p.read_text(encoding='utf-8'))
        for g in q.get('games', []):
            if g.get('gameStatus', '').upper() not in ('FINAL', 'OFF'):
                continue
            league = g.get('league', 'UNKNOWN')
            status = g.get('qualityStatus', 'UNKNOWN')
            counts[status] += 1
            by_league.setdefault(league, Counter())[status] += 1
            reasons.update(g.get('reasons') or [])
    state_path = data / 'quality/recovery_state.json'
    attempts = 0
    failures = 0
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        for entry in state.values():
            try:
                at = utc(entry['lastAttempt'])
            except (KeyError, ValueError, TypeError):
                continue
            if started <= at <= finished:
                attempts += 1
                failures += entry.get('result') == 'FETCH_FAILED'
    changed = None
    if base_sha and published_sha:
        proc = subprocess.run(['git', 'diff', '--name-only', base_sha, published_sha, '--', 'statsByDate/data'],
                              cwd=root, text=True, capture_output=True)
        if proc.returncode == 0:
            changed = len([line for line in proc.stdout.splitlines() if line.strip()])
    return {
        'schemaVersion': 1, 'startedAt': started.isoformat(), 'finishedAt': finished.isoformat(),
        'durationSeconds': round((finished - started).total_seconds(), 2),
        'baseSha': base_sha, 'publishedSha': published_sha,
        'quality': {'scope': 'final games in four most recent available quality reports',
                    'byStatus': dict(sorted(counts.items())),
                    'byLeague': {k: dict(sorted(v.items())) for k, v in sorted(by_league.items())},
                    'reasons': dict(sorted(reasons.items()))},
        'recovery': {'attemptsRecordedInState': attempts, 'failedFetchesRecordedInState': failures},
        'publication': {'changedDataFiles': changed},
        'efficiency': {'apiRequests': None, 'requestsWithoutDataChange': None,
                       'stageDurationsSeconds': None,
                       'note': 'API request counts and per-stage timings are not instrumented yet.'},
    }


def markdown(r):
    q = r['quality']
    lines = ['## StatsByDate – driftrapport',
             f"- Total körtid: **{r['durationSeconds']} s**",
             f"- Publicerad commit: `{r['publishedSha'] or 'ej tillgänglig'}`",
             f"- Ändrade datafiler: **{r['publication']['changedDataFiles'] if r['publication']['changedDataFiles'] is not None else 'ej mätt'}**",
             f"- Återhämtningsförsök registrerade under körningen: **{r['recovery']['attemptsRecordedInState']}**",
             f"- Misslyckade återhämtningshämtningar registrerade: **{r['recovery']['failedFetchesRecordedInState']}**",
             '', '### Kvalitet (avslutade matcher, fyra senaste rapportdatum)',
             '| Status | Antal |', '|---|---:|']
    lines.extend(f'| {k} | {v} |' for k, v in sorted(q['byStatus'].items()))
    if not q['byStatus']:
        lines.append('| Inga tillgängliga | 0 |')
    lines += ['', '### Avvikelseorsaker', '| Orsak | Antal |', '|---|---:|']
    lines.extend(f'| {k} | {v} |' for k, v in sorted(q['reasons'].items()))
    if not q['reasons']:
        lines.append('| Inga | 0 |')
    lines += ['', '### Effektiviseringsindikatorer',
              '- API-anrop: **ej mätt**', '- Anrop utan dataförändring: **ej mätt**',
              '- Körtid per arbetssteg: **ej mätt**',
              '', '_Rapporten är observationsbaserad. Kvalitetsstatus och källdata ändras inte._']
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo-dir', type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument('--started-at', required=True)
    ap.add_argument('--finished-at')
    ap.add_argument('--base-sha')
    ap.add_argument('--published-sha')
    ap.add_argument('--output', type=Path)
    ap.add_argument('--summary-path', type=Path)
    a = ap.parse_args()
    start = utc(a.started_at)
    finish = utc(a.finished_at) if a.finished_at else datetime.now(timezone.utc)
    if finish < start:
        ap.error('finished-at must be >= started-at')
    r = report(a.repo_dir.resolve(), start, finish, a.base_sha, a.published_sha)
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(r, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    summary = markdown(r)
    if a.summary_path:
        with a.summary_path.open('a', encoding='utf-8') as f:
            f.write(summary)
    print(summary)


if __name__ == '__main__':
    main()
