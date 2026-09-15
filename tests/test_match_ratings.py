import _test_paths  # Shared paths for direct runs and test discovery.
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from match_ratings import POOL, classify, display, evaluate, read_inputs, refresh, stored, update
from lobby_social import greeting, LobbySocial
from match_review import load_matches


def fixture(mid='one', timestamp=1):
    people = [dict(steam_id='7656119800000000'+str(i), participant_key='steam:7656119800000000'+str(i),
                   role='participant', controller_kind='remote_human', starting_team=t)
              for i,t in [(1,'a'), (2,'b')]]
    rows = [dict(kind='player', steam_id=p['steam_id'], participant_key=p['participant_key'],
                 controller_kind=p['controller_kind'], fields={'score':{'values_in_display_order':[10]}}) for p in people]
    rows[1:1] = [dict(kind='team',row_id='t'+team,fields={'victory_points':{'values_in_display_order':[vp]}}) for team,vp in [('a',200),('b',0)]]
    return dict(id=mid, metadata=dict(created_at=timestamp, participants=people,effective_settings={'victoryPoints':200},
                map='multi/desert:battle_zones', rating_profile=dict(pool=POOL, source='operator_cli_declaration')),
                finish=dict(engine_outcome={'winning_team':'a'}, rows=rows))


class CoreTests(unittest.TestCase):
    def test_profile_requires_explicit_run_declaration(self):
        from match_ratings import capture_profile
        class Controller:pass
        c=Controller()
        self.assertIsNone(capture_profile(c))
        c.rating_profile=POOL
        self.assertEqual(capture_profile(c),{'pool':POOL,'source':'operator_cli_declaration'})

    def test_equal_newcomers_reference(self):
        prob, changes = update({'a':['x'], 'b':['y']}, {}, 'a')
        self.assertEqual(prob, .5)
        self.assertAlmostEqual(changes['x']['after']['mu'],29.205473176557785,10)
        self.assertAlmostEqual(changes['x']['after']['sigma'],7.194816484813345,10)
        # Analytic independent reference: half-normal difference moments.
        variance=(25/3)**2+(25/300)**2
        c2=2*(variance+(25/6)**2)
        self.assertAlmostEqual(changes['x']['after']['mu'],25+variance/math.sqrt(c2)*math.sqrt(2/math.pi),12)
        self.assertAlmostEqual(changes['x']['after']['sigma'],math.sqrt(variance*(1-variance/c2*2/math.pi)),12)
        self.assertLess(changes['x']['after']['sigma'],25/3)
        self.assertAlmostEqual(changes['x']['after']['mu']+changes['y']['after']['mu'],50)

    def test_team_order_identity_invariance(self):
        teams={'a':['1','2'],'b':['3','4']}
        p,a=update(teams,{},'b')
        q,b=update({t:list(reversed(ids)) for t,ids in teams.items()},{},'b')
        self.assertEqual((p,a),(q,b))
        q,b=update({'a':teams['b'],'b':teams['a']},{},'a')
        for s in a:self.assertEqual(a[s]['after'],b[s]['after'])

    def test_extreme_upset_stays_finite(self):
        for difference in (100,1000,100000):
            _,r=update({'a':['1'],'b':['2']},{'1':display(difference,1),'2':display(-difference,1)},'b')
            self.assertTrue(all(math.isfinite(x['after']['mu']) and x['after']['sigma']>0 for x in r.values()))

    def test_no_score_bonus(self):
        a=fixture();b=copy.deepcopy(a)
        b['finish']['rows'][0]['fields']['score']['values_in_display_order']=[999999]
        self.assertEqual(evaluate([a])['players'],evaluate([b])['players'])

    def test_exclusions(self):
        mutations=[lambda r:r['finish'].update(engine_outcome=None),
                   lambda r:r['metadata'].pop('rating_profile'),
                   lambda r:r['metadata'].update(map='multi/map:combat'),
                   lambda r:r['metadata'].update(start_observation='attached_in_progress'),
                   lambda r:r['metadata']['participants'][0].update(controller_kind='ai'),
                   lambda r:r['metadata']['participants'][0].update(starting_team='b'),
                   lambda r:r['finish']['rows'].pop(),
                   lambda r:r['finish']['rows'][0].update(participant_key='wrong')]
        for mutation in mutations:
            r=fixture();mutation(r)
            self.assertNotEqual(classify(r)[0],'rated')
            self.assertFalse(evaluate([r])['players'])

    def test_conflicting_finish_and_lobby_quarantined(self):
        r=fixture();r['lobby']=copy.deepcopy(r['finish']);r['lobby_metadata']=r['metadata']
        self.assertEqual(classify(r)[0],'rated')
        r['lobby']['rows'][0]['fields']['score']['values_in_display_order']=[11]
        self.assertEqual(classify(r)[0],'conflicting_captures')

    def test_team_change_excluded(self):
        r=fixture();r['finish_roster']={'slots':[]}
        self.assertEqual(classify(r)[0],'changed_or_unresolved_participation')

    def test_explicit_adjudication_of_early_exit_retains_identity_guards(self):
        r=fixture()
        r['lobby']=r.pop('finish');r['lobby']['engine_outcome']=None
        r['metadata'].update(trigger='returned_to_lobby_without_observed_natural_completion',
                             rating_profile=None,rating_eligible=False)
        r['metadata']['operator_adjudication']=dict(source='explicit_user_confirmation',
            match_id=r['id'],winning_team='a',pool=POOL)
        self.assertEqual(classify(r)[0],'rated')
        self.assertEqual(classify(r)[1]['outcome_source'],'explicit_user_confirmation')
        for change in ('pool','match_id'):
            invalid=copy.deepcopy(r);invalid['metadata']['operator_adjudication'][change]='wrong'
            self.assertNotEqual(classify(invalid)[0],'rated')
        conflict=copy.deepcopy(r);conflict['lobby']['engine_outcome']={'winning_team':'b'}
        for row in conflict['lobby']['rows']:
            if row['kind']=='team':row['fields']['victory_points']['values_in_display_order']=[200 if row['row_id']=='tb' else 0]
        self.assertEqual(classify(conflict)[0],'conflicting_captures')
        r['lobby']['rows'].pop()
        self.assertEqual(classify(r)[0],'incomplete_result_identities')


class StorageTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'matches.sqlite3'
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE match_journal(match_id TEXT PRIMARY KEY,snapshot_json TEXT)')
            db.execute('CREATE TABLE completion_captures(match_id TEXT PRIMARY KEY,normalized_json TEXT,captured_at REAL)')
            db.execute('CREATE TABLE matches(match_id TEXT PRIMARY KEY,observation_json TEXT)')
            db.execute('CREATE TABLE results(match_id TEXT PRIMARY KEY,normalized_json TEXT)')
        self.insert(fixture())

    def insert(self,r):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('INSERT INTO match_journal VALUES (?,?)',(r['id'],json.dumps(r['metadata'])))
            db.execute('INSERT INTO completion_captures VALUES (?,?,?)',(r['id'],json.dumps(r['finish']),100))

    def test_dry_run_is_read_only(self):
        before=self.path.read_bytes()
        self.assertEqual(len(refresh(self.path,True)['players']),2)
        self.assertEqual(before,self.path.read_bytes())

    def test_retries_restarts_concurrency_and_late_resources_once(self):
        first=refresh(self.path)
        with ThreadPoolExecutor(4) as pool:
            for result in pool.map(lambda _:refresh(self.path),range(8)):self.assertEqual(result,first)
        r=fixture();r['metadata']['trigger']='normal_completion_observed'
        for row in r['finish']['rows']:row['fields']['resources']={'values_in_display_order':[42,0]}
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('INSERT INTO matches VALUES (?,?)',(r['id'],json.dumps(r['metadata'])))
            db.execute('INSERT INTO results VALUES (?,?)',(r['id'],json.dumps(r['finish'])))
        self.assertEqual(refresh(self.path)['players'],first['players'])
        self.assertEqual(stored(self.path)['players'],first['players'])

    def test_corrected_earlier_match_replays_all_and_preserves_old_run(self):
        self.insert(fixture('two',2));old=refresh(self.path)
        r=fixture();r['finish']['engine_outcome']['winning_team']='b'
        for row in r['finish']['rows']:
            if row['kind']=='team':row['fields']['victory_points']['values_in_display_order']=[200 if row['row_id']=='tb' else 0]
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE completion_captures SET normalized_json=? WHERE match_id=?',(json.dumps(r['finish']),'one'))
        new=refresh(self.path)
        self.assertNotEqual(old['matches']['two']['updates'],new['matches']['two']['updates'])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rating_runs').fetchone()[0],2)
            self.assertEqual(new,evaluate(read_inputs(db)))

    def test_failed_replay_preserves_published_head(self):
        old=refresh(self.path);self.insert(fixture('two',2))
        with patch('match_ratings.evaluate',side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):refresh(self.path)
        self.assertEqual(stored(self.path),old)
        self.assertEqual(len(refresh(self.path)['matches']),2)

    def test_review_and_default_greeting_lookup(self):
        result=refresh(self.path)
        self.assertEqual(load_matches(self.path)[0]['rating'],result['matches']['one'])
        class Controller:
            journal=type('J',(),{'path':self.path})()
        social=LobbySocial(Controller())
        rating=social.rating_lookup('76561198000000001')
        self.assertIsNotNone(rating)
        self.assertTrue(greeting({'display_name':'Player','games_played':100},rating,games=1).endswith(f"Rating: {round(rating['value'])} (provisional)."))
        self.assertIsNone(social.rating_lookup('unknown'))

    def test_parameters_cannot_change_under_published_version(self):
        from match_ratings import PARAMETERS
        old=refresh(self.path)
        with patch.dict(PARAMETERS,beta=1):
            with self.assertRaisesRegex(ValueError,'frozen'):refresh(self.path)
        self.assertEqual(old,stored(self.path))


class HistoricalTests(unittest.TestCase):
    def test_two_real_matches_chronological_predictions(self):
        records=json.loads((_test_paths.ROOT/'tests/fixtures/rating_history.json').read_text(encoding='utf-8'))
        # This old fixture has no recorded Final VP; automatic outcomes are unavailable.
        self.assertEqual(evaluate(records)['players'],{})
        # Explicit historical decisions still exercise chronological rating predictions.
        for record in records:
            record['metadata']['operator_adjudication']=dict(source='explicit_user_confirmation',match_id=record['id'],winning_team='b')
        result=evaluate(records)
        self.assertEqual(len(result['players']),21)
        matches=list(result['matches'].values())
        self.assertTrue(all(m['status']=='rated' for m in matches))
        self.assertEqual(matches[0]['probability_a'],.5)
        self.assertAlmostEqual(matches[1]['probability_a'],.5553678504523771,12)
        self.assertEqual(len(matches[0]['updates']),16)
        self.assertEqual(len(matches[1]['updates']),12)
        self.assertEqual(sum(p['games']==2 for p in result['players'].values()),7)
        self.assertTrue(all(p['provisional'] for p in result['players'].values()))
        for m in matches:
            for change in m['updates'].values():
                delta=change['after']['value']-change['before']['value']
                self.assertEqual(delta>0,change['team']=='b')
        # The second match must never influence the first match's prediction/update.
        self.assertEqual(evaluate(records[:1])['matches'][records[0]['id']],matches[0])


if __name__=='__main__':unittest.main()
