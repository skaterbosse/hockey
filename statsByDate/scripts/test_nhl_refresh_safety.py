"""Offline NHL endpoint failure regression tests, using copies of historical data."""
import csv,json,shutil,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import getGamePlayerStats as stats

DATE='2026-11-17'; GID='2026020333'
class NHLRefreshSafety(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name); source=Path(__file__).resolve().parent.parent/'data_test'
        for rel in [f'games/Games_{DATE}.csv',*[f'playerstats/{n}_{DATE}.csv' for n in ('PlayerStats','Goals','Shootout')]]:
            dest=self.root/rel; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(source/rel,dest)
        rel=Path('raw/games/NHL')/GID; self.raw=self.root/rel
        shutil.copytree(source/rel,self.raw)
        self.responses={p.stem:json.loads(p.read_text()) for p in self.raw.glob('*.json')}
    def snapshot(self):
        return {p.relative_to(self.root):p.read_bytes() for p in [*self.raw.glob('*.json'),*self.root.glob('playerstats/*.csv')]}
    def run_fetch(self,fail=None,invalid=None):
        def fetch(url,params=None):
            endpoint=url.rsplit('/',1)[-1]
            if endpoint==fail: raise OSError('Simulated NHL API failure')
            obj=json.loads(json.dumps(self.responses[endpoint]))
            if endpoint==invalid: obj['id']=0
            obj['_test_marker']=True
            return obj
        argv=['getGamePlayerStats.py','-d',DATE,'-l','NHL','--game-id',GID,'--refresh','--strict','--data-dir',str(self.root)]
        with patch.object(sys,'argv',argv),patch.object(stats,'fetch',side_effect=fetch),patch.object(stats,'load_nationalities',return_value=({}, {}, {})):
            return stats.main()
    def test_required_endpoint_failure_preserves_data(self):
        before=self.snapshot()
        for endpoint in ('boxscore','play-by-play'):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.run_fetch(fail=endpoint),1)
                self.assertEqual(before,self.snapshot())
    def test_wrong_identity_preserves_data(self):
        before=self.snapshot(); self.assertEqual(self.run_fetch(invalid='play-by-play'),1); self.assertEqual(before,self.snapshot())
    def test_optional_landing_failure_preserves_video(self):
        before=self.snapshot(); self.assertEqual(self.run_fetch(fail='landing'),0)
        self.assertEqual(before[self.raw.relative_to(self.root)/'landing.json'],(self.raw/'landing.json').read_bytes())
        rel=Path('playerstats')/f'Goals_{DATE}.csv'
        def clips(b):
            return {(r['Period'],r['Time'],r['ScorerID']):r['VideoURL'] for r in csv.DictReader(b.decode('utf-8-sig').splitlines(),delimiter=';') if r['GameID']==GID and r['VideoURL']}
        self.assertTrue(clips(before[rel])); self.assertEqual(clips(before[rel]),clips((self.root/rel).read_bytes()))
        self.assertTrue(json.loads((self.raw/'boxscore.json').read_text())['_test_marker'])
    def test_success_publishes_raw(self):
        self.assertEqual(self.run_fetch(),0)
        for p in self.raw.glob('*.json'): self.assertTrue(json.loads(p.read_text())['_test_marker'])
