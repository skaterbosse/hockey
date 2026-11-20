"""Offline recovery integration tests using copied historical fixtures, never modifying data_test."""
import csv
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import recoverGameStats as recovery
import getGamePlayerStats as stats
import test_data_mode
from validateGameQuality import validate_date

HERE = Path(__file__).resolve().parent
DATE = '2026-11-17'
AHL = '1029329'
NHL = '2026020333'
NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)

class RecoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = HERE.parent / 'data_test'
        lookup_patch = patch.object(stats, "load_nationalities", return_value=({}, {}, {}))
        lookup_patch.start()
        self.addCleanup(lookup_patch.stop)
        for folder in ('games', 'playerstats', 'raw/games', 'recaps', 'quality'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        for rel in [f'games/Games_{DATE}.csv', *[f'playerstats/{n}_{DATE}.csv' for n in ('PlayerStats','Goals','Shootout')], 'recaps/NHL_Recaps.csv', 'recaps/NHL_CondensedGames.csv']:
            shutil.copyfile(self.source / rel, self.root / rel)
        for league, gid in [('AHL', AHL), ('NHL', NHL)]:
            rel = Path('raw/games') / league / gid
            shutil.copytree(self.source / rel, self.root / rel)
        self.raw = self.root / 'raw/games/AHL' / AHL / 'gameSummary.json'
        self.fresh = stats.unpack_jsonp(self.raw.read_text(encoding='utf-8-sig'))
        # Keep only two games in schedule so all other CSV rows act as preservation sentinels.
        self.filter_csv(self.root / f'games/Games_{DATE}.csv', lambda r: r['GameID'] in (AHL,NHL))
        # Rebuild AHL CSV from the historical final snapshot, independent of local CSV age.
        with patch.object(stats,'fetch',return_value=self.fresh), patch.object(test_data_mode,'test_root',return_value=self.root):
            self.assertEqual(self.child(self.command(AHL)).returncode,0)
        validate_date(self.root,DATE)
        self.assertEqual(self.quality(AHL)['qualityStatus'],'COMPLETE', 'Need a valid final AHL fixture')
        self.assertEqual(self.quality(NHL)['qualityStatus'],'COMPLETE', 'Need complete NHL fixture and videos')
    def filter_csv(self,path,keep):
        with path.open(encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f,delimiter=';'); fields=reader.fieldnames; rows=list(reader)
        stats.save_csv(path,fields,[r for r in rows if keep(r)])
    def command(self,gid):
        return [sys.executable,str(HERE/'getGamePlayerStats.py'),'-d',DATE,'-l','AHL','--game-id',gid,'--refresh','--strict','--test-mode']
    def child(self,cmd):
        self.assertEqual(cmd,self.command(AHL))
        with patch.object(sys,'argv',cmd[1:]):
            return SimpleNamespace(returncode=stats.main())
    def quality(self,gid):
        return next(q for q in json.loads((self.root/f'quality/Quality_{DATE}.json').read_text())['games'] if q['gameId']==gid)
    def state(self):
        return json.loads((self.root/'quality/recovery_state.json').read_text())
    def snapshot(self):
        return {p.relative_to(self.root):p.read_bytes() for p in [self.raw,*self.root.glob('playerstats/*.csv')]}
    def damage(self):
        raw=json.loads(json.dumps(self.fresh)); stats.ahl_root(raw)['details']['final']='0'
        self.raw.write_text(json.dumps(raw))
        validate_date(self.root,DATE)
        self.assertEqual(self.quality(AHL)['qualityStatus'],'INCOMPLETE')
    def run_recovery(self, response=None, error=None):
        with patch.object(recovery,'test_root',return_value=self.root), patch.object(test_data_mode,'test_root',return_value=self.root), patch.object(recovery,'datetime') as clock, patch.object(sys,'argv',['recoverGameStats.py','--test-mode']), patch.object(recovery.subprocess,'run',side_effect=self.child) as run, patch.object(stats,'fetch',return_value=response,side_effect=error) as fetch:
            clock.now.return_value=NOW
            rc=recovery.main()
            return rc,run.call_count,fetch.call_count
    def test_E_ahl_recovery(self):
        self.damage()
        before=self.snapshot()
        self.assertEqual(self.run_recovery(self.fresh),(0,1,1))
        self.assertEqual(self.quality(AHL)['qualityStatus'],'COMPLETE')
        self.assertEqual(self.state()['AHL:'+AHL]['result'],'FETCH_OK')
        for rel,content in before.items():
            if rel.suffix=='.csv':
                def others(b): return [r for r in csv.DictReader(b.decode('utf-8-sig').splitlines(),delimiter=';') if r['GameID']!=AHL]
                self.assertEqual(others(content),others((self.root/rel).read_bytes()))
        self.assertEqual(self.run_recovery(self.fresh),(0,0,0))
    def test_F_video_only(self):
        self.filter_csv(self.root/'recaps/NHL_Recaps.csv',lambda r:r['GameID']!=NHL)
        validate_date(self.root,DATE)
        self.assertEqual(self.quality(NHL)['requiredActions'],['FETCH_RECAP'])
        before=self.snapshot()
        self.assertEqual(self.run_recovery(error=AssertionError('Unexpected API call')),(0,0,0))
        self.assertEqual(before,self.snapshot())
        self.assertFalse((self.root/'quality/recovery_state.json').exists())
    def test_G_ahl_failure_preserves_data(self):
        self.damage(); before=self.snapshot()
        self.assertEqual(self.run_recovery(error=OSError('Simulated API failure')),(1,1,1))
        self.assertEqual(before,self.snapshot())
        self.assertEqual(self.state()['AHL:'+AHL]['result'],'FETCH_FAILED')
        self.assertEqual(self.quality(AHL)['qualityStatus'],'INCOMPLETE')
        self.assertEqual(self.run_recovery(self.fresh),(0,0,0))
        self.assertEqual(before,self.snapshot())

if __name__=='__main__': unittest.main()
