"""Regression tests using the native solo quit capture, not invented score rows."""
import _test_paths  # Shared paths for direct runs and test discovery.
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from modules.end_game_results.legacy import cell, normalize_statistics, save_result

FIXTURES = _test_paths.ROOT/'tests/fixtures'


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads((FIXTURES/'solo_statistics.json').read_text())
        self.match = json.loads((FIXTURES/'solo_match.json').read_text())
        self.result = normalize_statistics(self.raw)

    def test_native_team_and_player_rows_preserve_blanks_and_pairs(self):
        team_a, player, team_b = self.result['rows']
        self.assertEqual([row['row_id'] for row in self.result['rows']],
                         ['ta','76561190000001022','tb'])
        self.assertEqual(player['fields']['player']['text'],'Player17')
        self.assertIsNone(player['fields']['victory_points'])
        self.assertEqual(player['fields']['score']['values_in_display_order'],[0])
        self.assertEqual(player['fields']['infantry']['values_in_display_order'],[0,0])
        self.assertEqual(player['fields']['resources']['values_in_display_order'],[0,0])
        self.assertIsNone(team_b['fields']['resources'])
        self.assertEqual(team_a['fields']['victory_points']['values_in_display_order'],[0])
        self.assertIsNone(self.result['engine_outcome'])

    def test_missing_is_not_zero_and_nonzero_pairs_are_not_collapsed(self):
        self.assertIsNone(cell(None))
        self.assertEqual(cell('<x.>17 / 23')['values_in_display_order'],[17,23])
        self.assertEqual(cell('<c(green)>5 <c(red)>9')['values_in_display_order'],[5,9])
        self.assertIsNone(cell('unavailable')['values_in_display_order'])

    def test_empty_result_panel_cannot_be_exported_as_zero(self):
        self.raw['nodes'] = [n for n in self.raw['nodes'] if n['vtable'] != 0xd82e0c]
        with self.assertRaisesRegex(ValueError,'No player result'):
            normalize_statistics(self.raw)

    def test_duplicate_export_and_separate_cycles(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary)/'results.sqlite3'
            self.assertTrue(save_result(database,self.match,self.raw,self.result))
            self.assertFalse(save_result(database,self.match,self.raw,self.result))
            second = dict(self.match,match_id='independent-second-match')
            self.assertTrue(save_result(database,second,self.raw,self.result))
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute('SELECT count(*) FROM results').fetchone()[0],2)

    def test_conflicting_export_cannot_overwrite_saved_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary)/'results.sqlite3'
            save_result(database,self.match,self.raw,self.result)
            changed = copy.deepcopy(self.result)
            changed['rows'][1]['fields']['score'] = cell('1')
            with self.assertRaisesRegex(ValueError,'Conflicting results'):
                save_result(database,self.match,self.raw,changed)

    def test_identity_mismatch_refuses_association(self):
        self.result['rows'][1]['steam_id'] = '76561190000000000'
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError,'Steam identities'):
                save_result(Path(temporary)/'results.sqlite3',self.match,self.raw,self.result)


if __name__ == '__main__':
    unittest.main()
