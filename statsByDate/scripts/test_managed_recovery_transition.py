"""F7 v3.3b supplementary integration tests (no production writes/network)."""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import getGamePlayerStats as stats
import recoverGameStats as recovery
import publishStatsByDate as publisher

DAY = '2026-11-20'
NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)


class TransitionAndPersistenceTests(unittest.TestCase):
    def test_in_progress_to_final_fetches_final_snapshot_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            scripts = base / 'scripts'
            scripts.mkdir()
            (scripts / 'scheduler_config.json').write_text(json.dumps({
                'maxStatsRecoveryHoursAfterFinal': 48,
                'statsRecoveryIntervalMinutes': 30,
            }))
            root = base / 'data'
            for name in ('games', 'quality', 'playerstats'):
                (root / name).mkdir(parents=True)
            schedule = root / 'games' / f'Games_{DAY}.csv'
            game = dict(League='NHL', GameID='1', Date=DAY,
                        Status='IN_PROGRESS', StartUTC='2026-11-20T00:00:00Z')
            stats.save_csv(schedule, list(game), [game])
            snapshot = root / 'playerstats' / f'PlayerStats_{DAY}.csv'
            snapshot.write_text('phase\nLIVE\n')
            calls = []

            def validate(r, d):
                # The FINAL schedule with LIVE-only data must require fetching final stats.
                quality = ('COMPLETE' if snapshot.read_text() == 'phase\nFINAL\n'
                           else 'INCOMPLETE')
                report = dict(date=d, schemaVersion=1, games=[dict(
                    league='NHL', gameId='1', gameDate=d,
                    gameStatus=game['Status'], qualityStatus=quality,
                    requiredActions=[] if quality == 'COMPLETE' else ['FETCH_MATCH_DATA'])])
                (r / 'quality' / f'Quality_{d}.json').write_text(json.dumps(report))

            def fetch(cmd):
                calls.append(cmd)
                self.assertEqual(cmd[cmd.index('--game-id') + 1], '1')
                self.assertIn('--refresh', cmd)
                snapshot.write_text('phase\nFINAL\n')
                return SimpleNamespace(returncode=0)

            # First verify the FINAL transition does not cause active-only to fetch.
            game['Status'] = 'FINAL'
            stats.save_csv(schedule, list(game), [game])
            with patch.object(sys, 'argv', ['getGamePlayerStats.py', '-d', DAY,
                                            '--data-dir', str(root), '--active-only']), \
                 patch.object(stats, 'fetch') as network:
                self.assertEqual(stats.main(), 0)
                network.assert_not_called()
            self.assertEqual(snapshot.read_text(), 'phase\nLIVE\n')

            with patch.object(recovery, 'HERE', scripts), \
                 patch.object(recovery, 'validate_date', side_effect=validate), \
                 patch.object(recovery, 'datetime') as clock, \
                 patch.object(recovery.subprocess, 'run', side_effect=fetch), \
                 patch.object(sys, 'argv', ['recoverGameStats.py', '--production']):
                clock.now.return_value = NOW
                self.assertEqual(recovery.main(), 0)
                self.assertEqual(len(calls), 1)
                self.assertEqual(snapshot.read_text(), 'phase\nFINAL\n')
                self.assertEqual(recovery.main(), 0)
                self.assertEqual(len(calls), 1)
            state = json.loads((root / 'quality' / 'recovery_state.json').read_text())
            self.assertEqual(state['NHL:1']['result'], 'FETCH_OK')

    def test_published_recovery_state_survives_fresh_git_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / 'source'
            repo.mkdir()

            def git(*args, cwd=repo):
                return subprocess.run(['git', *args], cwd=cwd, text=True,
                                      capture_output=True, check=True)

            git('init', '-q')
            git('config', 'user.name', 'Test Runner')
            git('config', 'user.email', 'test@example.invalid')
            data = repo / 'statsByDate' / 'data'
            for folder in ('games', 'quality'):
                (data / folder).mkdir(parents=True)
            for day in ('2026-11-19', DAY):
                (data / 'games' / f'Games_{day}.csv').write_text('League;GameID\nNHL;1\n')
            (repo / '.gitignore').write_text('')
            git('add', '.')
            git('commit', '-qm', 'baseline')

            state = data / 'quality' / 'recovery_state.json'
            expected = {'NHL:1': {'lastAttempt': '2026-11-20T12:00:00+00:00',
                                  'result': 'FETCH_FAILED'}}
            state.write_text(json.dumps(expected))
            with patch.object(sys, 'argv', ['publishStatsByDate.py', '--repo-dir',
                                            str(repo), '--mode', 'regular',
                                            '--date', DAY]):
                self.assertEqual(publisher.main(), 0)
            staged = git('diff', '--cached', '--name-only').stdout.splitlines()
            self.assertIn('statsByDate/data/quality/recovery_state.json', staged)
            git('commit', '-qm', 'publish recovery state')
            checkout = base / 'fresh'
            git('clone', '-q', str(repo), str(checkout))
            restored = checkout / 'statsByDate' / 'data' / 'quality' / 'recovery_state.json'
            self.assertEqual(json.loads(restored.read_text()), expected)


if __name__ == '__main__':
    unittest.main()
