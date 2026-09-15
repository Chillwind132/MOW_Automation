import _test_paths
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import http.client
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from match_adjudication import ConflictError,read_adjudications,save_adjudication
from match_ratings import stored,refresh
from match_review import load_matches,write_review
from match_review_service import create_service
from test_match_ratings import fixture


class DecisionFixture:
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.path=self.root/'test.sqlite3'
        r=fixture('pending');self.metadata=r['metadata']
        self.metadata.update(trigger='returned_to_lobby_without_observed_natural_completion',rating_eligible=False,rating_profile=None)
        self.result=r['finish'];self.result['engine_outcome']=None
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE matches(match_id TEXT PRIMARY KEY,observation_json TEXT)')
            db.execute('CREATE TABLE results(match_id TEXT PRIMARY KEY,normalized_json TEXT,raw_json TEXT)')
            db.execute('INSERT INTO matches VALUES (?,?)',('pending',json.dumps(self.metadata)))
            db.execute('INSERT INTO results VALUES (?,?,?)',('pending',json.dumps(self.result),'original native evidence'))

    def save(self, **changes):
        args=dict(match_id='pending',winning_team='a',reason='Team B conceded.',robz=True)
        args.update(changes)
        return save_adjudication(self.path,**args)

    def captures(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT * FROM matches').fetchall(),db.execute('SELECT * FROM results').fetchall()

class DecisionTests(DecisionFixture,unittest.TestCase):
    def test_archived_final_vp_is_shared_by_review_and_rating(self):
        self.metadata.update(effective_settings={},trigger='normal_completion_observed',rating_eligible=True,
                             rating_profile={'pool':'robz-battle-zones','source':'operator_cli_declaration'})
        self.result.update(source='persisted_replay_battleInfoTotal',engine_outcome={'winning_team':'a'},
                           replay={'ss_sha256':'a'*64})
        archive=self.root/'replays'/('a'*64)/'replay.ss'
        archive.parent.mkdir(parents=True)
        archive.write_text('{settings {scoreFinal 200}}',encoding='utf-8')
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE matches SET observation_json=?',(json.dumps(self.metadata),))
            db.execute('UPDATE results SET normalized_json=?',(json.dumps(self.result),))
        self.assertEqual(load_matches(self.path)[0]['winner'],'a')
        self.assertEqual(refresh(self.path)['matches']['pending']['status'],'rated')

    def test_early_replay_flag_is_undetermined_and_opposite_manual_winner_is_allowed(self):
        self.result.update(source='persisted_replay_battleInfoTotal',engine_outcome={'winning_team':'a'})
        for row in self.result['rows']:
            if row['kind']=='team':row['fields']['victory_points']['values_in_display_order']=[7 if row['row_id']=='tb' else 0]
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE results SET normalized_json=?',(json.dumps(self.result),))
        before=self.captures()
        self.assertIsNone(load_matches(self.path)[0]['winner'])
        self.assertEqual(refresh(self.path)['matches']['pending']['status'],'no_confirmed_winner')
        self.assertEqual(self.save(winning_team='b')['rating']['status'],'rated')
        review=load_matches(self.path)[0]
        self.assertEqual(review['winner'],'b')
        self.assertEqual(review['outcome_source'],'explicit_user_confirmation')
        self.assertEqual(self.captures(),before)

    def test_reason_outcome_and_rating_are_durable_without_rewriting_evidence(self):
        before=self.captures();result=self.save()
        self.assertEqual(result['rating']['status'],'rated')
        self.assertEqual(self.captures(),before)
        review=load_matches(self.path)[0]
        self.assertEqual(review['winner'],'a')
        self.assertEqual(review['metadata']['operator_adjudication']['reason'],'Team B conceded.')
        self.assertEqual(self.save(),result)
        self.assertEqual(refresh(self.path),stored(self.path))
        self.assertTrue(all(p['games']==1 for p in stored(self.path)['players'].values()))

    def test_empty_reason_invalid_team_and_unknown_match_cannot_write(self):
        for change in ({'reason':'  '},{'reason':'x'*2001},{'reason':None},{'winning_team':'c'},{'match_id':'missing'},{'robz':'true'}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.save(**change)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(read_adjudications(db),{})

    def test_duplicate_and_conflicting_concurrent_submissions(self):
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:self.save(),range(2)))
        self.assertEqual(results[0],results[1])
        for changes in ({'winning_team':'b'},{'reason':'Different reason'},{'robz':False}):
            with self.assertRaises(ConflictError):self.save(**changes)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(len(read_adjudications(db)),1)

    def test_failed_rating_publication_rolls_back_decision_and_preserves_head(self):
        old=refresh(self.path)
        with patch('match_ratings.evaluate',side_effect=RuntimeError('failed replay')):
            with self.assertRaises(RuntimeError):self.save()
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(read_adjudications(db),{})
        self.assertEqual(stored(self.path),old)

    def test_native_completion_hidden_by_incomplete_lobby_export_cannot_be_overridden(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE match_journal(match_id TEXT,snapshot_json TEXT)')
            db.execute('CREATE TABLE completion_captures(match_id TEXT,normalized_json TEXT,captured_at REAL)')
            db.execute('INSERT INTO match_journal VALUES (?,?)',('pending',json.dumps(self.metadata)))
            db.execute('INSERT INTO completion_captures VALUES (?,?,?)',('pending',json.dumps(fixture()['finish']),1))
        with self.assertRaises(ConflictError):self.save()

    def test_unconfirmed_mod_can_record_winner_without_rating(self):
        result=self.save(robz=False)
        self.assertEqual(result['rating']['status'],'robz_not_confirmed')
        self.assertEqual(load_matches(self.path)[0]['winner'],'a')
        self.assertEqual(stored(self.path)['players'],{})

    def test_later_conflicting_native_result_is_not_presented_as_user_confirmation(self):
        self.save()
        self.result['engine_outcome']={'winning_team':'b'}
        for row in self.result['rows']:
            if row['kind']=='team':row['fields']['victory_points']['values_in_display_order']=[200 if row['row_id']=='tb' else 0]
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE results SET normalized_json=?',(json.dumps(self.result),))
        self.assertEqual(refresh(self.path)['matches']['pending']['status'],'conflicting_captures')
        review=load_matches(self.path)[0]
        self.assertEqual(review['winner'],'b')
        self.assertEqual(review['outcome_source'],'native_result')
        self.assertEqual(review['metadata']['operator_adjudication']['winning_team'],'a')

    def test_progress_only_decision_does_not_invent_result_identities(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('DELETE FROM results');db.execute('DELETE FROM matches')
            db.execute('CREATE TABLE match_snapshots(sequence INTEGER,match_id TEXT,recorded_at REAL,sampled_at REAL,reason TEXT,snapshot_json TEXT)')
            snapshot=dict(metadata=self.metadata,sample=None,per_player_statistics_status='unavailable')
            db.execute('INSERT INTO match_snapshots VALUES (1,?,?,?,?,?)',('pending',2,None,'observer_stopped',json.dumps(snapshot)))
        result=self.save()
        self.assertEqual(result['rating']['status'],'incomplete_result_identities')
        self.assertEqual(load_matches(self.path)[0]['winner'],'a')
        self.assertEqual(self.captures(),([],[]))


class ServiceTests(DecisionFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.service=create_service(self.path,self.root/'review.html')
        thread=threading.Thread(target=self.service.serve_forever,kwargs={'poll_interval':0.01})
        thread.start()
        def cleanup():
            self.service.shutdown();self.service.server_close();thread.join(timeout=5)
        self.addCleanup(cleanup)

    def request(self, method, path, body=None, headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.service.server_port,timeout=5)
        try:
            connection.request(method,path,body,headers or {})
            response=connection.getresponse()
            return response.status,response.read().decode('utf-8')
        finally:connection.close()

    def post(self, headers=None, **changes):
        body=dict(match_id='pending',winning_team='a',reason='Team B conceded.',robz=True);body.update(changes)
        valid={'Origin':self.service.origin,'X-Local-Token':self.service.token,'Content-Type':'application/json'}
        if headers is not None:valid=headers
        return self.request('POST','/api/adjudications',json.dumps(body),valid)

    def test_page_policy_allows_embedded_rank_images(self):
        connection=http.client.HTTPConnection('127.0.0.1',self.service.server_port,timeout=5)
        try:
            connection.request('GET','/match_review.html')
            response=connection.getresponse()
            policy=response.getheader('Content-Security-Policy')
            response.read()
        finally:connection.close()
        directives=dict((parts[0],parts[1:]) for part in policy.split(';') if (parts:=part.split()))
        self.assertEqual(directives['img-src'],['data:'])
        self.assertEqual(directives['default-src'],["'none'"])

    def test_http_page_save_and_manual_refresh(self):
        status,page=self.request('GET','/match_review.html')
        self.assertEqual(status,200)
        self.assertIn(self.service.token,page)
        self.assertNotIn(self.service.token,(self.root/'review.html').read_text(encoding='utf-8'))
        status,body=self.post();self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['matches'][0]['winner'],'a')
        self.assertEqual(self.post()[0],200)
        self.assertEqual(self.post(winning_team='b')[0],409)
        status,body=self.request('GET','/api/matches')
        self.assertEqual(json.loads(body)['matches'][0]['metadata']['operator_adjudication']['reason'],'Team B conceded.')

    def test_cross_origin_missing_token_wrong_host_and_unknown_routes_are_rejected(self):
        for headers in ({},{'Origin':'https://example.com','X-Local-Token':self.service.token},
                        {'Origin':self.service.origin,'X-Local-Token':'wrong'}):
            self.assertEqual(self.post(headers=headers)[0],403)
        self.assertEqual(self.request('GET','/',headers={'Host':'example.com'})[0],403)
        self.assertEqual(self.request('GET','/../../data/rankbot.sqlite3')[0],404)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(read_adjudications(db),{})

    def test_json_limits_and_reason_validation(self):
        self.assertEqual(self.post(reason=' ')[0],400)
        headers={'Origin':self.service.origin,'X-Local-Token':self.service.token,'Content-Type':'application/json'}
        self.assertEqual(self.request('POST','/api/adjudications','{',headers)[0],400)
        self.assertEqual(self.request('POST','/api/adjudications','x'*17000,headers)[0],413)

    @unittest.skipUnless(shutil.which('node'),'Node required for review script syntax')
    def test_rendered_javascript_and_reason_escaping(self):
        self.save(reason='</script><script>bad()</script>')
        _,page=self.request('GET','/')
        self.assertNotIn('</script><script>bad()',page)
        script=re.findall(r'<script>(.*?)</script>',page,re.S)[0]
        path=self.root/'review.js';path.write_text(script,encoding='utf-8')
        subprocess.run(['node','--check',str(path)],check=True,capture_output=True)

    @unittest.skipUnless(shutil.which('node'),'Node required for review interaction')
    def test_page_button_sends_reason_and_displays_saved_outcome(self):
        self.metadata['rating_profile']={'pool':'robz-battle-zones','source':'operator_cli_declaration'}
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE matches SET observation_json=?',(json.dumps(self.metadata),))
        _,page=self.request('GET','/')
        path=self.root/'page.html';path.write_text(page,encoding='utf-8')
        harness=_test_paths.ROOT/'tests/fixtures/review_dom_harness.js'
        subprocess.run(['node',str(harness),str(path),self.service.origin],check=True,capture_output=True,timeout=15)
        with closing(sqlite3.connect(self.path)) as db:
            decision=read_adjudications(db)['pending']
        self.assertEqual(decision['winning_team'],'a')
        self.assertEqual(decision['reason'],'Team B conceded in the UI test.')
        self.assertEqual(stored(self.path)['matches']['pending']['status'],'rated')


if __name__=='__main__':unittest.main()
