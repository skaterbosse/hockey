import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from generateRunReport import report, markdown


class RunReportTests(unittest.TestCase):
    def test_report_counts_final_only_and_keeps_unknown_metrics_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quality = root / 'statsByDate/data/quality'
            quality.mkdir(parents=True)
            (quality / 'Quality_2026-11-21.json').write_text(json.dumps({'games': [
                {'gameStatus': 'FINAL', 'league': 'NHL', 'qualityStatus': 'INCOMPLETE', 'reasons': ['GOALIE_STATS_INCOMPLETE']},
                {'gameStatus': 'FINAL', 'league': 'AHL', 'qualityStatus': 'COMPLETE', 'reasons': []},
                {'gameStatus': 'LIVE', 'league': 'NHL', 'qualityStatus': 'INCOMPLETE', 'reasons': ['NOT_FINAL']},
            ]}))
            (quality / 'recovery_state.json').write_text(json.dumps({
                'NHL:1': {'lastAttempt': '2026-11-21T10:10:00+00:00', 'result': 'FETCH_FAILED'},
                'NHL:2': {'lastAttempt': '2026-11-20T10:10:00+00:00', 'result': 'FETCH_OK'}}))
            start = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
            end = datetime(2026, 11, 21, 10, 30, tzinfo=timezone.utc)
            r = report(root, start, end)
            self.assertEqual(r['quality']['byStatus'], {'COMPLETE': 1, 'INCOMPLETE': 1})
            self.assertEqual(r['recovery']['attemptsRecordedInState'], 1)
            self.assertEqual(r['recovery']['failedFetchesRecordedInState'], 1)
            self.assertIsNone(r['efficiency']['apiRequests'])
            self.assertIn('ej mätt', markdown(r))

    def test_workflow_has_report_and_artifact(self):
        wf = (Path(__file__).resolve().parents[2] / '.github/workflows/StatsByDate.yml').read_text()
        self.assertIn('generateRunReport.py', wf)
        self.assertIn('GITHUB_STEP_SUMMARY', wf)
        self.assertIn('actions/upload-artifact@v4', wf)
        self.assertIn('STATS_BASE_SHA', wf)


if __name__ == '__main__':
    unittest.main()
