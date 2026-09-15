import _test_paths
import copy
import json
import subprocess
import unittest
from modules.live_game_data.statistics import normalize_live_statistics, compare_final_statistics


class LiveStatisticsTests(unittest.TestCase):
    def test_native_reader_uses_mapped_fields_and_rejects_invalid_ownership(self):
        subprocess.run(['node','tests/battle_statistics_harness.js'],cwd=_test_paths.ROOT,
                       check=True,capture_output=True,text=True)

    def setUp(self):
        data=json.loads((_test_paths.ROOT/'tests/fixtures/live_statistics_20260908.json').read_text())
        self.match=data['match'];self.live=data['live']

    def test_real_capture_binds_human_and_ai_and_retains_nonzero_counters(self):
        result=normalize_live_statistics(self.match,self.live)
        self.assertEqual(result['status'],'observed')
        self.assertEqual(len(result['players']),2)
        human=next(p for p in result['players'] if p['steam_id'])
        bot=next(p for p in result['players'] if not p['steam_id'])
        self.assertEqual(human['display_name'],'Player21')
        self.assertGreater(human['score'],0)
        self.assertEqual(human['infantry'][0],bot['infantry'][1])
        self.assertTrue(bot['participant_key'].startswith('ai:'))
        team=next(t for t in result['teams'] if t['team']=='b')
        self.assertEqual(team['infantry'],human['infantry'])
        self.assertEqual(team['score'],human['score'])

    def test_generation_and_identity_failures_never_present_zeroes(self):
        for mutation in ('epoch','steam','team','kind','duplicate','missing'):
            live=copy.deepcopy(self.live);raw=live['playerStatistics'];p=raw['players'][0]
            if mutation=='epoch':raw['nativeGameStartTime']='old'
            if mutation=='steam':p['steamWords'][0]+=1
            if mutation=='team':p['team']='a'
            if mutation=='kind':p['ai']=True
            if mutation=='duplicate':raw['players'][1]=copy.deepcopy(p)
            if mutation=='missing':raw['players'].pop()
            result=normalize_live_statistics(self.match,live)
            self.assertEqual(result['status'],'unavailable',mutation)
            self.assertEqual(result['players'],[],mutation)

    def test_missing_counter_stays_null_but_observed_zero_is_zero(self):
        raw=self.live['playerStatistics']['players'][0]
        raw['resources']=None;raw['vehicles']=[0,0]
        result=normalize_live_statistics(self.match,self.live)
        self.assertEqual(result['status'],'partial')
        self.assertIsNone(result['players'][0]['resources'])
        self.assertEqual(result['players'][0]['vehicles'],[0,0])

    def test_missing_team_score_does_not_become_zero(self):
        self.live['playerStatistics']['scores']=[]
        result=normalize_live_statistics(self.match,self.live)
        self.assertTrue(all(t['victory_points'] is None and t['score'] is None for t in result['teams']))

    def test_false_zero_scoreboard_is_disclosed_without_overwriting_evidence(self):
        native=normalize_live_statistics(self.match,self.live)
        result={'rows':[{'participant_key':p['participant_key'],'fields':{
            k:{'values_in_display_order':[p[k]] if k=='score' else p[k]}
            for k in ('infantry','vehicles','score','resources')}} for p in native['players']]}
        self.assertEqual(compare_final_statistics(result,native)['status'],'matched')
        result['rows'][0]['fields']['score']['values_in_display_order']=[0]
        before=copy.deepcopy(result)
        check=compare_final_statistics(result,native)
        self.assertEqual(check['status'],'disagrees')
        self.assertEqual(check['differences'][0]['field'],'score')
        self.assertEqual(result,before)


if __name__=='__main__':unittest.main()
