"""Real normal-finish fixture plus simulated observer/persistence faults."""
import _test_paths  # Shared paths for direct runs and test discovery.
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from headless_host import HostController
from modules.end_game_results.legacy import normalize_completion
from match_journal import Journal

FIXTURES=_test_paths.ROOT/'tests/fixtures'


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.raw=json.loads((FIXTURES/'ai_completion.json').read_text())
        self.match=json.loads((FIXTURES/'ai_match.json').read_text())

    def test_observed_winner_scores_and_duplicate_ai_names(self):
        result=normalize_completion(self.raw,self.match['loaded_roster'],self.match['participants'])
        self.assertEqual(result['engine_outcome']['winning_team'],'a')
        self.assertEqual([r['fields']['score']['values_in_display_order'] for r in result['rows']],[[658],[658],[0],[474],[474]])
        ais=[r for r in result['rows'] if r.get('controller_kind')=='ai']
        self.assertEqual(len({r['participant_key'] for r in ais}),2)
        self.assertTrue(all(r['steam_id'] is None for r in ais))
        self.assertEqual(ais[0]['fields']['infantry']['values_in_display_order'],[37,34])

    def test_unapproved_native_member_prevents_association(self):
        changed=copy.deepcopy(self.match['participants'])
        changed[1]['native_member_id']=999
        with self.assertRaisesRegex(ValueError,'approved native member'):
            normalize_completion(self.raw,self.match['loaded_roster'],changed)

    def test_delayed_numeric_cells_are_not_committed_as_empty_results(self):
        raw=copy.deepcopy(self.raw)
        target=next(n for n in raw['nodes'] if n.get('text') and '658' in n['text'])
        target['text']=''
        with self.assertRaisesRegex(ValueError,'Incomplete terminal numeric'):
            normalize_completion(raw,self.match['loaded_roster'],self.match['participants'])

    def test_capture_is_committed_idempotently_and_conflicts_preserve_original(self):
        result=normalize_completion(self.raw,self.match['loaded_roster'],self.match['participants'])
        with tempfile.TemporaryDirectory() as temporary:
            journal=Journal(Path(temporary)/'journal.sqlite3')
            process,session=journal.register({'fixture':True},{})
            match=journal.new_match(session,{})
            self.assertTrue(journal.save_completion(match,result,self.raw,{}))
            self.assertFalse(journal.save_completion(match,result,self.raw,{}))
            changed=copy.deepcopy(result)
            changed['engine_outcome']['winning_team']='b'
            with self.assertRaisesRegex(RuntimeError,'Conflicting completion'):
                journal.save_completion(match,changed,self.raw,{})

    def test_watcher_captures_first_terminal_sample_without_waiting_for_exit(self):
        controller=HostController.__new__(HostController)
        controller.state=Mock(return_value={'ticks':1})
        controller.command=Mock(return_value={'probe':{'managerStateRaw':3}})
        controller.active_match=self.match
        controller.match_id=self.match['match_id']
        controller.capture_completion=Mock(return_value={'saved':True})
        result=controller.watch(60,1)
        self.assertTrue(result['finish_captured'])
        controller.capture_completion.assert_called_once()
        self.assertEqual([c.args[0] for c in controller.command.call_args_list],['probe'])


if __name__=='__main__':
    unittest.main()
