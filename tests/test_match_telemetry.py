import _test_paths
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock,patch

from headless_host import HostController
from match_journal import Journal
from match_metadata import participants
from modules.live_game_data import observe_controller
from match_ratings import read_inputs
from match_review import load_matches,write_review
from modules.live_game_data import MatchTelemetry,record_controller


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.directory=Path(tmp.name);self.path=self.directory/'test.sqlite3'
        self.journal=Journal(self.path)
        key,session=self.journal.register({'test':True},{'lobby':'test'})
        fixture=json.loads((_test_paths.ROOT/'tests/fixtures/ai_match.json').read_text())
        self.roster=fixture['loaded_roster']
        self.match=dict(match_id='test',native_game_start_time=self.roster['gameStartTimeRaw'],
                        starting_roster=self.roster,created_at=1,map=self.roster['map'],
                        participants=participants(self.roster,'test'))
        self.journal.new_match(session,self.match,'test')
        self.live=dict(state={'pageVtable':0xe2ae58},managerStateRaw=1,
                       hud=[dict(rawText='92 / 160',team=None,scope='observed_HUD_cell_unmapped')])
        self.monitor=MatchTelemetry(self.path)

    def snapshots(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT recorded_at,sampled_at,reason,snapshot_json FROM match_snapshots ORDER BY sequence').fetchall()

    def test_initial_thirty_second_and_restart_snapshots_never_feed_ratings(self):
        for stamp,expected in [(100,True),(101,False),(129.9,False),(130,True),(160,True)]:
            self.assertEqual(self.monitor.observe(self.match,self.roster,self.live,stamp),expected)
        restarted=MatchTelemetry(self.path)
        self.assertTrue(restarted.observe(self.match,self.roster,self.live,161))
        self.assertEqual([x[0] for x in self.snapshots()],[100,130,160,161])
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(read_inputs(db),[])

    def test_scope_and_unreadable_samples_cannot_replace_valid_progress(self):
        self.monitor.observe(self.match,self.roster,self.live,100)
        bad_roster=dict(self.roster,gameStartTimeRaw='other')
        self.assertFalse(self.monitor.observe(self.match,bad_roster,self.live,150))
        self.assertFalse(self.monitor.observe(self.match,dict(self.roster,steamLobbyId='other'),self.live,151))
        self.assertFalse(self.monitor.observe(self.match,self.roster,dict(self.live,managerStateRaw=None),152))
        self.assertFalse(self.monitor.observe(self.match,self.roster,dict(self.live,state={'pageVtable':0}),153))
        self.monitor.event(self.match,'observation_failed',{'error':'unreadable'},154)
        self.assertEqual(self.snapshots()[-1][1],100)

    def test_events_flush_latest_sample_with_its_original_timestamp_and_deduplicate(self):
        self.monitor.observe(self.match,self.roster,self.live,100)
        self.live['hud'][0]['rawText']='93 / 160'
        self.monitor.observe(self.match,self.roster,self.live,110)
        self.monitor.event(self.match,'left_match_session',{'cause':'unknown'},115)
        self.monitor.event(self.match,'left_match_session',{'cause':'unknown'},116)
        snapshots=self.snapshots()
        self.assertEqual(len(snapshots),2)
        self.assertEqual(snapshots[-1][:3],(115,110,'left_match_session'))
        self.assertEqual(json.loads(snapshots[0][3])['sample']['live']['hud'][0]['rawText'],'92 / 160')
        self.assertEqual(json.loads(snapshots[1][3])['sample']['live']['hud'][0]['rawText'],'93 / 160')

    def test_terminal_manager_is_only_an_observation_not_a_winner(self):
        self.monitor.observe(self.match,self.roster,dict(self.live,managerStateRaw=3),100)
        review=load_matches(self.path)
        self.assertIsNone(review[0]['winner'])
        self.assertEqual(review[0]['capture_stage'],'progress_snapshot')
        self.assertEqual(review[0]['progress_snapshots'][0]['sampled_at'],100)
        self.assertTrue(all(r['fields']['score'] is None for r in review[0]['rows']))

    def test_review_read_only_and_final_capture_supersedes_progress_without_duplication(self):
        self.monitor.observe(self.match,self.roster,self.live,100)
        self.monitor.event(self.match,'game_process_exited',{'detachment':{'reason':'process-terminated'}},115)
        before=self.path.read_bytes()
        review=load_matches(self.path)
        write_review(review,self.directory/'review.html',self.path)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(review[0]['observation_events'][0]['kind'],'game_process_exited')
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('INSERT INTO completion_captures VALUES (?,?,?,?,?)',
                ('test',json.dumps({'engine_outcome':{'winning_team':'b'},'rows':[]}), '{}','{}',120))
        review=load_matches(self.path)
        self.assertEqual(len(review),1)
        # A final capture without team VP cannot establish a Battle Zones winner.
        self.assertIsNone(review[0]['winner'])
        self.assertEqual(review[0]['capture_stage'],'finish_capture')
        self.assertEqual(len(review[0]['progress_snapshots']),2)

    def test_shared_controller_records_browser_exit_process_exit_and_stop(self):
        c=HostController(123,self.directory)
        c.journal=self.journal;c.active_match=self.match;c.match_telemetry=self.monitor
        c.script=Mock();c.script.exports_sync.state.return_value={'pageVtable':0xe2a3d0}
        observe_controller(c,self.roster,self.live)
        c.state();c.state()
        c.on_detached('process-terminated',None)
        c.close()
        with closing(sqlite3.connect(self.path)) as db:
            kinds=[r[0] for r in db.execute('SELECT kind FROM match_observation_events')]
        self.assertEqual(kinds.count('left_match_session'),1)
        self.assertIn('game_process_exited',kinds)
        self.assertIn('observer_stopped',kinds)

    def test_snapshot_write_failure_is_reported_without_game_action(self):
        c=Mock(active_match=self.match,journal=self.journal,match_telemetry=self.monitor)
        with patch.object(self.monitor,'observe',side_effect=sqlite3.OperationalError('disk full')):
            record_controller(c,'observe',self.roster,self.live)
        c.record.assert_called_once_with('match_telemetry_error',error='disk full')
        c.command.assert_not_called()

    def test_missing_durable_identity_refuses_insert_and_unknown_exit_has_no_fresh_sample(self):
        with self.assertRaisesRegex(ValueError,'durable match'):
            self.monitor.event(dict(self.match,match_id='unknown'),'observer_stopped',{})
        self.monitor.event(self.match,'observer_stopped',{},100)
        self.assertIsNone(self.snapshots()[0][1])
        self.assertIsNone(json.loads(self.snapshots()[0][3])['sample'])


if __name__=='__main__':unittest.main()
