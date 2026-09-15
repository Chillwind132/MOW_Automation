import _test_paths  # Shared paths for direct runs and test discovery.
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from game_master import GameMaster,Settings,CodexBackend,validate_reply,clean_environment,command,check_login,executable


class GameMasterTests(unittest.TestCase):
    def setUp(self):
        delay=patch('game_master.random.uniform',return_value=0)
        delay.start();self.addCleanup(delay.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'test.db'
        self.c=SimpleNamespace(journal=SimpleNamespace(path=self.path),record_only=False,record=Mock(),command=Mock())
        self.raw={'roster':{'localMemberIdRaw':1,'hostMemberIdRaw':1,'gameStartTimeRaw':'',
                           'settings':{'teamArmies':{'a':'ger_ss','b':'rus'}},'map':'desert'},'input_busy':False}
        self.obs={'lobby_id':'lobby','players':[{'native_member_id':1,'steam_id':'host','display_name':'Player17'},
                    {'native_member_id':2,'steam_id':'guest','display_name':'Alex'}],'messages':[]}
        self.social=SimpleNamespace(latest=self.raw,last_send=-float('inf'))
        p=patch('lobby_social.normalize_social',side_effect=lambda raw:self.obs);p.start();self.addCleanup(p.stop)
        self.backend=Mock();self.backend.generate.return_value='SS vs USSR'
        self.gm=GameMaster(self.c,Settings(),self.backend);self.addCleanup(lambda:self.gm.close())

    def tick(self,enabled=True,now=100):
        with patch('game_master.time.monotonic',return_value=now):self.gm.tick(self.social,enabled)

    def message(self,text='host, what nations?',name='Alex',key='new'):
        self.obs['messages'].append({'message_key':key,'kind':'player','sender_name':name,'text':text})

    def launch(self):
        self.tick();self.message();self.tick();self.gm.future.result(timeout=2)

    def test_old_history_silent_new_addressed_message_once(self):
        self.message(key='old');self.tick();self.backend.generate.assert_not_called()
        self.message();self.tick();self.gm.future.result(timeout=2);self.tick(now=101);self.tick(now=130)
        self.c.command.assert_called_once()
        self.assertEqual(self.c.command.call_args.args,('chat-reply',))
        self.assertEqual(self.c.command.call_args.kwargs['steamId'],'guest')
        context=self.backend.generate.call_args.args[0]
        self.assertNotIn('steam_id',json.dumps(context))
        self.assertNotIn('guest',json.dumps(context))

    def test_hold_lobby_change_leave_and_settings_change_discard(self):
        for cause in ('hold','lobby','left','epoch','settings','busy'):
            with self.subTest(cause=cause):
                self.gm.close();self.gm=GameMaster(self.c,Settings(),self.backend)
                self.obs['messages']=[];self.obs['lobby_id']=cause
                self.obs['players']=self.obs['players'][:1]+[{'native_member_id':2,'steam_id':'guest','display_name':'Alex'}]
                self.raw['input_busy']=False;self.raw['roster']['gameStartTimeRaw']=''
                self.raw['roster']['settings']={'teamArmies':{'a':'ger_ss','b':'rus'}}
                self.launch()
                if cause=='lobby':self.obs['lobby_id']='changed'
                if cause=='left':self.obs['players'].pop()
                if cause=='epoch':self.raw['roster']['gameStartTimeRaw']='next'
                if cause=='settings':self.raw['roster']['settings']['teamArmies']['b']='usa'
                if cause=='busy':self.raw['input_busy']=True
                self.tick(enabled=cause!='hold',now=101)
                self.c.command.assert_not_called()

    def test_failure_and_uncertain_send_not_retried(self):
        self.launch();self.c.command.side_effect=RuntimeError('native timeout')
        self.tick(now=101);self.tick(now=130)
        self.c.command.assert_called_once()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM game_master_replies').fetchone()[0],'unconfirmed')

    def test_generation_failure_stays_silent(self):
        self.tick();self.backend.generate.side_effect=RuntimeError('model unavailable');self.message();self.tick()
        try:self.gm.future.result(timeout=2)
        except RuntimeError:pass
        self.tick(now=101);self.c.command.assert_not_called()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM game_master_replies').fetchone()[0],'generation_failed')

    def test_stop_rechecked_immediately_before_send(self):
        self.launch();self.c.game_master_can_send=lambda:False
        self.tick(now=101);self.c.command.assert_not_called()

    def test_delayed_reply_rechecks_hold(self):
        self.launch()
        with patch('game_master.random.uniform',return_value=3):self.tick(now=101)
        self.tick(now=103);self.c.command.assert_not_called()
        self.tick(enabled=False,now=104);self.c.command.assert_not_called()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM game_master_replies').fetchone()[0],'discarded_stale')

    def test_timeout_kills_model_process(self):
        process=Mock();process.communicate.side_effect=subprocess.TimeoutExpired('codex',5)
        process.poll.return_value=None
        backend=CodexBackend(Settings(timeout=5))
        with patch('game_master.executable',return_value='codex.exe'),patch('game_master.subprocess.Popen',return_value=process):
            with self.assertRaises(subprocess.TimeoutExpired):backend.generate({'max_chars':120})
        process.kill.assert_called_once();process.wait.assert_called_once_with(timeout=5)
        self.assertIsNone(backend.process)

    def test_legacy_addressed_mode_considers_all_chat_and_dry_run_never_sends(self):
        self.gm.close();self.gm=GameMaster(self.c,Settings(mode='addressed',dry_run=True),self.backend)
        self.tick();self.message('nice map',key='second');self.tick();self.gm.future.result(timeout=2);self.tick(now=101)
        self.backend.generate.assert_called_once()
        self.c.command.assert_not_called()
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT status FROM game_master_replies').fetchone()[0],'dry_run')

    def test_model_can_choose_silence_for_unaddressed_chat(self):
        self.backend.generate.return_value=None
        self.tick();self.message('hi');self.tick();self.gm.future.result(timeout=2);self.tick(now=101)
        self.backend.generate.assert_called_once();self.c.command.assert_not_called()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM game_master_replies').fetchone()[0],'silent')

    def test_messages_during_generation_and_cooldown_are_processed_in_order(self):
        from concurrent.futures import Future
        self.tick()
        self.gm.pool.shutdown(wait=True)
        futures=[];contexts=[]
        def submit(fn,context):
            contexts.append(context);future=Future();futures.append(future);return future
        self.gm.pool=Mock();self.gm.pool.submit.side_effect=submit
        self.message('hi',key='first');self.tick()
        self.message('mb 1 n1?',key='second');self.message('nice map',key='third');self.tick(now=101)
        self.assertEqual(len(contexts),1)
        futures[0].set_result(None);self.tick(now=102)
        self.message('ready',key='fourth');self.tick(now=103)
        self.assertEqual(len(contexts),1)
        for index,now in enumerate((120,140,160),1):
            self.tick(now=now);futures[index].set_result(None);self.tick(now=now+1)
        self.assertEqual([x['respond_to']['text'] for x in contexts],['hi','mb 1 n1?','nice map','ready'])
        self.assertIn({'name':'Alex','text':'ready'},contexts[1]['recent_chat'])
        self.tick(now=200);self.assertEqual(len(contexts),4)
        self.c.command.assert_not_called()

    def test_held_or_changed_lobby_does_not_replay_queued_chat(self):
        for cause in ('hold','lobby','epoch','settings'):
            with self.subTest(cause=cause):
                self.gm.close();self.gm=GameMaster(self.c,Settings(),self.backend)
                self.obs['messages']=[];self.backend.reset_mock()
                self.tick();self.gm.next_request=200
                self.message('hi');self.tick(now=101)
                self.assertEqual(len(self.gm.inbox),1)
                if cause=='lobby':self.obs['lobby_id']='new-lobby'
                if cause=='epoch':self.raw['roster']['gameStartTimeRaw']='new-epoch'
                if cause=='settings':self.raw['roster']['settings']['maxPlayers']=6
                self.tick(enabled=cause!='hold',now=102);self.tick(now=201)
                self.backend.generate.assert_not_called()

    def test_format_request_reaches_model_with_full_lobby_policy(self):
        self.raw['roster']['settings']['maxPlayers']=4
        self.tick();self.message('mb 1 n1?');self.tick();self.gm.future.result(timeout=2)
        context=self.backend.generate.call_args.args[0]
        self.assertEqual(context['respond_to']['text'],'mb 1 n1?')
        self.assertEqual(context['hosting_policy'],{'required_players':4,'unanimous_early_start':True,'wait_for_full_lobby':False,
            'all_players_must_be_ready':True,'spectators_count_as_players':False})
        self.tick(now=101)
        self.c.command.assert_called_once()

    def test_spectator_question_includes_actual_host_role(self):
        self.raw['roster']['rows']=[
            {'memberIdRaw':1,'typeRaw':4,'teamRaw':'spectator','readyRaw':1},
            {'memberIdRaw':2,'typeRaw':1,'teamRaw':'b','readyRaw':0}]
        self.tick();self.message('Player17, you will spectator?');self.tick();self.gm.future.result(timeout=2)
        context=self.backend.generate.call_args.args[0]
        self.assertEqual(context['players'],[
            {'name':'Player17','is_host':True,'role':'spectator','team':'spectator','ready':True},
            {'name':'Alex','is_host':False,'role':'player','team':'b','ready':False}])
        self.assertNotIn('steam_id',json.dumps(context))

    def test_missing_role_is_unknown_not_assumed_spectator(self):
        self.launch()
        context=self.backend.generate.call_args.args[0]
        self.assertIsNone(context['players'][0]['role'])

    def test_schema_and_chat_limits(self):
        for value in ({'reply':True,'text':'/kick Alex'},{'reply':True,'text':'<c(red)>hi'},
                      {'reply':True,'text':'hi\nthere'},{'reply':True,'text':'http://example.com'},
                      {'reply':True,'text':'x'*129},{'reply':'yes','text':'hi'}, {'reply':True,'text':'hi','tool':'shell'}):
            with self.subTest(value=value),self.assertRaises(ValueError):validate_reply(value,120)
        self.assertIsNone(validate_reply({'reply':False,'text':''},120))

    def test_auth_and_process_configuration(self):
        with patch.dict('os.environ',{'OPENAI_API_KEY':'test-secret','CODEX_API_KEY':'test-secret'}):
            env=clean_environment();self.assertNotIn('OPENAI_API_KEY',env);self.assertNotIn('CODEX_API_KEY',env)
        with patch('game_master.executable',return_value='codex.exe'):
            args=command(Settings(),Path(self.tmp.name))
            self.assertIn('forced_login_method="chatgpt"',args)
            self.assertIn('--ignore-user-config',args);self.assertIn('read-only',args)
            with patch('game_master.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='Logged in using an API key',stderr='')):
                with self.assertRaisesRegex(RuntimeError,'ChatGPT'):check_login()

    def test_extension_discovery_without_path_prefers_newest_complete_install(self):
        home=Path(self.tmp.name)
        for version in ('1.9.0','1.10.0'):
            binary=home/'.vscode'/'extensions'/('openai.chatgpt-'+version)/'bin/windows-x86_64/codex.exe'
            binary.parent.mkdir(parents=True);binary.write_bytes(b'test fixture')
        (home/'.vscode/extensions/openai.chatgpt-99.0.0').mkdir()
        with patch.dict('os.environ',{'MOW_CODEX_EXE':''}),patch('game_master.shutil.which',return_value=None),patch('game_master.Path.home',return_value=home),patch('game_master.platform.machine',return_value='AMD64'):
            self.assertIn('openai.chatgpt-1.10.0',executable())
        with patch.dict('os.environ',{'MOW_CODEX_EXE':'missing-relative.exe'}):
            with self.assertRaisesRegex(RuntimeError,'absolute path'):executable()


if __name__=='__main__':unittest.main()
