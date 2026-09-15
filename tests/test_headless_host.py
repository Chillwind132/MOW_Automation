"""Regression checks against the previous false-success failure modes."""
import _test_paths  # Shared paths for direct runs and test discovery.
import unittest
import io
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch
from headless_host import (GAME, GAME_HUD, LOBBY, LOBBY_PAGE, MAIN_MENU, INTERNET, SETUP,
                           HostController, background_result, background_window, gameplay_loaded, lobby_loaded, wait_for,
                           configure_console_output)


class ConsoleOutputTests(unittest.TestCase):
    def test_command_rejection_preserves_native_delivery_evidence(self):
        host=HostController.__new__(HostController)
        host.monitor_background=False;host.journal=None;host.record=Mock()
        host.script=Mock()
        for mutation in (False,True,None):
            result={'ok':False,'error':'recipient left','mutationStarted':mutation}
            host.script.exports_sync.command.return_value=result
            with self.assertRaises(RuntimeError) as caught:
                host.command('chat-greeting',steamId='steam')
            self.assertIs(caught.exception.command_result,result)

    def test_cleanup_waits_for_replay_and_ignores_archived_ui_counters(self):
        from match_journal import Journal
        for available in (False,True):
            with self.subTest(available=available), tempfile.TemporaryDirectory() as folder:
                host=HostController.__new__(HostController)
                host.directory=Path(folder);host.journal=Journal(Path(folder)/'journal.sqlite3')
                host.process_key,host.host_session_id=host.journal.register({'pid':1},{'lobby':1})
                host.match_id=host.journal.new_match(host.host_session_id,{})
                host.active_match={'match_id':host.match_id,'engine_outcome':{'winning_team':'b'}}
                host.journal.transition(host.match_id,'lobby','results_available',host.active_match)
                host.recovery={'status':'needs_reconciliation'}
                host.command,host.capture_results,host.archived_ai_results=Mock(),Mock(),Mock()
                host.ui_objects=Mock(return_value=[]);host.checkpoint=Mock(return_value='lobby')
                result={'source':'persisted_replay_battleInfoTotal','engine_outcome':None,'replay':{}}
                with patch('modules.end_game_results.wait_for_match',return_value=result,
                           side_effect=None if available else TimeoutError('replay pending')):
                    if available:self.assertEqual(host.save_ai_results(1)[0],'lobby')
                    else:
                        with self.assertRaises(TimeoutError):host.save_ai_results(1)
                host.command.assert_not_called();host.capture_results.assert_not_called()
                host.archived_ai_results.assert_not_called()
                state=host.journal.inspect(host.process_key)['matches'][0]['state']
                self.assertEqual(state,'lobby_returned' if available else 'results_available')

    def test_solo_heroic_profile_requires_exact_opponents_and_unique_slots(self):
        from copy import deepcopy
        from match_metadata import controlled_ai
        roster = dict(localMemberIdRaw=2, hostMemberIdRaw=2,
            rows=[dict(typeRaw=1, memberIdRaw=2)] +
                 [dict(typeRaw=2, memberIdRaw=i, aiDifficultyRaw='heroic') for i in (3, 4, 5)],
            slots=[dict(memberIdRaw=i, teamRaw='a' if i==2 else 'b') for i in (2, 3, 4, 5)])
        self.assertTrue(controlled_ai(roster))
        for variation in ('difficulty', 'count', 'remote', 'host', 'duplicate_slot', 'duplicate_member', 'no_opponent'):
            case = deepcopy(roster)
            if variation=='difficulty': case['rows'][1]['aiDifficultyRaw']='hard'
            if variation=='count': case['rows'].pop()
            if variation=='remote': case['rows'][1]['typeRaw']=1
            if variation=='host': case['hostMemberIdRaw']=3
            if variation=='duplicate_slot': case['slots'].append(case['slots'][0].copy())
            if variation=='duplicate_member': case['rows'].append(case['rows'][1].copy())
            if variation=='no_opponent':
                for slot in case['slots']: slot['teamRaw']='a'
            with self.subTest(variation=variation):
                self.assertFalse(controlled_ai(case))

    def test_long_ai_profile_preserves_exact_start_and_roster_guards(self):
        root = Path(__file__).resolve().parents[1]
        code = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('headless/headless_host.js','utf8');
const body=source.split("if (action==='start' && options.ai) {")[1].split("if (action === 'gate')")[0];
for(const variation of ['default','long','mismatch','unknown','stale','remote','foreign_host','unready','one_team','resources',
 'solo','solo_hard','solo_two','solo_duplicate_slot','solo_duplicate_member']) {
 const roster={localMemberIdRaw:2,hostMemberIdRaw:2,rows:[{typeRaw:1,memberIdRaw:2,readyRaw:1},
  {typeRaw:2,memberIdRaw:3},{typeRaw:2,memberIdRaw:4}],slots:[{memberIdRaw:2,teamRaw:'a'},
  {memberIdRaw:3,teamRaw:'a'},{memberIdRaw:4,teamRaw:'b'}],settings:{victoryPoints:200,totalManpower:10000}};
 const options={victoryPoints:200,approval:'current'};
 if(variation.startsWith('solo')) {
  roster.slots[1].teamRaw='b';
  roster.rows.push({typeRaw:2,memberIdRaw:5});roster.slots.push({memberIdRaw:5,teamRaw:'b'});
  roster.rows.filter(m=>m.typeRaw===2).forEach(m=>m.aiDifficultyRaw='heroic');
  if(variation==='solo_hard')roster.rows[1].aiDifficultyRaw='hard';
  if(variation==='solo_two')roster.rows.pop();
  if(variation==='solo_duplicate_slot')roster.slots.push({...roster.slots[0]});
  if(variation==='solo_duplicate_member')roster.rows.push({...roster.rows[1]});
 }
 if(variation==='default'){delete options.victoryPoints;roster.settings.victoryPoints=75;}
 if(variation==='mismatch')roster.settings.victoryPoints=75;
 if(variation==='unknown')options.victoryPoints=201;
 if(variation==='stale')options.approval='old';
 if(variation==='remote')roster.rows.push({typeRaw:1,memberIdRaw:5});
 if(variation==='foreign_host')roster.hostMemberIdRaw=3;
 if(variation==='unready')roster.rows[0].readyRaw=0;
 if(variation==='one_team')roster.slots[2].teamRaw='a';
 if(variation==='resources')roster.settings.totalManpower=9999;
 const context={startingRoster:roster,rosterApproval:()=> 'current'};vm.createContext(context);
 vm.runInContext('function run(options){if(true){'+body+'}',context);
 if(['default','long','solo'].includes(variation))assert.doesNotThrow(()=>context.run(options));
 else assert.throws(()=>context.run(options));
}
"""
        result = subprocess.run(['node', '-e', code], cwd=root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ai_joinability_guards_and_native_boolean_marshalling(self):
        root = Path(__file__).resolve().parents[1]
        code = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('headless/headless_host.js','utf8');
const body=source.split("} else if (action === 'ai-joinability') {")[1].split("} else if (action === 'menu') {")[0];
for(const variation of ['closed','open','readonly','remote','foreign_host','invalid','refused']) {
 const calls=[],p={isNull:()=>false,readPointer(){return this;},add(n){assert.equal(n,136);return this;}};
 const roster={rows:[{typeRaw:1,memberIdRaw:2},{typeRaw:2,memberIdRaw:3}],localMemberIdRaw:2,hostMemberIdRaw:2,steamLobbyId:'123'};
 if(variation==='remote')roster.rows.push({typeRaw:1,memberIdRaw:4});
 if(variation==='foreign_host')roster.hostMemberIdRaw=3;
 const context={readOnly:variation==='readonly',lobbyPage(){},lobbyProbe:()=>roster,
  Process:{getModuleByName:()=>({getExportByName:()=> 'getter'})},uint64:x=>x,nativeMutationStarted:false,
  NativeFunction:function(address,result,args,abi){return address==='getter'?()=>p:(self,id,value)=>{
    assert.equal(abi,'thiscall');assert.equal(typeof value,'number');calls.push(value);return variation!=='refused';};}};
 vm.createContext(context);vm.runInContext('function run(options){'+body+'}',context);
 const options={joinability:variation==='open'?'open':variation==='invalid'?'invalid':'closed'};
 if(['closed','open'].includes(variation))assert.equal(context.run(options).joinable,variation==='open');
 else assert.throws(()=>context.run(options));
 assert.equal(calls.length,['closed','open','refused'].includes(variation)?1:0);
}
"""
        result = subprocess.run(['node', '-e', code], cwd=root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unicode_player_names_survive_legacy_output_pipes(self):
        for encoding in ('cp1252', 'utf-8'):
            with self.subTest(encoding=encoding):
                buffers = [io.BytesIO(), io.BytesIO()]
                streams = [io.TextIOWrapper(b, encoding=encoding) for b in buffers]
                with patch('headless_host.sys.stdout', streams[0]), patch('headless_host.sys.stderr', streams[1]):
                    configure_console_output()
                    for stream in streams:
                        print('PYRO \ua731\u1d05', file=stream, flush=True)
                expected = 'PYRO \ua731\u1d05'.encode(encoding, errors='backslashreplace')
                for buffer, stream in zip(buffers, streams):
                    self.assertIn(expected, buffer.getvalue())
                    stream.detach()

    def test_captured_text_streams_need_no_reconfiguration(self):
        with patch('headless_host.sys.stdout', io.StringIO()), patch('headless_host.sys.stderr', io.StringIO()):
            configure_console_output()


class Clock:
    def __init__(self): self.time = 0
    def now(self): return self.time
    def sleep(self, duration): self.time += duration


class ValidationTests(unittest.TestCase):
    def state(self, **changes):
        return dict(coreVtable=0xe25660,sessionVtable=0xd9f744,
                    stageVtable=GAME,pageVtable=GAME_HUD,**changes)

    def test_game_stage_before_map_load_is_not_success(self):
        state = self.state()
        state['pageVtable'] = 0
        self.assertFalse(gameplay_loaded(state))

    def test_dummy_or_corrupt_session_is_not_success(self):
        state = self.state()
        state['sessionVtable'] = 0
        self.assertFalse(gameplay_loaded(state))

    def test_stale_memory_after_crash_is_not_success(self):
        clock = Clock()
        def sample():
            return {'ticks':min(3,int(clock.time*2)), 'loaded':True}
        with self.assertRaisesRegex(TimeoutError,'heartbeat stalled'):
            wait_for(sample,lambda s:s['loaded'],10,stable_seconds=5,
                     clock=clock.now,sleep=clock.sleep)

    def test_transient_transition_resets_stability_window(self):
        clock = Clock()
        def sample():
            return {'ticks':int(clock.time*10),'loaded':not 1 <= clock.time < 2}
        wait_for(sample,lambda s:s['loaded'],10,stable_seconds=3,
                 clock=clock.now,sleep=clock.sleep)
        self.assertGreaterEqual(clock.time,5)

    def test_missing_transition_times_out(self):
        clock = Clock()
        with self.assertRaisesRegex(TimeoutError,'did not satisfy'):
            wait_for(lambda:{'ticks':int(clock.time*10)},lambda s:False,2,
                     clock=clock.now,sleep=clock.sleep)

    def test_live_gameplay_passes_after_stable_interval(self):
        clock = Clock()
        result = wait_for(lambda:self.state(ticks=int(clock.time*10)),
                          gameplay_loaded,10,stable_seconds=3,
                          clock=clock.now,sleep=clock.sleep)
        self.assertEqual(result['ticks'],30)


class LobbyTests(unittest.TestCase):
    def lobby(self):
        return dict(coreVtable=0xe25660, sessionVtable=0xd9f744,
                    stageVtable=LOBBY, pageVtable=LOBBY_PAGE,
                    serviceVtable=0xde0fd0, card='0x12340000', map='test-map', core='0x1234')

    def controller(self, state):
        controller = HostController.__new__(HostController)
        controller.state = Mock(return_value=state)
        controller.command = Mock()
        controller.checkpoint = Mock(return_value=self.lobby())
        controller.create_widget = Mock(return_value='0x12345678')
        return controller

    def test_existing_lobby_does_not_ready_or_start(self):
        controller = self.controller(self.lobby())
        self.assertEqual(controller.host_lobby(10), self.lobby())
        controller.command.assert_not_called()

    def test_cold_start_waits_for_main_menu_before_hosting(self):
        cold = dict(core='0x0', coreVtable=0, sessionVtable=0,
                    stageVtable=0, pageVtable=0, ticks=0)
        controller = self.controller(cold)
        menu = {**cold, 'pageVtable': MAIN_MENU, 'ticks': 10}
        online = {**self.lobby(), 'stageVtable': INTERNET}
        setup = {**online, 'stageVtable': SETUP, 'pageVtable': 0xe2a540}
        controller.checkpoint.side_effect = [menu, online, setup, self.lobby(), self.lobby()]
        controller.host_lobby(10)
        predicate = controller.checkpoint.call_args_list[0].args[1]
        self.assertFalse(predicate(cold))
        self.assertTrue(predicate(menu))
        self.assertEqual([c.args[0] for c in controller.command.call_args_list],
                         ['internet', 'setup', 'create'])

    def test_cold_start_timeout_and_stalled_menu_do_not_issue_commands(self):
        for menu_at in (None, 3):
            with self.subTest(menu_at=menu_at):
                clock = Clock()
                cold = dict(core='0x0', coreVtable=0, sessionVtable=0,
                            stageVtable=0, pageVtable=0, ticks=0)
                controller = self.controller(cold)
                controller.state.side_effect = lambda: {
                    **cold, 'pageVtable': MAIN_MENU if menu_at is not None and clock.time >= menu_at else 0}
                controller.checkpoint.side_effect = lambda name, predicate, timeout: wait_for(
                    controller.state, predicate, timeout, stable_seconds=1,
                    clock=clock.now, sleep=clock.sleep)
                with self.assertRaises(TimeoutError):
                    controller.host_lobby(10)
                controller.command.assert_not_called()

    def test_cold_start_wait_accepts_slow_live_menu(self):
        clock = Clock()
        cold = dict(core='0x0', coreVtable=0, sessionVtable=0,
                    stageVtable=0, pageVtable=0, ticks=0)
        controller = self.controller(cold)
        controller.checkpoint.side_effect = TimeoutError('capture startup predicate')
        with self.assertRaises(TimeoutError):
            controller.host_lobby(10)
        predicate = controller.checkpoint.call_args.args[1]
        result = wait_for(lambda: {**cold, 'ticks': int(clock.time * 10),
            'pageVtable': MAIN_MENU if clock.time >= 4 else 0},
            predicate, 10, stable_seconds=1, clock=clock.now, sleep=clock.sleep)
        self.assertEqual(result['pageVtable'], MAIN_MENU)
        self.assertGreaterEqual(clock.time, 5)

    def test_existing_internet_browser_enters_setup(self):
        state=self.lobby()
        state.update(stageVtable=0xe2fd94,pageVtable=0xe2a3d0,pageName='mp_lobbyinet')
        controller=self.controller(state)
        setup={**state,'stageVtable':SETUP,'pageVtable':0xe2a540}
        controller.checkpoint.side_effect=[setup,self.lobby(),self.lobby()]
        controller.host_lobby(10)
        self.assertEqual([c.args[0] for c in controller.command.call_args_list],['setup','create'])
        state['pageName']='unexpected'
        controller=self.controller(state)
        with self.assertRaisesRegex(RuntimeError,'Cannot host to lobby'):
            controller.host_lobby(10)
        controller.command.assert_not_called()

    def test_setup_stops_after_create(self):
        state = self.lobby()
        state['stageVtable'] = SETUP
        controller = self.controller(state)
        controller.host_lobby(10)
        controller.command.assert_called_once_with('create', widget='0x12345678')

    def test_existing_game_is_rejected_without_mutation(self):
        state = self.lobby()
        state.update(stageVtable=GAME, pageVtable=GAME_HUD)
        controller = self.controller(state)
        with self.assertRaisesRegex(RuntimeError, 'Cannot host to lobby'):
            controller.host_lobby(10)
        controller.command.assert_not_called()

    def test_incomplete_lobby_is_not_accepted(self):
        for key, value in [('card', '0x0'), ('map', None), ('serviceVtable', 0)]:
            with self.subTest(key=key):
                state = self.lobby()
                state[key] = value
                self.assertFalse(lobby_loaded(state))


class BackgroundTests(unittest.TestCase):
    def test_manual_visibility_change_is_nonfatal_by_default(self):
        result = background_result([{'gameForeground':True}])
        self.assertEqual(result['exit_code'],0)
        self.assertEqual(result['status'],'interrupted')
        self.assertFalse(result['validation_passed'])

    def test_strict_visibility_check_uses_separate_exit_code(self):
        result = background_result([{'gameForeground':True}],strict=True)
        self.assertEqual(result['exit_code'],2)
        self.assertEqual(result['cause'],'unknown')

    def test_missing_window_is_not_background_success(self):
        self.assertFalse(background_window({'gameForeground':False, 'windows':[]}))

    def test_restored_or_foreground_window_is_rejected(self):
        self.assertFalse(background_window({'gameForeground':False,
                                            'windows':[{'minimized':False}]}))
        self.assertFalse(background_window({'gameForeground':True,
                                            'windows':[{'minimized':True}]}))

    def test_wait_for_asynchronous_minimize_completion(self):
        clock = Clock()
        result = wait_for(lambda: {'gameForeground':False,
                                  'windows':[{'minimized':clock.time >= 1}]},
                          background_window, 5, clock=clock.now, sleep=clock.sleep)
        self.assertTrue(background_window(result))
        self.assertGreaterEqual(clock.time, 1)

    def test_transient_window_violation_is_retained(self):
        from unittest.mock import patch
        controller = HostController.__new__(HostController)
        controller.pid = 1
        controller.record = Mock()
        controller.background_violations = []
        restored = {'gameForeground':False, 'windows':[{'minimized':False}]}
        minimized = {'gameForeground':False, 'windows':[{'minimized':True}]}
        with patch('headless_host.window_state', side_effect=[restored, minimized]):
            controller.observe_window()
            controller.observe_window()
        self.assertEqual(controller.background_violations, [restored])


class LifecycleTests(unittest.TestCase):
    def test_result_save_failure_prevents_dismissal(self):
        from unittest.mock import patch
        controller = HostController.__new__(HostController)
        controller.capture_results = Mock(return_value={})
        controller.command = Mock()
        with patch('modules.end_game_results.wait_for_match',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):
                controller.dismiss_saved_results({'match_id':'test'})
        controller.command.assert_not_called()

    def test_start_failure_is_not_retried_and_does_not_quit(self):
        controller = HostController.__new__(HostController)
        controller.host_lobby = Mock()
        controller.ui_objects = Mock(return_value=[])
        controller.quit_solo = Mock()
        controller.checkpoint = Mock()
        def command(action, **options):
            if action == 'start':
                raise TimeoutError('Start outcome unknown')
            return {'startAllowed':True}
        controller.command = Mock(side_effect=command)
        with tempfile.TemporaryDirectory() as temporary:
            controller.directory = Path(temporary)
            with self.assertRaisesRegex(TimeoutError,'Start outcome unknown'):
                controller.solo_cycle(30,5)
            self.assertTrue((controller.directory/'match_observation.json').exists())
        controller.quit_solo.assert_not_called()
        self.assertEqual(sum(call.args[0] == 'start' for call in controller.command.call_args_list),1)

    def test_previous_visible_statistics_prevent_new_cycle(self):
        controller = HostController.__new__(HostController)
        controller.host_lobby = Mock()
        controller.ui_objects = Mock(return_value=[{'kind':'mp_statistics','flags':6}])
        controller.command = Mock()
        with self.assertRaisesRegex(RuntimeError,'previous statistics'):
            controller.solo_cycle(30,5)
        controller.command.assert_not_called()

    def test_quit_rejects_lobby_without_mutation(self):
        controller = HostController.__new__(HostController)
        controller.state = Mock(return_value={'stageVtable':LOBBY,'pageVtable':LOBBY_PAGE})
        controller.command = Mock()
        with self.assertRaisesRegex(RuntimeError,'requires gameplay'):
            controller.quit_solo(30,5)
        controller.command.assert_not_called()


if __name__ == '__main__':
    unittest.main()


class PowerRequestTests(unittest.TestCase):
    @patch('headless_host.ctypes.windll.kernel32.SetThreadExecutionState')
    def test_releases_after_interrupt_and_allows_screen_sleep(self, set_state):
        from headless_host import prevent_idle_sleep
        set_state.side_effect = [0x80000000, 0x80000001]
        with self.assertRaises(KeyboardInterrupt):
            with prevent_idle_sleep():
                raise KeyboardInterrupt
        self.assertEqual([c.args[0] for c in set_state.call_args_list],
                         [0x80000001, 0x80000000])

    @patch('headless_host.ctypes.windll.kernel32.SetThreadExecutionState')
    def test_restores_previous_request_on_normal_exit(self, set_state):
        from headless_host import prevent_idle_sleep
        set_state.side_effect = [0x80000003, 0x80000001]
        with prevent_idle_sleep():
            pass
        self.assertEqual(set_state.call_args_list[-1].args, (0x80000003,))

    @patch('headless_host.ctypes.windll.kernel32.SetThreadExecutionState', return_value=0)
    def test_failed_request_is_reported(self, set_state):
        from headless_host import prevent_idle_sleep
        with self.assertRaisesRegex(RuntimeError, 'refused'):
            with prevent_idle_sleep():
                self.fail('Should not run without sleep protection')
