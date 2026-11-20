"""Offline tests of single-game selection and CSV merging."""
import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import getGamePlayerStats as m

class TargetedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.date='2026-11-17'
        self.games=[dict(League=l,Date=self.date,GameID=i,Status=s) for l,i,s in [('NHL','1','FINAL'),('NHL','2','FINAL'),('AHL','3','FINAL'),('AHL','4','FINAL'),('AHL','5','SCHEDULED')]]
        m.save_csv(self.root/'games'/f'Games_{self.date}.csv',list(self.games[0]),self.games)
        self.types=[('PlayerStats',m.PLAYER_FIELDS),('Goals',m.GOAL_FIELDS),('Shootout',m.SHOOTOUT_FIELDS)]
        for name,fields in self.types:
            m.save_csv(self.root/'playerstats'/f'{name}_{self.date}.csv',fields,[dict(g,Source='old') for g in self.games[:4]])
    def run_main(self,gid,league):
        with patch.object(sys,'argv',['script','-d',self.date,'-l',league,'--data-dir',str(self.root),'--game-id',gid,'--refresh','--strict']):
            return m.main()
    def snapshot(self):
        return {p.name:p.read_bytes() for p in (self.root/'playerstats').glob('*.csv')}
    def test_reject_unknown_wrong_league_and_future(self):
        before=self.snapshot()
        with patch.object(m,'fetch') as fetch:
            for gid,league in [('999','ALL'),('3','NHL'),('5','AHL')]:
                with self.assertRaises(SystemExit) as e: self.run_main(gid,league)
                self.assertEqual(e.exception.code,2)
            fetch.assert_not_called()
        self.assertEqual(before,self.snapshot())
    def test_duplicate_rejected(self):
        m.save_csv(self.root/'games'/f'Games_{self.date}.csv',list(self.games[0]),self.games+[self.games[0]])
        with self.assertRaises(SystemExit): self.run_main('1','NHL')
    def test_targeted_both_leagues(self):
        for league,gid in [('NHL','1'),('AHL','3')]:
            row=dict(League=league,Date=self.date,GameID=gid,PlayerID='99',Name='Test Player',Source='new')
            before=self.snapshot()
            with patch.object(m,'load_nationalities',return_value=({}, {}, {})), patch.object(m,'cached',return_value=({},'downloaded')) as cache, patch.object(m,'fetch',return_value={}) as fetch, patch.object(m,'nhl_players',return_value=[row]), patch.object(m,'nhl_goals',return_value=[]), patch.object(m,'nhl_shootout',return_value=[]), patch.object(m,'attach_nhl_goal_videos',return_value=0), patch.object(m,'ahl_players',return_value=[row]), patch.object(m,'ahl_goals',return_value=[]), patch.object(m,'ahl_shootout',return_value=[]), patch.object(m,'ahl_final_problem',return_value=None):
                self.assertEqual(self.run_main(gid,league),0)
                if league=='NHL':
                    self.assertEqual(cache.call_count,3); fetch.assert_not_called()
                    self.assertTrue(all(f'/{gid}/' in c.args[1] for c in cache.call_args_list))
                else:
                    cache.assert_not_called(); self.assertEqual(fetch.call_count,1); self.assertEqual(fetch.call_args.args[1]['game_id'],gid)
            for name,raw in before.items():
                old=list(csv.DictReader(raw.decode('utf-8-sig').splitlines(),delimiter=';'))
                with (self.root/'playerstats'/name).open(encoding='utf-8-sig') as f: new=list(csv.DictReader(f,delimiter=';'))
                self.assertEqual([r for r in old if r['GameID']!=gid],[r for r in new if r['GameID']!=gid])
                self.assertEqual(len([r for r in new if r['GameID']==gid]),1 if name.startswith('PlayerStats') else 0)

if __name__=='__main__': unittest.main()
