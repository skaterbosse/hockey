import unittest,json
from datetime import timedelta
from generateUpdateSchedule import build,parse,BASE
C=json.loads((BASE/'scheduler_config.json').read_text())
START=parse('2026-11-16T00:00:00Z')
def row(status='LIVE',start=START,key='1'):
    return dict(League='NHL',GameID=key,Status=status,StartUTC=start.isoformat())
class SchedulerTest(unittest.TestCase):
    def calc(self,rows,minutes,prev=None):
        now=START+timedelta(minutes=minutes)
        return build(rows,prev or {},now,now,C)
    def test_unfinished(self):
        for status in ('LIVE','SCHEDULED','UNKNOWN'):
            for minutes in (0,200,210,240):
                self.assertEqual(self.calc([row(status)],minutes)['intervalMinutes'],10)
    def test_future(self):
        self.assertEqual(self.calc([row('SCHEDULED')],-20)['nextDueUTC'],'2026-11-16T00:00:00Z')
    def test_terminal(self):
        for status in ('CANCELLED','POSTPONED'):
            self.assertIsNone(self.calc([row(status)],10)['nextDueUTC'])
    def test_tail(self):
        prev=self.calc([row('FINAL')],180)['games']
        for age,interval in ((0,15),(59,15),(60,30),(179,30),(180,120),(399,120),(400,None)):
            self.assertEqual(self.calc([row('FINAL')],180+age,prev)['intervalMinutes'],interval)
    def test_overlap(self):
        self.assertEqual(self.calc([row('FINAL'),row('LIVE',key='2')],180)['intervalMinutes'],10)
if __name__=='__main__': unittest.main()
