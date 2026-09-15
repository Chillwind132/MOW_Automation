import _test_paths
import copy
import tempfile
import unittest
from pathlib import Path

from match_review_presentation import decorate,departures,recorded_games,rank_icons,has_human_opponents


class PresentationTests(unittest.TestCase):
    def test_progress_uses_main_table_without_changing_saved_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            match=dict(rows=[dict(kind='player',row_id='p1',fields={})],participants=[],metadata={},
                       capture_stage='progress_snapshot',progress_snapshots=[dict(sampled_at=12,
                       player_statistics=dict(status='observed',teams=[dict(team='a',victory_points=10,score=123,infantry=[4,2],vehicles=[1,0])],
                       players=[dict(participant_key='p1',steam_id='human',team='a',display_name='Player',score=123,
                                     infantry=[4,2],vehicles=[1,0],resources=[50,0])]))])
            original=copy.deepcopy(match['rows'])
            decorate(match,Path(folder)/'test.sqlite3')
            self.assertEqual(match['rows'],original)
            self.assertEqual(match['display_rows'][1]['fields']['score']['values_in_display_order'],[123])
            self.assertEqual(match['display_sampled_at'],12)
            match['replay']={'ss_sha256':'not-a-hash'}
            decorate(match,Path(folder)/'test.sqlite3')
            self.assertEqual(match['display_rows'],original)
            self.assertEqual(match['display_source'],'replay')

    def player_match(self,mode):
        return dict(rows=[dict(kind='team',row_id='ta',fields={'player':{'text':'Team A'},'victory_points':{'values_in_display_order':[26]}}),
                          dict(kind='player',row_id='p1',participant_key='one',army='usa',fields={'player':{'text':'One'}}),
                          dict(kind='player',row_id='p2',participant_key='two',army='ger_ss',fields={'player':{'text':'Two'}})],
                    participants=[dict(participant_key='one',starting_team='a'),dict(participant_key='two',starting_team='a')],
                    metadata={},settings={'armySelectionMode':mode},capture_stage='lobby_results')

    def test_players_can_choose_different_nations_on_same_team(self):
        m=self.player_match(2);original=copy.deepcopy(m['rows'])
        decorate(m,'unused.sqlite3')
        self.assertEqual(m['army_mode'],'Players')
        self.assertEqual([r['player_army'] for r in m['player_rows']],['U.S. Army','Waffen-SS'])
        self.assertEqual([r['team_label'] for r in m['player_rows']],['A','A'])
        self.assertTrue(all(r['team']=='a' and r['kind']=='player' for r in m['player_rows']))
        self.assertEqual(m['player_rows'][0]['fields']['victory_points']['values_in_display_order'],[26])
        self.assertEqual(m['rows'],original)

    def test_teams_use_configured_nation_and_alliances_keep_chosen_nation(self):
        m=self.player_match(1);m['settings']['teamArmies']={'a':'ger'}
        decorate(m,'unused.sqlite3')
        self.assertEqual(m['army_mode'],'Teams')
        self.assertEqual([r['team_label'] for r in m['player_rows']],['A · Wehrmacht','A · Wehrmacht'])
        m=self.player_match(3);m['settings']['teamAlliances']={'a':'allies','b':'axis'}
        decorate(m,'unused.sqlite3')
        self.assertEqual(m['army_mode'],'Alliances')
        self.assertEqual(m['player_rows'][0]['team_label'],'A · ALLIES/SOVIET')
        self.assertEqual(m['player_rows'][0]['player_army'],'U.S. Army')

    def test_replay_selection_rules_override_stale_recorded_settings(self):
        import shutil
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);digest='a'*64;archive=root/'replays'/digest;archive.mkdir(parents=True)
            shutil.copyfile(_test_paths.ROOT/'tests/fixtures/replays/replay2/replay2.ss',archive/'replay.ss')
            m=self.player_match(0);m['replay']={'ss_sha256':digest}
            decorate(m,root/'test.sqlite3')
            self.assertEqual(m['army_mode'],'Teams')
            self.assertEqual(m['player_rows'][0]['team_label'],'A · Waffen-SS')

    def test_players_filter_requires_opposing_humans_but_allows_bots(self):
        a=dict(steam_id='one',starting_team='a',role='participant',controller_kind='local_host')
        b=dict(steam_id='two',starting_team='b',role='participant',controller_kind='remote_human')
        bot=dict(steam_id=None,starting_team='b',role='participant',controller_kind='ai')
        for people,expected in [([a,b],True),([a,b,bot],True),([a,bot],False),
                                ([a,dict(b,starting_team='a')],False),
                                ([a,dict(b,role='spectator')],False),
                                ([a,dict(b,steam_id=None)],False),
                                ([a,dict(b,steam_id='one')],False),([],False)]:
            with self.subTest(people=people):
                self.assertEqual(has_human_opponents({'participants':people}),expected)

    def test_rank_exact_counts_thresholds_and_unknown(self):
        match={'participants':[dict(steam_id='a',games_played=0),dict(steam_id='b',games_played=1129),
                               dict(steam_id='c',games_played=None)]}
        ranks=recorded_games(match,'unused.sqlite3')
        self.assertEqual(ranks['a'],dict(games_played=0,tier=0))
        self.assertEqual(ranks['b'],dict(games_played=1129,tier=8))
        self.assertNotIn('c',ranks)
        icons=rank_icons()
        self.assertEqual(len(icons),11)
        self.assertTrue(icons['8'].startswith('data:image/png;base64,iVBOR'))

    def test_departure_reason_rejoin_and_gaps(self):
        def event(kind,evidence,stamp=1):return dict(steam_id='a',kind=kind,evidence=evidence,observed_at=stamp)
        native=dict(association='active_controller_match_and_same_lobby',flags=4)
        events=[event('steam_lobby_membership',native),
                event('roster_missing',{'before':{'status':'present'}},2),
                event('roster_restored',{},3)]
        self.assertEqual(departures(events)['a'],dict(label='Leaver',reason='Disconnected',returned=True))
        for e in [event('observation_gap',{}),event('state_observed_without_continuous_coverage',{}),
                  event('steam_lobby_membership',dict(native,association='unassociated_or_outside_active_play')),
                  event('roster_missing',{'before':{'status':'ambiguous_identity'}})]:
            self.assertEqual(departures([e]),{})
        unknown=departures([event('roster_missing',{'before':{'status':'present'}})])
        self.assertIn('reason unavailable',unknown['a']['reason'])


if __name__=='__main__':unittest.main()
