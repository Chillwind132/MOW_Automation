import _test_paths  # Shared paths for direct runs and test discovery.
import copy
from contextlib import closing
import json
from pathlib import Path
import tempfile
import shutil
import subprocess
import unittest
from unittest.mock import Mock,patch

from lobby_social import LobbySocial,SocialStore,badge_tier,greeting,normalize_social,recorded_games
from test_friends_host import roster


class SocialTests(unittest.TestCase):
    def setUp(self):
        delay=patch('lobby_social.random.uniform',return_value=0)
        delay.start();self.addCleanup(delay.stop)
        self.raw=json.loads((_test_paths.ROOT/'tests/fixtures/lobby_social.json').read_text())
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'social.sqlite3'

    def controller(self):
        c=Mock(record_only=False)
        c.journal.path=self.path
        c.command.return_value={'probe':self.raw}
        return c

    def test_failed_poll_discards_previous_snapshot(self):
        c=self.controller();social=LobbySocial(c)
        with patch('lobby_social.time.monotonic',return_value=100):
            social.poll()
        self.assertIsNotNone(social.latest)
        c.command.side_effect=RuntimeError('UI probe time budget exceeded')
        with patch('lobby_social.time.monotonic',return_value=106):
            with self.assertRaises(RuntimeError):social.poll()
        self.assertIsNone(social.latest)
        c.command.reset_mock()
        social.greet_current()
        c.command.assert_not_called()

    def test_real_lobby_tooltips_bind_to_member_ids_and_chat_is_exact(self):
        obs=normalize_social(self.raw)
        self.assertEqual([(p['steam_id'],p['games_played'],p['badge_tier'],p['ranked_games_played']) for p in obs['players']],
            [('76561190000001022',1044,8,0),('76561190000001024',193,5,0)])
        self.assertTrue(any(m['text']=='Test123' and m['sender_name']=='Player17' for m in obs['messages']))
        self.assertTrue(all(m['sender_steam_id'] is None for m in obs['messages']))
        self.raw['roster']['rows'][1]['displayName']='Player17'
        self.assertEqual(normalize_social(self.raw)['players'][1]['games_played'],193)

    def test_unavailable_experience_is_not_zero_and_badges_have_native_boundaries(self):
        self.raw['members']=[]
        self.assertIsNone(normalize_social(self.raw)['players'][0]['games_played'])
        self.assertEqual([badge_tier(n) for n in [None,0,1,9,10,799,800,1499,1500,1999,2000]],
            [None,0,1,1,2,7,8,8,9,9,10])
        self.raw['roster']['rows'][0]['gamesPlayedRaw']=1044
        self.assertEqual(normalize_social(self.raw)['players'][0]['games_played'],1044)

    def test_repeated_observations_and_reconnect_do_not_duplicate_records(self):
        store=SocialStore(self.path);obs=normalize_social(self.raw)
        store.capture(obs);SocialStore(self.path).capture(obs)
        with closing(store.connect()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM player_experience').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lobby_chat').fetchone()[0],len(obs['messages']))
        self.assertTrue(store.claim(obs['lobby_id'],'steam','hello'))
        self.assertFalse(SocialStore(self.path).claim(obs['lobby_id'],'steam','hello'))

    def test_greet_remote_player_once_and_never_in_record_only(self):
        c=self.controller();social=LobbySocial(c);social.poll(announce=True)
        sends=[call for call in c.command.call_args_list if call.args[0]=='chat-greeting']
        self.assertEqual(len(sends),1)
        self.assertEqual(sends[0].kwargs['text'],greeting({'display_name':'Player07'}))
        c.command.reset_mock();LobbySocial(c).poll(announce=True)
        self.assertEqual(c.command.call_count,1)
        with closing(SocialStore(self.path).connect()) as db,db:db.execute('DELETE FROM lobby_greetings')
        c.record_only=True;c.command.reset_mock();LobbySocial(c).poll(announce=True)
        c.command.assert_called_once_with('probe',target='social')

    def test_busy_input_and_remote_host_do_not_send(self):
        for field in ('input_busy','remote_host'):
            c=self.controller();raw=copy.deepcopy(self.raw)
            if field=='input_busy':raw['input_busy']=True
            else:raw['roster']['hostMemberIdRaw']=3
            c.command.return_value={'probe':raw};LobbySocial(c).poll(announce=True)
            c.command.assert_called_once_with('probe',target='social')

    def test_uncertain_send_is_not_retried_after_restart(self):
        c=self.controller();c.command.side_effect=[{'probe':self.raw},RuntimeError('timeout')]
        with self.assertRaisesRegex(RuntimeError,'timeout'):LobbySocial(c).poll(announce=True)
        c.command.side_effect=None;c.command.reset_mock();LobbySocial(c).poll(announce=True)
        c.command.assert_called_once_with('probe',target='social')
        with closing(SocialStore(self.path).connect()) as db:
            self.assertEqual(db.execute('SELECT status FROM lobby_greetings').fetchone()[0],'unconfirmed')

    def test_poll_rate_and_rating_provider(self):
        c=self.controller();social=LobbySocial(c,lambda steam:{'value':1020,'provisional':True})
        with patch('lobby_social.time.monotonic',return_value=100):
            social.poll(announce=True);social.poll(announce=True)
        self.assertEqual(c.command.call_count,2)
        self.assertTrue(c.command.call_args.kwargs['text'].endswith('Games: 0. Rating: 1020 (provisional).'))
        player={'display_name':'<c(red)>Bob\n<>','games_played':1044}
        self.assertTrue(greeting(player).startswith('Hi Bob!'))
        self.assertNotIn('1044',greeting(player))
        self.assertTrue(greeting(player,{'value':1020.4,'provisional':True},games=2).endswith('Games: 2. Rating: 1020 (provisional).'))
        self.assertTrue(greeting(player,{'value':987.4,'provisional':True},games=1).endswith('Games: 1. Rating: 987 (provisional).'))
        self.assertTrue(greeting(player,{'value':1200,'provisional':False},games=8).endswith('Games: 8. Rating: 1200.'))
        self.assertTrue(greeting(player,games=1).endswith('Games: 1. Rating: unrated.'))
        text=greeting({'display_name':'😀'*40},{'value':1200,'provisional':True},games=1000)
        self.assertLessEqual(len(text.encode('utf-16-le'))//2,256)
        self.assertTrue(greeting(player).endswith('Games: 0. Rating: unrated.'))

    def test_definite_rejection_retries_only_after_same_lobby_entry(self):
        from modules.live_game_data import Participation
        c=self.controller()
        error=RuntimeError('Greeting recipient left the lobby')
        error.command_result={'ok':False,'mutationStarted':False}
        c.command.side_effect=[{'probe':self.raw},error]
        with patch('lobby_social.time.time',return_value=100):
            with self.assertRaises(RuntimeError):LobbySocial(c).poll(announce=True)
        obs=normalize_social(self.raw);lobby=obs['lobby_id'];steam=obs['players'][1]['steam_id']
        store=SocialStore(self.path)
        with closing(store.connect()) as db:
            self.assertEqual(db.execute('SELECT status FROM lobby_greetings').fetchone()[0],'not_sent')
        tracker=Participation(self.path)
        for entered,event_lobby,flags,page in [(99,lobby,1,0xe2b2cc),(110,'other',1,0xe2b2cc),
                                              (120,lobby,2,0xe2b2cc),(130,lobby,1,0xe2ae58)]:
            with patch('modules.live_game_data.participation.time.time',return_value=entered):
                tracker.native({'steam_id':steam,'lobby_id':event_lobby,'flags':flags,'page_vtable':page})
            self.assertFalse(store.renew_after_game_rejoin(lobby,steam,0))
        with patch('modules.live_game_data.participation.time.time',return_value=150):
            tracker.native({'steam_id':steam,'lobby_id':lobby,'flags':1,'page_vtable':0xe2b2cc})
        c.command.side_effect=None;c.command.reset_mock()
        LobbySocial(c).poll(announce=True)
        self.assertEqual(c.command.call_args.args,('chat-greeting',))
        c.command.reset_mock();LobbySocial(c).poll(announce=True)
        c.command.assert_called_once_with('probe',target='social')
        with closing(store.connect()) as db:
            self.assertEqual(db.execute('SELECT status FROM lobby_greeting_history').fetchall(),[('not_sent',)])

    def test_possible_mutation_stays_unconfirmed(self):
        c=self.controller();error=RuntimeError('native failure')
        error.command_result={'ok':False,'mutationStarted':True}
        c.command.side_effect=[{'probe':self.raw},error]
        with self.assertRaises(RuntimeError):LobbySocial(c).poll(announce=True)
        c.command.side_effect=None;c.command.reset_mock();LobbySocial(c).poll(announce=True)
        c.command.assert_called_once_with('probe',target='social')

    def test_recorded_games_counts_saved_matches_once_and_excludes_spectators(self):
        from test_match_ratings import fixture
        store=SocialStore(self.path)
        first=fixture();steam=first['metadata']['participants'][0]['steam_id']
        spectator=fixture('spectator');spectator['metadata']['participants'][0]['role']='spectator'
        ai=fixture('ai');ai['metadata']['participants'][0]['controller_kind']='ai'
        with closing(store.connect()) as db,db:
            db.execute('CREATE TABLE match_journal (match_id TEXT, snapshot_json TEXT)')
            db.execute('CREATE TABLE completion_captures (match_id TEXT, normalized_json TEXT)')
            db.execute('CREATE TABLE matches (match_id TEXT, observation_json TEXT)')
            db.execute('CREATE TABLE results (match_id TEXT, normalized_json TEXT)')
            for record in (first,spectator,ai,fixture('unfinished')):
                db.execute('INSERT INTO match_journal VALUES (?,?)',(record['id'],json.dumps(record['metadata'])))
                if record['id']!='unfinished':
                    db.execute('INSERT INTO completion_captures VALUES (?,?)',(record['id'],json.dumps(record['finish'])))
            for record in (first,fixture('second')):
                db.execute('INSERT INTO matches VALUES (?,?)',(record['id'],json.dumps(record['metadata'])))
                db.execute('INSERT INTO results VALUES (?,?)',(record['id'],json.dumps(record['finish'])))
        self.assertEqual(recorded_games(self.path,steam),2)
        self.assertEqual(recorded_games(self.path,'unknown'),0)
        c=self.controller()
        with patch('lobby_social.recorded_games',return_value=2):
            LobbySocial(c,lambda steam:{'value':1020,'provisional':True}).poll(announce=True)
        self.assertTrue(c.command.call_args.kwargs['text'].endswith('Games: 2. Rating: 1020 (provisional).'))

    def rejoin_store(self, entered=300, lobby='lobby', page=0xe2b2cc):
        from modules.live_game_data import Participation
        store=SocialStore(self.path)
        with patch('lobby_social.time.time',return_value=100):
            store.claim('lobby','steam',greeting({'display_name':'Bob'},games=0))
            store.finish('lobby','steam','unconfirmed')
        tracker=Participation(self.path)
        with patch('modules.live_game_data.participation.time.time',return_value=entered):
            tracker.native({'steam_id':'steam','lobby_id':lobby,'flags':1,'page_vtable':page})
        return store

    def test_fast_post_game_rejoin_renews_once_with_updated_rating(self):
        store=self.rejoin_store()
        with patch('lobby_social.latest_recorded_game_end',return_value=200):
            # Replay import has not finished yet: keep the old claim.
            self.assertFalse(store.renew_after_game_rejoin('lobby','steam',0))
            self.assertTrue(store.renew_after_game_rejoin('lobby','steam',1))
        text=greeting({'display_name':'Bob'},{'value':1042.3,'provisional':True},games=1)
        self.assertTrue(text.endswith('Games: 1. Rating: 1042 (provisional).'))
        self.assertTrue(store.claim('lobby','steam',text))
        # A restart and another reconnect cannot retry an uncertain send this game.
        self.assertFalse(SocialStore(self.path).renew_after_game_rejoin('lobby','steam',1))
        with closing(store.connect()) as db:
            self.assertEqual(db.execute('SELECT status FROM lobby_greeting_history').fetchall(),[('unconfirmed',)])

    def test_rejoin_must_follow_completion_in_the_same_lobby(self):
        for entered,lobby,page in [(150,'lobby',0xe2b2cc),(300,'other',0xe2b2cc),(300,'lobby',0xe2ae58)]:
            with self.subTest(entered=entered,lobby=lobby,page=page):
                store=self.rejoin_store(entered,lobby,page)
                with patch('lobby_social.latest_recorded_game_end',return_value=200):
                    self.assertFalse(store.renew_after_game_rejoin('lobby','steam',1))
                with closing(store.connect()) as db,db:
                    db.execute('DELETE FROM participation_events')

    def test_completed_game_without_rejoin_does_not_repeat_greeting(self):
        store=SocialStore(self.path)
        store.claim('lobby','steam',greeting({'display_name':'Bob'},games=0))
        self.assertFalse(store.renew_after_game_rejoin('lobby','steam',1))

    def test_greetings_use_requested_text_without_separate_announcements(self):
        c=self.controller();social=LobbySocial(c)
        with patch('lobby_social.time.monotonic',return_value=100):
            social.poll(announce=True)
        first=c.command.call_args.kwargs['text']
        with closing(social.store.connect()) as db,db:
            db.execute('DELETE FROM lobby_greetings')
        with patch('lobby_social.time.monotonic',return_value=106):
            social.greet_current()
        second=c.command.call_args.kwargs['text']
        self.assertEqual(first,second)
        self.assertTrue(all(call.args[0] in ('probe','chat-greeting') for call in c.command.call_args_list))
        source=(_test_paths.ROOT/'headless/friends_host.py').read_text()
        self.assertNotIn('social.ready_status(',source)

    def test_greeting_waits_without_blocking(self):
        c=self.controller();social=LobbySocial(c)
        with patch('lobby_social.random.uniform',return_value=3) as delay:
            with patch('lobby_social.time.monotonic',return_value=100):social.poll(announce=True)
            self.assertEqual(c.command.call_count,1)
            delay.assert_called_once_with(1,3)
            with patch('lobby_social.time.monotonic',return_value=102):social.greet_current()
            self.assertEqual(c.command.call_count,1)
            with patch('lobby_social.time.monotonic',return_value=103):social.greet_current()
            self.assertEqual(c.command.call_args.args,('chat-greeting',))
        self.assertTrue(greeting({'display_name':'Alex'}).startswith('Hi Alex!'))

    @unittest.skipUnless(shutil.which('node'),'Node required for native race guard')
    def test_native_departed_recipient_rejected_before_touching_input(self):
        source=(_test_paths.ROOT/'headless/headless_host.js').read_text()
        send=source[source.index('function sendLobbyChat('):source.index('function servicesProbe(')]
        script=send+'''
        function lobbyProbe(){return {steamLobbyId:'lobby',localMemberIdRaw:1,hostMemberIdRaw:1,rows:[]}}
        function lobbySocialContext(){throw Error('input must not be touched')}
        let rejected=false;
        try{sendLobbyChat({lobbyId:'lobby',steamId:'123',text:'Hi'})}
        catch(e){rejected=String(e).includes('Greeting recipient left the lobby')}
        if(!rejected)throw Error('Missing recipient was not rejected before input access');
        '''
        subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)

    @unittest.skipUnless(shutil.which('node'),'Node required for native race guard')
    def test_native_announcement_rechecks_readiness_before_touching_input(self):
        source=(_test_paths.ROOT/'headless/headless_host.js').read_text()
        send=source[source.index('function sendLobbyChat('):source.index('function servicesProbe(')]
        approval=source[source.index('function rosterApproval('):source.index('function friendsReady(')]
        r=roster();r['steamLobbyId']='lobby'
        script=approval+send+'\nconst r='+json.dumps(r)+''';
        function lobbyProbe(){return r}
        function lobbySocialContext(){throw Error('input must not be touched')}
        const options={lobbyId:'lobby',approval:rosterApproval(r),text:'All ready.'};
        r.rows[1].readyRaw=0;
        let rejected=false;
        try{sendLobbyChat(options,true)}catch(e){rejected=String(e).includes('announcements are disabled')}
        if(!rejected)throw Error('Stale readiness was accepted');
        '''
        subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)


if __name__=='__main__':unittest.main()
