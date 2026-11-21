"""Run from project root: PYTHONPATH=statsByDate/scripts python3 -m unittest test_f8_1b_scheduler -v"""
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import generateUpdateSchedule as scheduler

UTC = timezone.utc

class SchedulerRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'quality').mkdir()
        self.now = datetime(2026, 11, 21, 18, 0, tzinfo=UTC)
        self.row = {'League':'NHL','GameID':'123','Date':'2026-11-21',
                    'StartUTC':'2026-11-21T15:00:00Z','Status':'FINAL'}
        self.cfg = {'maxStatsRecoveryHoursAfterFinal':48, 'statsRecoveryIntervalMinutes':30}
        self.quality = {'schemaVersion':1,'date':'2026-11-21','games':[{
            'league':'NHL','gameId':'123','gameDate':'2026-11-21',
            'gameStatus':'FINAL','qualityStatus':'INCOMPLETE',
            'requiredActions':['FETCH_MATCH_DATA']}]}
        self.write_quality()
    def write_quality(self):
        (self.root/'quality'/'Quality_2026-11-21.json').write_text(json.dumps(self.quality))
    def windows(self):
        return scheduler.recovery_windows([self.row],self.root,self.now,self.now,self.cfg)
    def test_incomplete_produces_recovery_window(self):
        result=self.windows()
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['kind'],'stats_recovery')
        self.assertEqual(result[0]['dueUTC'],'2026-11-21T18:30:00Z')
    def test_complete_does_not_schedule(self):
        self.quality['games'][0]['qualityStatus']='COMPLETE'; self.write_quality()
        self.assertEqual(self.windows(),[])
    def test_cooldown_is_respected(self):
        (self.root/'quality'/'recovery_state.json').write_text(json.dumps({
            'NHL:123':{'lastAttempt':'2026-11-21T17:55:00Z'}}))
        self.assertEqual(self.windows()[0]['dueUTC'],'2026-11-21T18:30:00Z')
    def test_missing_quality_fails_closed(self):
        (self.root/'quality'/'Quality_2026-11-21.json').unlink()
        with self.assertRaises(FileNotFoundError): self.windows()
    def test_expired_game_not_scheduled(self):
        self.row['StartUTC']='2026-11-18T15:00:00Z'
        self.assertEqual(self.windows(),[])
    def test_off_status_supported(self):
        self.row['Status']='OFF'; self.quality['games'][0]['gameStatus']='OFF'; self.write_quality()
        self.assertEqual(len(self.windows()),1)

if __name__=='__main__': unittest.main()
