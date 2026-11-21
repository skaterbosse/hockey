"""Offline checks of opt-in, read-only operational instrumentation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from generateRunReport import read_metrics

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'statsByDate/scripts'
TELEMETRY = ROOT / 'statsByDate/scripts'


class MetricsTests(unittest.TestCase):
    def test_timed_command_preserves_exit_code_and_records_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'metrics.jsonl'
            env = {**os.environ, 'STATS_METRICS_LOG': str(path)}
            p = subprocess.run([sys.executable, str(SCRIPTS / 'runMeasuredStep.py'),
                                '--stage', 'synthetic', '--', sys.executable, '-c', 'raise SystemExit(7)'],
                               env=env, capture_output=True)
            self.assertEqual(p.returncode, 7)
            metrics = read_metrics(path)
            self.assertEqual(metrics['stages'].keys(), {'synthetic'})
            self.assertGreaterEqual(metrics['stages']['synthetic'], 0)

    def test_http_instrumentation_counts_requests_and_urllib_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'metrics.jsonl'
            env = {**os.environ, 'STATS_METRICS_LOG': str(path), 'PYTHONPATH': str(TELEMETRY)}
            code = '''
import urllib.request
from unittest.mock import patch
from io import BytesIO
class R:
    status = 200
    def read(self): return b'ok'
with patch.object(urllib.request, '_opener'):
    pass
import httpTelemetry
httpTelemetry._urlopen = lambda *a, **k: R()
urllib.request.urlopen('https://api-web.nhle.com/v1/test')
try:
    httpTelemetry._urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError('test'))
    urllib.request.urlopen('https://lscluster.hockeytech.com/feed/index.php')
except OSError: pass
'''
            p = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            m = read_metrics(path)
            self.assertEqual(m['sources']['NHL']['successful'], 1)
            self.assertEqual(m['sources']['AHL']['failed'], 1)

    def test_missing_metrics_are_unknown(self):
        self.assertIsNone(read_metrics(Path('/nonexistent/f7-metrics-absent.jsonl')))

    def test_workflow_wires_metrics_without_changing_recovery_policy(self):
        s = (ROOT / '.github/workflows/StatsByDate.yml').read_text()
        self.assertIn('STATS_METRICS_LOG=', s)
        self.assertIn('runMeasuredStep.py', s)
        self.assertIn('--metrics-path "$STATS_METRICS_LOG"', s)
        self.assertIn('--managed-recovery', s)
        self.assertIn('recoverGameStats.py --production', s)
        self.assertIn('recoverNHLGoalVideos.py --production', s)


if __name__ == '__main__':
    unittest.main()
