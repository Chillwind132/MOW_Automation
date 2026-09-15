"""Shared module boundaries and standalone entry points."""
import _test_paths
from contextlib import closing
import json
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from modules.live_game_data import compose_bridge
from modules.end_game_results import load_result, SOURCE
from headless_host import HostController


class ModuleTests(unittest.TestCase):
    def test_packages_import_without_host_search_path_or_native_libraries(self):
        code = "import sys; import modules.live_game_data; import modules.end_game_results; assert 'frida' not in sys.modules; assert 'pymem' not in sys.modules"
        subprocess.run([sys.executable, '-c', code], cwd=_test_paths.ROOT, check=True, capture_output=True)

    def test_compatibility_exports_share_the_same_implementations(self):
        import live_statistics, match_telemetry, match_participation, replay_results, match_metadata
        from modules import live_game_data as live, end_game_results as final
        self.assertIs(live_statistics.normalize_live_statistics, live.normalize_live_statistics)
        self.assertIs(match_telemetry.MatchTelemetry, live.MatchTelemetry)
        self.assertIs(match_participation.Participation, live.Participation)
        self.assertIs(match_metadata.participants, live.participants)
        self.assertIs(replay_results.ReplayImporter, final.ReplayImporter)

    def test_bridge_requires_exactly_one_module_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'host.js'
            for source in ('', '// @include modules/live_game_data/bridge.js\n'*2):
                path.write_text(source)
                with self.assertRaises(ValueError): compose_bridge(path)
        source=compose_bridge(_test_paths.ROOT/'headless/headless_host.js')
        self.assertNotIn('// @include modules/live_game_data/bridge.js', source)
        self.assertEqual(source.count('function battleStatisticsProbe('), 1)
        subprocess.run(['node','--input-type=module','--check'],input=source,text=True,capture_output=True,check=True)

    def test_offline_replay_cli_and_legacy_cli_work_outside_project(self):
        subprocess.run([sys.executable, str(_test_paths.ROOT/'headless/replay_results.py'), '--help'],
                       cwd=Path(tempfile.gettempdir()),check=True,capture_output=True)
        subprocess.run([sys.executable, '-m', 'modules.end_game_results', '--help'],
                       cwd=_test_paths.ROOT,check=True,capture_output=True)

    def test_final_lookup_rejects_ui_rows_and_does_not_create_missing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'results.sqlite3'
            self.assertIsNone(load_result(path,'match'))
            self.assertFalse(path.exists())
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE results (match_id TEXT PRIMARY KEY, normalized_json TEXT)')
                db.execute('INSERT INTO results VALUES (?,?)',('match',json.dumps({'source':'native_statistics_ui_tree'})))
            self.assertIsNone(load_result(path,'match'))
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('UPDATE results SET normalized_json=?',(json.dumps({'source':SOURCE,'score':0}),))
            self.assertEqual(load_result(path,'match')['score'],0)

    def test_replay_cli_retries_transient_startup_database_error(self):
        from modules.end_game_results.replays import main, ReplayImporter
        with patch('sys.argv',['replays']), patch.object(ReplayImporter,'poll',side_effect=[sqlite3.OperationalError('database is locked'),[]]) as poll, patch('modules.end_game_results.replays.time.sleep'):
            main()
        self.assertEqual(poll.call_count,2)

    def test_loaded_modes_use_one_shared_observer(self):
        c=HostController.__new__(HostController)
        c.active_match=None
        c.command=Mock(side_effect=[{'probe':{'gameStartTimeRaw':'0x123'}},{'probe':{'managerStateRaw':1}}])
        def associate(controller,roster,hosting_mode):
            controller.active_match={'match_id':'one','hosting_mode':hosting_mode}
        with patch('modules.live_game_data.associate_loaded',side_effect=associate) as bind, patch('modules.live_game_data.observe_controller') as observe:
            result=c.observe_loaded_match('solo')
        bind.assert_called_once()
        observe.assert_called_once_with(c,{'gameStartTimeRaw':'0x123'},{'managerStateRaw':1})
        self.assertEqual(result['match_id'],'one')


if __name__=='__main__': unittest.main()
