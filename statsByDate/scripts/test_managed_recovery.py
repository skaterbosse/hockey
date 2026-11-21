"""Offline managed-recovery checks; production mode uses a temporary root."""
import unittest, tempfile, json, sys, csv
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import recoverGameStats as recovery
import updateHockeyDaily as daily
import getGamePlayerStats as stats
import recoverNHLGoalVideos as videos
NOW=datetime(2026,11,20,12,tzinfo=timezone.utc)
DAY='2026-11-20'
class ManagedTests(unittest.TestCase):
    def test_production_state_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); scripts=base/'scripts'; scripts.mkdir(); root=base/'data'; (root/'games').mkdir(parents=True); (root/'quality').mkdir()
            (scripts/'scheduler_config.json').write_text(json.dumps(dict(maxStatsRecoveryHoursAfterFinal=48,statsRecoveryIntervalMinutes=30)))
            game=dict(League='NHL',GameID='1',Date=DAY,Status='FINAL',StartUTC='2026-11-20T00:00:00Z')
            stats.save_csv(root/'games'/f'Games_{DAY}.csv',list(game),[game])
            report=dict(date=DAY,schemaVersion=1,games=[dict(league='NHL',gameId='1',gameDate=DAY,gameStatus='FINAL',qualityStatus='INCOMPLETE',requiredActions=['FETCH_MATCH_DATA'])])
            state=root/'quality/recovery_state.json'; state.write_text(json.dumps({'NHL:9':dict(lastAttempt='2026-11-01T00:00:00Z',result='FETCH_OK')}))
            def validate(r,d): (r/'quality'/f'Quality_{d}.json').write_text(json.dumps(report))
            with patch.object(recovery,'HERE',scripts),patch.object(recovery,'validate_date',side_effect=validate),patch.object(recovery,'datetime') as clock,patch.object(sys,'argv',['recoverGameStats.py','--production']),patch.object(recovery.subprocess,'run',return_value=SimpleNamespace(returncode=1)) as child:
                clock.now.return_value=NOW
                self.assertEqual(recovery.main(),0); self.assertEqual(child.call_count,1)
                self.assertNotIn('--test-mode',child.call_args.args[0]); self.assertEqual(json.loads(state.read_text())['NHL:1']['result'],'FETCH_FAILED'); self.assertNotIn('NHL:9',json.loads(state.read_text()))
                self.assertEqual(recovery.main(),0); self.assertEqual(child.call_count,1)
    def test_managed_daily_commands(self):
        with patch.object(sys,'argv',['updateHockeyDaily.py','--mode','regular','-d',DAY,'--managed-recovery','--dry-run']),patch.object(daily,'run_step',return_value=0) as run:
            self.assertEqual(daily.main(),0)
            commands=[c.args[1] for c in run.call_args_list]; self.assertEqual(len(commands),4)
            self.assertTrue(all('--active-only' in c and '--strict' not in c for c in commands if c[1]=='getGamePlayerStats.py'))
    def test_active_only_final_no_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'games').mkdir(); row=dict(League='NHL',GameID='1',Date=DAY,Status='FINAL'); stats.save_csv(root/'games'/f'Games_{DAY}.csv',list(row),[row])
            with patch.object(sys,'argv',['getGamePlayerStats.py','-d',DAY,'--data-dir',tmp,'--active-only']),patch.object(stats,'fetch') as fetch:
                self.assertEqual(stats.main(),0); fetch.assert_not_called(); self.assertFalse((root/'playerstats').exists())
    def test_video_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'games').mkdir(); (root/'playerstats').mkdir(); g=dict(League='NHL',GameID='1',Date=DAY,Status='FINAL'); stats.save_csv(root/'games'/f'Games_{DAY}.csv',list(g),[g]); row=dict(League='NHL',GameID='1',Period='1',Time='02:00',ScorerID='5',Strength='',EmptyNet='',VideoURL='',HighlightClipID=''); path=root/'playerstats'/f'Goals_{DAY}.csv'; stats.save_csv(path,list(row),[row]); before=path.read_bytes()
            landing=dict(id=1,summary=dict(scoring=[dict(periodDescriptor=dict(number=1),goals=[dict(timeInPeriod='02:00',playerId=5,highlightClipSharingUrl='https://www.nhl.com/video/test',highlightClip=7)])]))
            with patch.object(videos,'fetch',return_value=landing) as fetch:
                self.assertEqual(videos.recover_day(root,DAY,True),0); self.assertEqual(before,path.read_bytes()); fetch.assert_not_called()
                self.assertEqual(videos.recover_day(root,DAY),1); self.assertTrue(fetch.call_args.args[0].endswith('/landing'))
                with path.open(encoding='utf-8-sig') as f: result=next(csv.DictReader(f,delimiter=';'))
                self.assertEqual(result,{**row,'VideoURL':'https://www.nhl.com/video/test','HighlightClipID':'7'})
                self.assertEqual(videos.recover_day(root,DAY),0); self.assertEqual(fetch.call_count,1)
if __name__=='__main__': unittest.main()
