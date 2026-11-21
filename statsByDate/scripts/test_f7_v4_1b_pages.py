#!/usr/bin/env python3
"""F7 v4.1b: static workflow checks and isolated Pages artifact smoke test."""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPDATE = ROOT / '.github/workflows/StatsByDate.yml'
DEPLOY = ROOT / '.github/workflows/DeployPagesOnly.yml'


class PagesPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.update = UPDATE.read_text(encoding='utf-8')
        cls.deploy = DEPLOY.read_text(encoding='utf-8')

    def test_exact_sha_passed_from_update_to_reusable_workflow(self):
        self.assertIn('published_sha: ${{ steps.published_commit.outputs.sha }}', self.update)
        self.assertIn('id: published_commit', self.update)
        self.assertIn('SHA="$(git rev-parse HEAD)"', self.update)
        self.assertIn('echo "sha=$SHA" >> "$GITHUB_OUTPUT"', self.update)
        self.assertIn('published_sha: ${{ needs.update.outputs.published_sha }}', self.update)
        self.assertLess(self.update.index('python statsByDate/scripts/publishStatsByDate.py --mode'),
                        self.update.index('id: published_commit'))

    def test_deploy_uses_exact_sha_and_checks_it(self):
        self.assertIn('published_sha:', self.deploy)
        self.assertIn("ref: ${{ inputs.published_sha || 'main' }}", self.deploy)
        self.assertIn("if: inputs.published_sha != ''", self.deploy)
        self.assertIn('ACTUAL_SHA="$(git rev-parse HEAD)"', self.deploy)
        self.assertIn('[[ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]]', self.deploy)
        self.assertLess(self.deploy.index('Verify exact publication commit'),
                        self.deploy.index('Upload Pages artifact'))

    def test_pages_artifact_includes_schedule_and_data(self):
        # Extract only the shell block of the Pages content step, run against a temp fixture.
        match = re.search(r'      - name: Include StatsByDate in Pages\n'
                          r'        shell: bash\n        run: \|\n'
                          r'(?P<code>(?:          .*\n|\n)+?)'
                          r'(?=      - name: Upload Pages artifact)', self.deploy)
        self.assertIsNotNone(match, 'Cannot locate Pages copy step')
        code = '\n'.join(line[10:] if line.startswith('          ') else line
                         for line in match.group('code').splitlines())
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            for name, content in {
                'StatsByDate.html': '<html>test</html>',
                'statsByDate/data/updateSchedule.json': '{"schemaVersion":1}',
                'statsByDate/data/games/Games_2026-11-21.csv': 'game',
                'statsByDate/data/playerstats/Goals_2026-11-21.csv': 'goal',
                'statsByDate/data/raw/games/NHL/1/boxscore.json': '{}',
                'statsByDate/data/recaps/NHL_Recaps.csv': 'recap',
                'statsByDate/data/quality/recovery_state.json': '{"internal":true}',
            }.items():
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            result = subprocess.run(['bash', '-e', '-c', code], cwd=repo,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ('updateSchedule.json', 'games/Games_2026-11-21.csv',
                         'playerstats/Goals_2026-11-21.csv',
                         'raw/games/NHL/1/boxscore.json', 'recaps/NHL_Recaps.csv'):
                self.assertTrue((repo / '_site/statsByDate/data' / name).is_file(), name)
            self.assertFalse((repo / '_site/statsByDate/data/quality/recovery_state.json').exists())


if __name__ == '__main__':
    unittest.main()
