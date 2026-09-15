import _test_paths
import copy
from pathlib import Path
import tempfile
import unittest

from match_outcomes import automatic_winner, final_vp
from test_match_ratings import fixture


class OutcomeTests(unittest.TestCase):
    def test_completion_requires_valid_target_and_both_team_totals(self):
        record=fixture();result=record['finish'];metadata=record['metadata']
        self.assertEqual(automatic_winner(result,metadata),'a')
        for points in (0,7,199,None,'bad',float('nan')):
            changed=copy.deepcopy(result)
            changed['rows'][1]['fields']['victory_points']['values_in_display_order']=[points]
            self.assertIsNone(automatic_winner(changed,metadata))
        for target in (None,0,-1,'bad',float('inf')):
            changed=dict(metadata,effective_settings={'victoryPoints':target})
            self.assertIsNone(automatic_winner(result,changed))
        changed=copy.deepcopy(result);changed['rows'].pop(2)
        self.assertIsNone(automatic_winner(changed,metadata))
        changed=copy.deepcopy(result);changed['rows'][2]['fields']['victory_points']['values_in_display_order']=[200]
        self.assertIsNone(automatic_winner(changed,metadata))
        changed=copy.deepcopy(result);changed['engine_outcome']={'winning_team':'b'}
        self.assertIsNone(automatic_winner(changed,metadata))

    def test_archive_target_precedes_lobby_settings_without_changing_evidence(self):
        record=fixture();result=record['finish'];metadata=record['metadata']
        result['replay']={'ss_sha256':'a'*64}
        before=copy.deepcopy(record)
        with tempfile.TemporaryDirectory() as folder:
            database=Path(folder)/'test.sqlite3'
            replay=Path(folder)/'replays'/('a'*64)/'replay.ss'
            replay.parent.mkdir(parents=True)
            replay.write_text('{settings {scoreFinal 250}}',encoding='utf-8')
            self.assertEqual(final_vp(result,metadata,database),250)
            self.assertIsNone(automatic_winner(result,metadata,database))
        self.assertEqual(record,before)
