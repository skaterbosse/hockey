"""F7 v4.1: isolated Git staging checks; no network or production writes."""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import publishStatsByDate as publisher

TODAY = date(2026, 11, 21)
PROJECT = Path('statsByDate/data')

class PublicationWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'repo'
        self.repo.mkdir()
        self.data = self.repo / PROJECT
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test Runner')
        self.git('config', 'user.email', 'test@example.invalid')
        self.put('.gitignore', '')
        for offset in range(-7, 7):
            day = (TODAY + timedelta(days=offset)).isoformat()
            self.put(f'{PROJECT}/games/Games_{day}.csv', 'League;GameID\nNHL;2026020349\nAHL;1029329\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'baseline')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, text=True,
                              capture_output=True, check=True).stdout.strip()

    def put(self, path, content):
        path = self.repo / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def publish(self, mode):
        with patch.object(sys, 'argv', ['publishStatsByDate.py', '--repo-dir',
                                        str(self.repo), '--date', str(TODAY), '--mode', mode]):
            self.assertEqual(publisher.main(), 0)
        return set(self.git('diff', '--cached', '--name-only').splitlines())

    def test_regular_stages_recovered_data_2_and_3_days_back(self):
        expected = set()
        for offset in (-3, -2):
            day = (TODAY + timedelta(days=offset)).isoformat()
            for kind in ('PlayerStats', 'Goals', 'Shootout'):
                name = f'{PROJECT}/playerstats/{kind}_{day}.csv'
                self.put(name, f'recovered-{offset}-{kind}\n')
                expected.add(name)
            name = f'{PROJECT}/quality/Quality_{day}.json'
            self.put(name, '{"qualityStatus":"INCOMPLETE"}')
            expected.add(name)
        for league, gid in [('NHL', '2026020349'), ('AHL', '1029329')]:
            name = f'{PROJECT}/raw/games/{league}/{gid}/boxscore.json'
            self.put(name, '{"updated":true}')
            expected.add(name)
        name = f'{PROJECT}/quality/recovery_state.json'
        self.put(name, json.dumps({'NHL:2026020349': {'result': 'FETCH_OK'}}))
        expected.add(name)
        self.assertTrue(expected.issubset(self.publish('regular')))

    def test_daily_stages_recovered_data_2_and_3_days_back(self):
        expected = set()
        for offset in (-3, -2):
            day = (TODAY + timedelta(days=offset)).isoformat()
            for kind in ('PlayerStats', 'Goals', 'Shootout'):
                name = f'{PROJECT}/playerstats/{kind}_{day}.csv'
                self.put(name, f'changed-{offset}-{kind}\n')
                expected.add(name)
        self.assertTrue(expected.issubset(self.publish('daily')))

    def test_regular_preserves_unrelated_older_statistics(self):
        day = (TODAY - timedelta(days=4)).isoformat()
        old = f'{PROJECT}/playerstats/Goals_{day}.csv'
        self.put(old, 'original\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'older data')
        changed = f'{PROJECT}/playerstats/Goals_{(TODAY - timedelta(days=2)).isoformat()}.csv'
        self.put(changed, 'new\n')
        staged = self.publish('regular')
        self.assertIn(changed, staged)
        self.assertNotIn(old, staged)
        self.assertEqual((self.repo / old).read_text(), 'original\n')

if __name__ == '__main__':
    unittest.main()
