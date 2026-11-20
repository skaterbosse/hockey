import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from game_recovery import decision, end_reference

class RecoveryTests(unittest.TestCase):
    def test_policy(self):
        ref=datetime(2026,11,20,tzinfo=timezone.utc)
        g={'Status':'FINAL'}; q={'gameStatus':'FINAL','qualityStatus':'INCOMPLETE','requiredActions':['FETCH_MATCH_DATA']}
        for minutes, expected in [(60,'RECOVER'),(1440,'RECOVER'),(2879,'RECOVER'),(2880,'EXPIRED'),(4320,'EXPIRED'),(-1,'UNKNOWN_TIME')]:
            with self.subTest(minutes=minutes): self.assertEqual(decision(g,q,ref+timedelta(minutes=minutes),ref,48),expected)
        now=ref+timedelta(hours=1)
        for status in ('LIVE','FUT'):
            self.assertEqual(decision(dict(g,Status=status),q,now,ref,48),'NOT_FINAL')
        self.assertEqual(decision(g,dict(q,qualityStatus='COMPLETE'),now,ref,48),'COMPLETE')
        for action in ('FETCH_GOAL_VIDEOS','FETCH_RECAP','FETCH_CONDENSED'):
            self.assertEqual(decision(g,dict(q,requiredActions=[action]),now,ref,48),'NO_STATS_ACTION')
        self.assertEqual(decision(g,q,now,None,48),'UNKNOWN_TIME')
        self.assertEqual(decision(g,q,now,ref,48,now-timedelta(minutes=29)),'COOLDOWN')
        self.assertEqual(decision(g,q,now,ref,48,now-timedelta(minutes=30)),'RECOVER')
    def test_fallback(self):
        g={'League':'NHL','GameID':'1','StartUTC':'2026-11-20T00:30:00Z'}
        for league in ('NHL','AHL'):
            ref,source=end_reference(dict(g,League=league),Path('/nonexistent'))
            self.assertEqual(ref.hour,0); self.assertEqual(ref.minute,30)
            self.assertEqual(source,'SCHEDULED_START_CONSERVATIVE')

if __name__=='__main__': unittest.main()
