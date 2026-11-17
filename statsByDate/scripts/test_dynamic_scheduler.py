import unittest,json
from datetime import timedelta
from generateUpdateSchedule import build,parse,BASE,highlights_complete
C=json.loads((BASE/'scheduler_config.json').read_text())
START=parse('2026-11-16T00:00:00Z')
def row(status='LIVE',start=START,key='1',league='NHL',**kw):
    return dict(League=league,GameID=key,Status=status,StartUTC=start.isoformat(),HomeScore='1',AwayScore='0',**kw)
class SchedulerTest(unittest.TestCase):
    def calc(self,rows,minutes,prev=None,goals=None,last=None):
        now=START+timedelta(minutes=minutes)
        return build(rows,prev or {},now,now if last is None else START+timedelta(minutes=last),C,goals)
    def test_unfinished(self):
        for status in ('LIVE','SCHEDULED','UNKNOWN'):
            for minutes in (0,190,200,209,210,240):
                self.assertEqual(self.calc([row(status)],minutes)['intervalMinutes'],10 if minutes<200 else None)
                self.assertEqual(self.calc([row(status)],minutes,last=minutes-10)['intervalMinutes'],10 if minutes<210 and minutes%5==0 else None)
    def test_future(self):
        self.assertEqual(self.calc([row('SCHEDULED')],-20)['nextDueUTC'],'2026-11-16T00:00:00Z')
    def test_terminal(self):
        for status in ('CANCELLED','POSTPONED'):
            self.assertIsNone(self.calc([row(status)],10)['nextDueUTC'])
    def test_tail(self):
        prev=self.calc([row('FINAL')],180)['games']
        for age in (0,30,60,90,100,120,129,130):
            result=self.calc([row('FINAL')],180+age,prev)
            self.assertEqual(result['intervalMinutes'],30 if age<100 else None)
            self.assertEqual(result['games']['NHL:1']['finalObservedUTC'],prev['NHL:1']['finalObservedUTC'])
    def test_overlap(self):
        result=self.calc([row('FINAL'),row('LIVE',key='2')],180)
        self.assertEqual(result['intervalMinutes'],10)
        self.assertEqual(len(result['windows']),2)
    def test_complete(self):
        for goals,complete in ((None,False),([],False),([{'VideoURL':''}],False),([{'VideoURL':'https://example.org/a'}],True)):
            self.assertEqual(highlights_complete(row('FINAL'),goals),complete)
            self.assertEqual(self.calc([row('FINAL')],180,goals={'NHL:1':goals})['intervalMinutes'],None if complete else 30)
    def test_score_and_shootout(self):
        r=row('FINAL',Decision='GWS'); r.update(HomeScore='2',AwayScore='1')
        videos=[{'VideoURL':'https://example.org/a'}]*2
        self.assertTrue(highlights_complete(r,videos))
        self.assertFalse(highlights_complete(r,videos[:1]))
        r.update(HomeScore='0',AwayScore='0',Decision='REG')
        self.assertTrue(highlights_complete(r,[]))
        self.assertFalse(highlights_complete(r,None))
    def test_ahl(self):
        self.assertIsNone(self.calc([row('FINAL',league='AHL')],180)['nextDueUTC'])
        self.assertEqual(self.calc([row('LIVE',league='AHL')],180)['intervalMinutes'],10)
if __name__=='__main__': unittest.main()
