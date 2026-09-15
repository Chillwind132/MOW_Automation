"""Readiness races, native execution policy, local controls and spectator identities."""
import _test_paths  # Shared paths for direct runs and test discovery.
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch,Mock

from friends_host import Control,ReadyWindow,readiness,run,capacity_ready,prepare
from match_metadata import participants
from match_journal import Journal,reconcile

ROOT=_test_paths.ROOT


def roster():
    return {'localMemberIdRaw':1,'hostMemberIdRaw':1,
            'settings':{'armySelectionMode':3,'enableSpectators':1,'maxPlayers':2},
            'slots':[{'slotIdRaw':1,'memberIdRaw':2,'teamRaw':'a'},
                     {'slotIdRaw':4,'memberIdRaw':3,'teamRaw':'b'}],
            'rows':[{'memberIdRaw':i,'typeRaw':4 if i==1 else 1,'teamRaw':t,
                     'readyRaw':0 if i==1 else 1,'armyRaw':'' if i==1 else 'ger',
                     'identityWordsRaw':[100+i,17825793],'displayName':'same name'}
                    for i,t in [(1,'spectator'),(2,'a'),(3,'b')]]}


class FriendsTests(unittest.TestCase):
    def test_match_limit_stops_after_results_are_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            j=Journal(root/'matches.sqlite3')
            key,session=j.register({'test':True},{'lobby':'test'})
            r=roster();r.update(steamLobbyId='test',map='test',gameStartTimeRaw='new')
            match={'match_id':'test','hosting_mode':'friends','starting_roster':r,'native_game_start_time':'new'}
            j.new_match(session,match,'test')
            j.transition('test','lobby','playing',match)
            c=Mock(journal=j,process_key=key,host_session_id=session,match_id='test',directory=root,
                   active_match=match,recovery={'status':'playing'})
            c.state.return_value={'stageVtable':0xe2fe30,'pageVtable':0xe2ae58,'ticks':100}
            c.command.side_effect=[{'probe':r},{'probe':{'managerStateRaw':3}}]
            with patch('friends_host.time.sleep'):
                result=run(c,Control(root/'control.sqlite3'),max_matches=1)
            c.finish_ai.assert_called_once()
            c.save_ai_results.assert_called_once()
            self.assertEqual(result['matches_saved'],1)
            self.assertFalse(result['running'])

    def test_loading_waits_for_delayed_epoch_without_replaying_start(self):
        for initial in ('', 'old'):
            with self.subTest(initial=initial), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                j=Journal(root/'matches.sqlite3')
                key,session=j.register({'test':True},{'lobby':'test'})
                r=roster();r.update(steamLobbyId='test',map='test',gameStartTimeRaw=initial)
                match={'match_id':'test','hosting_mode':'friends','starting_roster':copy.deepcopy(r)}
                j.new_match(session,match,'test')
                j.transition('test','lobby','loading',match)
                c=Mock(journal=j,process_key=key,host_session_id=session,match_id='test',
                       directory=root,active_match=match,recovery={'status':'loading'})
                c.state.return_value={'stageVtable':0xe2fe30,'pageVtable':0xe2ae58,'ticks':100}
                ctl=Control(root/'control.sqlite3')
                calls=[]
                def command(action, **options):
                    calls.append((action,options))
                    if len(calls)==3:
                        r['gameStartTimeRaw']='new'
                        ctl.request('stop')
                    return {'probe':copy.deepcopy(r)}
                c.command.side_effect=command
                elapsed=[100.0]
                def slow_load(_):elapsed[0]+=150
                with patch('friends_host.time.sleep',side_effect=slow_load),patch('friends_host.time.monotonic',side_effect=lambda:elapsed[0]):
                    run(c,ctl)
                self.assertEqual(match['native_game_start_time'],'new')
                self.assertEqual(calls,[('probe',{'target':'roster'})]*3)
                self.assertEqual(j.inspect(key)['matches'][0]['state'],'playing')

    def test_mixed_test_requires_human_ready_but_not_bot_ready_byte(self):
        r=roster();r['rows'][1].update(typeRaw=2,readyRaw=0)
        self.assertTrue(readiness(r,2,ai_test='mixed')['ready'])
        r['rows'][2]['readyRaw']=0
        self.assertFalse(readiness(r,2,ai_test='mixed')['ready'])

    def test_bot_lobby_readiness_does_not_use_human_ready_byte(self):
        r=roster()
        for row in r['rows'][1:]:
            row.update(typeRaw=2,readyRaw=0,armyRaw='random')
        result=readiness(r,2,ai_test=True)
        self.assertTrue(result['ready'],result['reasons'])
        self.assertEqual(result['ready_players'],2)
        r['rows'][1]['typeRaw']=1
        self.assertFalse(readiness(r,2,ai_test=True)['ready'])

    def test_humans_still_require_ready_byte(self):
        r=roster();r['rows'][1]['readyRaw']=0
        self.assertFalse(readiness(r,2)['ready'])

    def test_capacity_requires_exact_even_count_and_equal_slot_layout(self):
        r=roster()
        self.assertTrue(capacity_ready(r,2))
        self.assertFalse(capacity_ready(r,4))
        self.assertFalse(capacity_ready(r,3))
        r['settings']['maxPlayers']=4
        self.assertFalse(capacity_ready(r,4))
        r['slots'] += [{'slotIdRaw':2,'memberIdRaw':0,'teamRaw':'a'},
                       {'slotIdRaw':5,'memberIdRaw':0,'teamRaw':'b'}]
        self.assertTrue(capacity_ready(r,4))
        self.assertFalse(readiness(r,2)['ready'])

    def test_prepare_configures_capacity_and_verifies_before_returning(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=roster();r['slots']=[dict(s,memberIdRaw=0) for s in r['slots']];r['rows']=r['rows'][:1]
            r['settings']['maxPlayers']=6
            c=Mock(active_match=None,recovery={'status':'idle'},directory=Path(tmp),expected_map=None)
            c.command.return_value={'probe':{'roster':r,'approval':'fresh'}}
            with patch('friends_host._verify_command') as verify:
                def command(action,**options):
                    if action=='configure-capacity':
                        r['settings']['maxPlayers']=4
                        r['slots']=[{'teamRaw':t,'memberIdRaw':0} for t in ('a','a','b','b')]
                    return {'probe':{'roster':r,'approval':'fresh'} if options.get('target')=='approval' else r}
                c.command.side_effect=command
                result=prepare(c,10,4)
                self.assertTrue(capacity_ready(result,4))
                self.assertTrue(verify.call_args.args[2]({}))
                self.assertIn('configure-capacity',[call.args[0] for call in c.command.call_args_list])

    def test_prepare_waits_for_spectator_ui_and_refreshes_approval(self):
        for appears in (True,False):
            with self.subTest(appears=appears), tempfile.TemporaryDirectory() as tmp:
                r=roster();r['rows']=r['rows'][:1]
                r['rows'][0].update(typeRaw=1,teamRaw='a')
                c=Mock(active_match=None,recovery={'status':'idle'},directory=Path(tmp))
                probes=iter([[],[],[{'name':'spectator:spectator'}] if appears else []])
                ui_ready=False
                def command(action,**options):
                    if options.get('target')=='controls':
                        return {'probe':{'nodes':next(probes)}}
                    if options.get('target')=='approval':
                        return {'probe':{'roster':r,'approval':'fresh' if ui_ready else 'old'}}
                    if action=='spectate-host':
                        self.assertTrue(ui_ready)
                        self.assertEqual(options['approval'],'fresh')
                        r['rows'][0].update(typeRaw=4,teamRaw='spectator')
                    return {'probe':r}
                def checkpoint(label,predicate,timeout):
                    nonlocal ui_ready
                    self.assertEqual(timeout,10)
                    self.assertFalse(predicate({}))
                    self.assertFalse(predicate({}))
                    if not predicate({}):
                        raise TimeoutError('spectator UI unavailable')
                    ui_ready=True
                c.command.side_effect=command;c.checkpoint.side_effect=checkpoint
                with patch('friends_host._verify_command'):
                    if appears:
                        prepare(c,10,2)
                    else:
                        with self.assertRaises(TimeoutError):prepare(c,10,2)
                        self.assertNotIn('spectate-host',[x.args[0] for x in c.command.call_args_list])

    def test_idle_dialog_and_missing_service_wait_without_starting(self):
        for dialog in (True,False):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);c=Mock(active_match=None,match_id=None,journal=Mock(path=root/'matches.sqlite3'),directory=root)
                c.state.return_value={'pageVtable':0xe2bea8 if dialog else 0xe2b2cc}
                c.command.side_effect=RuntimeError('probe: Expected one active service of kind 8')
                ctl=Control(root/'control.sqlite3')
                with patch('friends_host.prepare'),patch('friends_host.time.sleep',side_effect=lambda _:ctl.request('stop')):
                    result=run(c,ctl)
                self.assertNotIn('error',result)
                self.assertFalse(any(call.args[0]=='start' for call in c.command.call_args_list))

    def test_expected_map_gates_every_start_check(self):
        r=roster();r['map']='multi/other:battle_zones'
        expected='multi/3v3_big_desert_town:battle_zones'
        self.assertFalse(readiness(r,expected_map=expected)['ready'])
        r['map']=expected
        self.assertTrue(readiness(r,expected_map=expected)['ready'])

    def test_ready_humans_exclude_spectator_and_keep_steam_identity(self):
        r=roster()
        check=readiness(r)
        self.assertTrue(check['ready'],check)
        self.assertEqual((check['players'],check['ready_players']),(2,2))
        p=participants(r,'match')
        self.assertEqual(p[0]['role'],'spectator')
        self.assertEqual(p[0]['controller_kind'],'local_host')
        self.assertIsNotNone(p[0]['steam_id'])
        self.assertEqual(len({m['participant_key'] for m in p}),3)

    def test_unready_join_and_disconnect_prevent_start(self):
        r=roster();r['rows'][1]['readyRaw']=0
        self.assertFalse(readiness(r)['ready'])
        r=roster();r['rows'].pop()
        self.assertFalse(readiness(r)['ready'])
        r=roster();extra=copy.deepcopy(r['rows'][1]);extra['memberIdRaw']=4
        r['rows'].append(extra)
        self.assertFalse(readiness(r)['ready'])

    def test_team_and_profile_changes_prevent_start(self):
        for kind in ('one_team','disabled_spectators','wrong_mode','host_playing','nation_missing','too_few'):
            r=roster()
            if kind=='one_team': r['slots'][1]['teamRaw']='a'
            if kind=='disabled_spectators': r['settings']['enableSpectators']=0
            if kind=='wrong_mode': r['settings']['armySelectionMode']=1
            if kind=='host_playing': r['rows'][0]['typeRaw']=1
            if kind=='nation_missing': r['rows'][1]['armyRaw']=''
            self.assertFalse(readiness(r,3 if kind=='too_few' else 2)['ready'],kind)

    def test_ai_is_opt_in_and_test_mode_refuses_remote_humans(self):
        r=roster()
        self.assertFalse(readiness(r,ai_test=True)['ready'])
        for m in r['rows'][1:]:
            m.update(typeRaw=2,identityWordsRaw=[0,0])
        self.assertFalse(readiness(r)['ready'])
        self.assertTrue(readiness(r,ai_test=True)['ready'])

    def test_ambiguous_identity_and_slot_refuse_start(self):
        r=roster();r['rows'][2]['identityWordsRaw']=r['rows'][1]['identityWordsRaw']
        self.assertFalse(readiness(r)['ready'])
        r=roster();r['slots'].append(copy.deepcopy(r['slots'][0]))
        self.assertFalse(readiness(r)['ready'])
        r=roster();r['rows'].append(copy.deepcopy(r['rows'][0]))
        self.assertFalse(readiness(r)['ready'])

    def test_countdown_restarts_on_nation_roster_or_hold_change(self):
        w=ReadyWindow(5)
        self.assertFalse(w.update('nationA',True,0))
        self.assertFalse(w.update('nationB',True,4))
        self.assertFalse(w.update('nationB',True,8))
        self.assertTrue(w.update('nationB',True,9))
        self.assertFalse(w.update('nationB',False,10))
        self.assertFalse(w.update('nationB',True,11))
        self.assertTrue(w.update('nationB',True,16))

    def test_local_control_sequence_ack_and_stale_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=Control(Path(tmp)/'control.sqlite3')
            self.assertFalse(c.status()['running'])
            with patch('friends_host.time.time',return_value=100):
                token=c.begin()
                requested=c.request('hold')
                self.assertEqual(requested['requested_sequence'],1)
                self.assertEqual(c.desired(token),('hold',1))
                c.publish(token,{'running':True,'phase':'held','applied_sequence':1})
                self.assertEqual(c.status()['applied_sequence'],1)
                c.request('run');c.request('stop')
                self.assertEqual(c.desired(token),('stop',3))
            with patch('friends_host.time.time',return_value=120):
                self.assertTrue(c.status()['stale'])
                with self.assertRaises(RuntimeError): c.request('run')
            c.publish(token,{'running':False,'phase':'stopped'})
            with self.assertRaises(RuntimeError): c.request('run')

    def test_completion_retries_before_exit_and_saves_before_next_lobby(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            j=Journal(root/'matches.sqlite3')
            key,session=j.register({'test':True},{'lobby':'test'})
            r=roster();r.update(steamLobbyId='test',map='test',gameStartTimeRaw='new')
            match={'match_id':'test','hosting_mode':'friends','starting_roster':r,'native_game_start_time':'new'}
            j.new_match(session,match,'test')
            j.transition('test','lobby','playing',match)
            c=Mock(journal=j,process_key=key,host_session_id=session,match_id='test',directory=root,active_match=match,
                   recovery={'status':'playing'})
            c.state.return_value={'stageVtable':0xe2fe30,'pageVtable':0xe2ae58,'ticks':100}
            c.command.side_effect=lambda action,**kw:{'probe':r if kw['target']=='roster' else {'managerStateRaw':3}}
            c.capture_completion.side_effect=[ValueError('not ready'),{'saved':True}]
            ctl=Control(root/'control.sqlite3')
            c.save_ai_results.side_effect=lambda timeout:ctl.request('stop')
            with patch('friends_host.time.sleep'):
                result=run(c,ctl,held=True)
            self.assertEqual(c.capture_completion.call_count,2)
            c.finish_ai.assert_called_once()
            c.save_ai_results.assert_called_once()
            order=[x[0] for x in c.mock_calls]
            self.assertLess(order.index('capture_completion'),order.index('finish_ai'))
            self.assertLess(order.index('finish_ai'),order.index('save_ai_results'))
            self.assertEqual(result['matches_saved'],1)
            self.assertFalse(result['running'])

    def test_resume_saved_completion_requires_same_epoch(self):
        record={'matches':[{'match_id':'m','session_id':'s','state':'completion_observed',
                          'latest_match_observation':{'native_game_start_time':'epoch'}}],
                'unresolved_commands':[]}
        obs={'process_key':'p','session_id':'s','loaded':True,'native_game_start_time':'epoch'}
        self.assertEqual(reconcile(record,'p','s',obs)['status'],'completion_observed')
        obs['native_game_start_time']='another'
        self.assertEqual(reconcile(record,'p','s',obs)['status'],'needs_reconciliation')

    def test_planned_restart_follows_save_and_reprepares_without_losing_hold(self):
        for phase in ('playing','results_available','save_failure'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);j=Journal(root/'matches.sqlite3')
                key,session=j.register({'test':True},{'lobby':'test'})
                r=roster();r.update(steamLobbyId='test',map='test',gameStartTimeRaw='new')
                match={'match_id':'test','hosting_mode':'friends','starting_roster':r,'native_game_start_time':'new'}
                j.new_match(session,match,'test')
                j.transition('test','lobby','results_available' if phase=='results_available' else 'playing',match)
                c=Mock(journal=j,process_key=key,host_session_id=session,match_id='test',directory=root,
                       active_match=match,recovery={'status':phase})
                c.state.return_value={'stageVtable':0xe2fe30,'pageVtable':0xe2b2cc if phase=='results_available' else 0xe2ae58,'ticks':100}
                c.command.side_effect=lambda action,**kw:{'probe':r if kw.get('target')=='roster' else {'managerStateRaw':3}}
                ctl=Control(root/'control.sqlite3');order=[]
                def save(timeout):
                    order.append('save')
                    if phase=='save_failure':raise TimeoutError('replay pending')
                    c.active_match=c.match_id=None
                c.save_ai_results.side_effect=save
                def restart(controller,match_id,timeout,poll):
                    order.append('restart');poll()
                    self.assertEqual(match_id,'test')
                    self.assertEqual(ctl.status()['desired'],'hold')
                    self.assertTrue(ctl.status()['running'])
                def prepare(*args):
                    order.append('prepare');ctl.request('stop')
                with patch('friends_host.time.sleep'),patch('friends_host.LobbySocial'), \
                     patch('host_restart.restart_after_match',side_effect=restart) as restart_mock, \
                     patch('friends_host.prepare',side_effect=prepare):
                    if phase=='save_failure':
                        with self.assertRaises(TimeoutError):run(c,ctl,held=True,restart=True)
                        restart_mock.assert_not_called()
                    else:
                        result=run(c,ctl,held=True,restart=True)
                        self.assertEqual(order,['save','restart','prepare'])
                        self.assertEqual(result['matches_saved'],1)
                        self.assertFalse(result['running'])

    @unittest.skipUnless(shutil.which('node'),'Node required for native bridge policy regression')
    def test_native_guard_rejects_races_at_execution(self):
        variants=[]
        r=roster();variants.append((r,True))
        r=roster();r['rows'][1]['readyRaw']=0;variants.append((r,False))
        r=roster();r['slots'][1]['teamRaw']='a';variants.append((r,False))
        r=roster();r['rows'][0]['typeRaw']=1;variants.append((r,False))
        r=roster();r['settings']['armySelectionMode']=2;variants.append((r,False))
        r=roster();r['rows'][1]['armyRaw']='';variants.append((r,False))
        r=roster();r['settings']['maxPlayers']=6;variants.append((r,False))
        r=roster();extra=copy.deepcopy(r['rows'][1]);extra['memberIdRaw']=4
        r['rows'].append(extra);r['slots'].append({'slotIdRaw':2,'memberIdRaw':4,'teamRaw':'a'})
        variants.append((r,False))
        self.assertIn('teams must have equal player counts',readiness(r)['reasons'])
        source=(ROOT/'headless/headless_host.js').read_text()
        source=source[source.index('function friendsReady('):source.index('function settingsProbe(')]
        script=source+'\nconst cases='+json.dumps(variants)+'; for(const [r,want] of cases) {if(friendsReady(r,2)!==want) throw Error(JSON.stringify(r));}'
        subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)


if __name__=='__main__':
    unittest.main()
