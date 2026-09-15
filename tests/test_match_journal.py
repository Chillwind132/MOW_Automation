"""Offline recovery faults; these tests do not establish live engine behavior."""
import _test_paths  # Shared paths for direct runs and test discovery.
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from match_journal import Journal, ProcessLock, fingerprint, reconcile
from match_metadata import participants, controlled_ai


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path=Path(self.temporary.name)/'test.sqlite3'
        self.journal=Journal(self.path)
        self.identity={'pid':12,'creation_filetime':'100','sha256':'test'}
        self.process,self.session=self.journal.register(self.identity,{'lobby':'one'})

    def test_completed_replay_recovers_hidden_results_only_with_current_identity(self):
        mid=self.journal.new_match(self.session,{'native_game_start_time':'epoch'})
        self.journal.transition(mid,'lobby','results_available',{})
        observed=dict(process_key=self.process,session_id=self.session,native_game_start_time='epoch',
                      lobby_loaded=True,loaded=False,replay_saved=True,results_visible=False)
        def decision(o):return reconcile(self.journal.inspect(self.process),self.process,self.session,o)['status']
        self.assertEqual(decision(observed),'results_available')
        for key,val in [('native_game_start_time','other'),('session_id','other'),
                        ('lobby_loaded',False),('replay_saved',False)]:
            self.assertEqual(decision(dict(observed,**{key:val})),'needs_reconciliation')
        self.journal.request(self.process,mid,'exit-completed',{})
        self.assertEqual(decision(observed),'needs_reconciliation')

    def test_hidden_statistics_require_complete_durable_sequence_and_current_identity(self):
        match = self.journal.new_match(self.session, {})
        self.journal.transition(match, 'lobby', 'results_available',
                                {'match_id': match, 'native_game_start_time': 'epoch'})
        self.journal.save_completion(match, {}, {'match_id': match, 'native_game_start_time': 'epoch'}, {})
        requests = []
        for action in ('exit-completed', 'results'):
            request = self.journal.request(self.process, match, action, {'controlled': {'epoch': 'epoch'}})
            self.journal.command_state(request, 'executing')
            self.journal.command_state(request, 'observed-complete',
                {'ok': True, 'state': {'session': 'native-session', 'card': 'native-card'}, 'probe': {'nodes': []}})
            requests.append(request)
        observation = dict(process_key=self.process, session_id=self.session,
            native_game_start_time='epoch', lobby_loaded=True, loaded=False, results_visible=False,
            session='native-session', card='native-card')
        def recover(value):
            return self.journal.archived_completion_results(self.process, self.session, match, value)
        raw, proof = recover(observation)
        self.assertEqual(raw['nodes'], [])
        self.assertEqual(proof['results_request_id'], requests[1])
        self.assertEqual(self.journal.inspect(self.process)['matches'][0]['state'], 'results_available')
        for field, value in [('process_key', 'other'), ('session_id', 'other'),
                ('native_game_start_time', 'other'), ('lobby_loaded', False), ('loaded', True),
                ('results_visible', True), ('card', 'other'), ('session', 'other')]:
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                recover(dict(observation, **{field: value}))
        # Fail closed even when an earlier good capture remains in the journal.
        for action in ('results', 'exit-completed'):
            request = self.journal.request(self.process, match, action, {})
            self.journal.command_state(request, 'executing')
            with self.assertRaises(RuntimeError):
                recover(observation)
            self.journal.command_state(request, 'failed', {'ok': False, 'mutationStarted': False})
            with self.assertRaises(RuntimeError):
                recover(observation)

    def test_hidden_statistics_reject_missing_terminal_capture_or_normal_exit(self):
        match = self.journal.new_match(self.session, {})
        self.journal.transition(match, 'lobby', 'results_available',
                                {'match_id': match, 'native_game_start_time': 'epoch'})
        observation = dict(process_key=self.process, session_id=self.session,
            native_game_start_time='epoch', lobby_loaded=True, loaded=False, results_visible=False,
            session='native-session', card='native-card')
        with self.assertRaisesRegex(RuntimeError, 'durable completion'):
            self.journal.archived_completion_results(self.process, self.session, match, observation)

    def test_pid_reuse_is_a_new_process_and_session(self):
        process,session=self.journal.register(dict(self.identity,creation_filetime='101'),{'lobby':'one'})
        self.assertNotEqual(process,self.process)
        self.assertNotEqual(session,self.session)
        self.assertEqual(self.journal.register(self.identity,{'lobby':'one'}),(self.process,self.session))

    def test_lost_acknowledgment_blocks_replay_and_new_controller(self):
        match=self.journal.new_match(self.session,{'roster':'test'})
        request=self.journal.request(self.process,match,'start',{},'request-one')
        self.journal.command_state(request,'executing')
        reopened=Journal(self.path)
        for request_id in ['request-one','request-two']:
            with self.assertRaises(RuntimeError):
                reopened.request(self.process,match,'start',{},request_id)
        decision=reconcile(reopened.inspect(self.process),self.process,self.session,
                           {'process_key':self.process,'session_id':self.session,'loaded':True})
        self.assertEqual(decision['status'],'needs_reconciliation')

    def test_out_of_order_commands_and_lifecycle_are_rejected(self):
        match=self.journal.new_match(self.session,{})
        request=self.journal.request(self.process,match,'start',{})
        with self.assertRaises(RuntimeError):
            self.journal.command_state(request,'observed-complete')
        self.journal.transition(match,'lobby','start_requested',{})
        with self.assertRaises(RuntimeError):
            self.journal.transition(match,'lobby','playing',{})
        with self.assertRaises(RuntimeError):
            self.journal.new_match(self.session,{})

    def test_reattach_observes_same_match_and_refuses_stale_results(self):
        match=self.journal.new_match(self.session,{})
        self.journal.transition(match,'lobby','playing',{'match_id':match,'native_game_start_time':'epoch-one','fixture':True})
        record=self.journal.inspect(self.process)
        observation={'process_key':self.process,'session_id':self.session,'loaded':True,'native_game_start_time':'epoch-one'}
        self.assertEqual(reconcile(record,self.process,self.session,observation)['match_id'],match)
        observation.update(loaded=False,results_visible=True)
        self.assertFalse(reconcile(record,self.process,self.session,observation)['may_mutate'])
        observation['session_id']='reused-address-different-session'
        self.assertEqual(reconcile(record,self.process,self.session,observation)['status'],'needs_reconciliation')

    def test_lock_excludes_another_attachment_and_releases(self):
        lock=ProcessLock(self.temporary.name,self.identity)
        try:
            with self.assertRaisesRegex(RuntimeError,'Another controller'):
                ProcessLock(self.temporary.name,self.identity)
        finally:
            lock.close()
        ProcessLock(self.temporary.name,self.identity).close()

    def test_migration_backs_up_and_preserves_legacy_rows(self):
        legacy=Path(self.temporary.name)/'legacy.sqlite3'
        with closing(sqlite3.connect(legacy)) as db, db:
            db.execute('CREATE TABLE matches(match_id TEXT PRIMARY KEY, observation_json TEXT NOT NULL)')
            db.execute('INSERT INTO matches VALUES (?,?)',('old','{"trigger":"host_requested_quit"}'))
        Journal(legacy)
        with closing(sqlite3.connect(legacy)) as db:
            self.assertEqual(db.execute('SELECT * FROM matches').fetchone(),('old','{"trigger":"host_requested_quit"}'))
        backups=list(legacy.parent.glob('legacy.sqlite3.pre-journal-*.bak'))
        self.assertEqual(len(backups),1)
        with closing(sqlite3.connect(backups[0])) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM matches').fetchone()[0],1)


class ParticipantTests(unittest.TestCase):
    def setUp(self):
        self.roster=json.loads((_test_paths.ROOT/'tests/fixtures/ai_assignment.json').read_text())['after']

    def test_real_ai_has_no_steam_id_and_distinct_slot_identity(self):
        result=participants(self.roster,'match-a')
        ai=next(p for p in result if p['controller_kind']=='ai')
        self.assertIsNone(ai['steam_id'])
        self.assertEqual(ai['starting_team'],'b')
        self.assertEqual(ai['ai_difficulty'],'normal')
        self.assertEqual(ai['participant_key'],'ai:match-a:4:1')

    def test_duplicate_names_and_slot_reuse_do_not_merge(self):
        first=participants(self.roster,'match-a')
        ai=self.roster['rows'][1]
        self.roster['rows'].append(dict(ai,memberIdRaw=99))
        self.roster['slots'][1]['memberIdRaw']=99
        result=participants(self.roster,'match-a',first)
        self.assertEqual(len({p['participant_key'] for p in result}),3)
        self.assertEqual(result[1]['participant_key'],first[1]['participant_key'])
        ai['memberIdRaw']=100
        self.roster['slots'][3]['memberIdRaw']=100
        changed=participants(self.roster,'match-a',result)
        self.assertEqual(changed[1]['participant_key'],'ai:match-a:4:2')
        self.assertTrue(controlled_ai(self.roster))
        self.roster['rows'].append(dict(ai,typeRaw=1,memberIdRaw=200))
        self.assertFalse(controlled_ai(self.roster))


if __name__=='__main__':
    unittest.main()
