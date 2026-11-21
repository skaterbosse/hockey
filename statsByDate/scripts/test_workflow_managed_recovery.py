"""Regression checks for F7 v3.3c workflow activation and publication."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/StatsByDate.yml'
PUBLISHER = ROOT / 'statsByDate/scripts/publishStatsByDate.py'

class WorkflowManagedRecoveryTests(unittest.TestCase):
    def test_order_and_arguments(self):
        s = WORKFLOW.read_text(encoding='utf-8')
        commands = [
            'updateHockeyDaily.py --mode regular --managed-recovery',
            'getNHLGameRecaps.py',
            'getNHLCondensedGames.py',
            'validateGameQuality.py --recent --production',
            'recoverGameStats.py --production',
            'recoverNHLGoalVideos.py --production',
            'validateGameQuality.py --recent --production',
            'generateUpdateSchedule.py --run-start',
            'publishStatsByDate.py --mode',
        ]
        positions = []
        offset = 0
        for command in commands:
            pos = s.find(command, offset)
            self.assertGreaterEqual(pos, 0, f'Missing or out-of-order workflow command: {command}')
            positions.append(pos)
            offset = pos + len(command)
        self.assertEqual(positions, sorted(positions))
        self.assertIn('updateHockeyDaily.py --mode daily', s)

    def test_every_recovery_step_has_mode_gate(self):
        s = WORKFLOW.read_text(encoding='utf-8')
        for name in ('Recover incomplete NHL and AHL statistics',
                     'Recover missing NHL goal videos',
                     'Revalidate quality after recovery'):
            block = s.split('      - name: ' + name + '\n', 1)[1].split('      - name:', 1)[0]
            self.assertIn("if: steps.schedule.outputs.mode != ''", block)
            self.assertNotIn('--test-mode', block)

    def test_publisher_stages_persistent_state(self):
        s = PUBLISHER.read_text(encoding='utf-8')
        self.assertIn("'recovery_state.json'", s)
        self.assertIn('to_add.add(recovery_state.as_posix())', s)
        self.assertIn("'push'", s)

    def test_workflow_keeps_concurrency_and_deployment(self):
        s = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('group: statsbydate-publish', s)
        self.assertIn('cancel-in-progress: false', s)
        self.assertIn('uses: ./.github/workflows/DeployPagesOnly.yml', s)
        self.assertIn('fetch-depth: 0', s)

if __name__ == '__main__':
    unittest.main()
