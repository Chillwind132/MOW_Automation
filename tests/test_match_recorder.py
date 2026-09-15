"""Manual observers must never mutate the game or confuse quit results with wins."""
import _test_paths  # Shared paths for direct runs and test discovery.
from contextlib import closing
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock,patch

from headless_host import HostController
from match_journal import Journal
from match_metadata import participants
from match_recorder import associate_loaded,save_lobby_results
from modules.end_game_results.legacy import normalize_statistics

ROOT=_test_paths.ROOT


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)
        self.journal=Journal(self.directory/'matches.sqlite3')
        self.key,self.session=self.journal.register({'test':True},{'lobby':'test'})
        fixture=json.loads((ROOT/'tests/fixtures/ai_match.json').read_text())
        self.roster=fixture['loaded_roster']
        self.raw=json.loads((ROOT/'tests/fixtures/solo_statistics.json').read_text())
        self.c=Mock(journal=self.journal,process_key=self.key,host_session_id=self.session,
                    directory=self.directory,identity={'test':True},match_id=None,active_match=None,record_only=True)

    def test_python_record_only_rejects_every_game_action_before_dispatch(self):
        c=HostController.__new__(HostController)
        c.record_only=True
        for action in ('ready','start','configure-friends','spectate-host','gate','results','dismiss-results','exit-completed','create','menu','chat-greeting','chat-announcement','chat-reply'):
            with self.assertRaisesRegex(RuntimeError,'forbids native mutations'):
                c.command(action)

    @unittest.skipUnless(shutil.which('node'),'Node required for bridge guard regression')
    def test_bridge_record_only_rejects_direct_native_commands(self):
        source=(ROOT/'headless/headless_host.js').read_text()
        source=source[source.index('function execute('):source.index('// Hook a returning function')]
        script='let readOnly=true;\n'+source+"\nfor(const action of ['start','ready','results','configure-friends','exit-completed','chat-greeting','chat-announcement','chat-reply']) {let rejected=false;try{execute(action,{})}catch(e){rejected=String(e).includes('Record-only mode')}if(!rejected)throw Error(action)}"
        subprocess.run(['node','-e',script],check=True,capture_output=True)

    def test_capture_reads_statistics_without_selecting_tab(self):
        c=HostController.__new__(HostController)
        c.record_only=True;c.directory=self.directory
        c.ui_objects=Mock(return_value=[{'kind':'mp_statistics','flags':6,'address':'0x123'}])
        c.command=Mock(return_value={'probe':self.raw,'state':{}})
        c.capture_results()
        c.command.assert_called_once_with('probe',target='statistics',address='0x123')

    def test_loaded_association_accepts_another_map_and_settings_without_actions(self):
        self.roster['map']='multi/other_map:battle_zones'
        self.roster['settings'].update(victoryPoints=123,totalManpower=4321)
        self.assertTrue(associate_loaded(self.c,self.roster,self.roster))
        m=self.c.active_match
        self.assertEqual(m['map'],'multi/other_map:battle_zones')
        self.assertEqual(m['effective_settings']['victoryPoints'],123)
        self.assertEqual(m['start_observation'],'lobby_then_loaded')
        self.c.command.assert_not_called()
        self.assertEqual(self.journal.inspect(self.key)['matches'][0]['state'],'playing')

    def test_capture_reuses_discovery_before_brief_dialog_disappears(self):
        c=HostController.__new__(HostController)
        c.record_only=True;c.directory=self.directory
        c.ui_objects=Mock(side_effect=AssertionError('Second scan would miss dialog'))
        c.command=Mock(return_value={'probe':self.raw,'state':{}})
        c.capture_results(objects=[{'kind':'mp_statistics','flags':6,'address':'0x123'}])
        c.ui_objects.assert_not_called()
        c.command.assert_called_once_with('probe',target='statistics',address='0x123')

    def test_missing_replay_keeps_final_pending_without_reading_ui(self):
        associate_loaded(self.c,self.roster)
        with patch('modules.end_game_results.replays.ReplayImporter.poll',return_value=[]):
            with self.assertRaises(TimeoutError):save_lobby_results(self.c,self.roster)
        self.c.capture_results.assert_not_called()
        self.assertEqual(self.journal.inspect(self.key)['matches'][0]['state'],'playing')

    def test_attaching_midgame_is_labelled_and_missing_epoch_is_rejected(self):
        r=copy.deepcopy(self.roster);r['gameStartTimeRaw']=''
        with self.assertRaises(ValueError):associate_loaded(self.c,r)
        associate_loaded(self.c,self.roster)
        self.assertEqual(self.c.active_match['start_observation'],'attached_in_progress')

    def test_replay_save_is_idempotent_and_does_not_read_or_dismiss_ui(self):
        associate_loaded(self.c,self.roster)
        result={'source':'persisted_replay_battleInfoTotal','engine_outcome':None,'replay':{'hash':'fixture'}}
        with patch('modules.end_game_results.wait_for_match',return_value=result):
            self.assertTrue(save_lobby_results(self.c))
            self.assertFalse(save_lobby_results(self.c))
        self.assertIsNone(self.c.active_match['engine_outcome'])
        self.assertEqual(self.journal.inspect(self.key)['matches'][0]['state'],'results_saved')
        self.c.command.assert_not_called()
        self.c.capture_results.assert_not_called()

    def test_current_lobby_epoch_does_not_block_persisted_replay(self):
        associate_loaded(self.c,self.roster)
        r=copy.deepcopy(self.roster);r['gameStartTimeRaw']='different'
        result={'source':'persisted_replay_battleInfoTotal','engine_outcome':None,'replay':{}}
        with patch('modules.end_game_results.wait_for_match',return_value=result) as reader:
            self.assertTrue(save_lobby_results(self.c,r))
        reader.assert_called_once_with(self.journal.path,self.c.active_match,timeout=0)
        self.c.capture_results.assert_not_called()

    def test_reconnect_to_different_lobby_preserves_previous_match(self):
        associate_loaded(self.c,self.roster)
        old_id=self.c.match_id
        self.journal.transition(old_id,'playing','completion_observed',self.c.active_match)
        c=HostController.__new__(HostController)
        c.record_only=True;c.journal=self.journal;c.identity={'test':True}
        c.state=Mock(return_value={'session':'new-session'})
        roster=dict(self.roster,steamLobbyId='different-lobby',gameStartTimeRaw='')
        c.command=Mock(return_value={'probe':roster});c.record=Mock();c.ui_objects=Mock(return_value=[])
        with patch('headless_host.valid_engine',return_value=True),patch('headless_host.gameplay_loaded',return_value=False),patch('headless_host.lobby_loaded',return_value=True):
            c.bind_session()
        self.assertEqual(c.recovery['status'],'idle')
        self.assertIsNone(c.active_match)
        self.assertIsNone(c.match_id)
        self.assertEqual(self.journal.inspect(self.key)['matches'][0]['state'],'completion_observed')
        c.command.assert_called_once_with('probe',target='roster')
        # A changed native session in the SAME lobby still needs proof.
        c.command.return_value={'probe':self.roster}
        with patch('headless_host.valid_engine',return_value=True),patch('headless_host.gameplay_loaded',return_value=True),patch('headless_host.lobby_loaded',return_value=False):
            c.bind_session()
        self.assertEqual(c.recovery['status'],'needs_reconciliation')
        self.assertEqual(c.match_id,old_id)

    def test_attach_in_server_browser_waits_without_roster_probe(self):
        c=HostController.__new__(HostController)
        c.record_only=True;c.command=Mock();c.record=Mock();c.journal=Mock()
        c.state=Mock(return_value={'coreVtable':14833248,'sessionVtable':14284612,
            'session':'0x7ac317a0','stageVtable':14876052,'pageVtable':14853072,
            'pageName':'mp_lobbyinet','service':'0x0','card':'0x0','map':None})
        c.bind_session()
        self.assertEqual(c.recovery['status'],'waiting_for_lobby')
        self.assertIsNone(c.active_match)
        c.command.assert_not_called()
        c.journal.register.assert_not_called()


if __name__=='__main__':
    unittest.main()
