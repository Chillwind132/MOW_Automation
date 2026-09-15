"""CLI launch policy and read-only review regression coverage."""
import _test_paths  # Shared paths for direct runs and test discovery.
import hashlib
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from headless_host import ensure_process
from match_review import load_matches,write_review


class LaunchTests(unittest.TestCase):
    def setUp(self):
        discovery = patch('headless_host.find_game_executable', return_value=None)
        self.discovery = discovery.start()
        self.addCleanup(discovery.stop)

    @patch('headless_host.subprocess.Popen')
    @patch('headless_host.os.startfile')
    @patch('headless_host.time.sleep')
    @patch('headless_host.find_process', side_effect=[None, 123])
    def test_direct_executable_preferred(self, find, sleep, steam, launch):
        executable = Path('C:/Games/AS2/mowas_2.exe')
        self.discovery.return_value = executable
        self.assertEqual(ensure_process('friends-host'), 123)
        launch.assert_called_once_with([str(executable), '-no_reload_caching'], cwd=str(executable.parent))
        steam.assert_not_called()

    @patch('headless_host.subprocess.Popen', side_effect=OSError('cannot launch'))
    @patch('headless_host.os.startfile')
    @patch('headless_host.time.sleep')
    @patch('headless_host.find_process', side_effect=[None, 123])
    def test_direct_failure_falls_back(self, find, sleep, steam, launch):
        self.discovery.return_value = Path('C:/Games/AS2/mowas_2.exe')
        self.assertEqual(ensure_process('friends-host'), 123)
        steam.assert_called_once_with('steam://rungameid/244450')

    @patch('headless_host.os.startfile')
    @patch('headless_host.time.sleep')
    @patch('headless_host.find_process',side_effect=[None,None,123])
    def test_friends_host_launches_when_not_running_including_record_only(self,find,sleep,launch):
        self.assertEqual(ensure_process('friends-host'),123)
        launch.assert_called_once_with('steam://rungameid/244450')

    @patch('headless_host.os.startfile')
    @patch('headless_host.find_process',return_value=123)
    def test_existing_game_is_reused(self,find,launch):
        self.assertEqual(ensure_process('friends-host'),123)
        launch.assert_not_called()

    @patch('headless_host.os.startfile')
    @patch('headless_host.find_process',return_value=None)
    def test_read_status_does_not_launch(self,find,launch):
        with self.assertRaisesRegex(RuntimeError,'not running'):
            ensure_process('status')
        launch.assert_not_called()

    @patch('headless_host.os.startfile')
    @patch('headless_host.time.monotonic',side_effect=[0,121])
    @patch('headless_host.find_process',return_value=None)
    def test_launch_timeout_is_bounded(self,find,clock,launch):
        with self.assertRaises(TimeoutError):ensure_process('friends-host')
        launch.assert_called_once()


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.db=self.root/'matches.sqlite3'
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('CREATE TABLE matches(match_id TEXT, observation_json TEXT)')
            db.execute('CREATE TABLE results(match_id TEXT, normalized_json TEXT)')
            for mid,time,outcome in [('old',1,{'winning_team':'a'}),('new',2,None)]:
                m={'observed_at':time,'starting_roster':{'map':'multi/other:battle_zones'},'trigger':'quit'}
                r={'engine_outcome':outcome,'rows':[{'kind':'player','row_id':'name','fields':{'player':{'text':'</script><script>alert(1)</script>'},'score':{'values_in_display_order':[0]}}}]}
                db.execute('INSERT INTO matches VALUES (?,?)',(mid,json.dumps(m)))
                db.execute('INSERT INTO results VALUES (?,?)',(mid,json.dumps(r)))

    def test_legacy_metadata_and_unknown_outcome_remain_explicit(self):
        rows=load_matches(self.db)
        self.assertEqual([r['id'] for r in rows],['new','old'])
        self.assertEqual(rows[0]['map'],'multi/other:battle_zones')
        self.assertEqual(rows[0]['outcome'],'Winner undetermined')
        self.assertIsNone(rows[1]['winner'])

    def test_review_never_changes_database(self):
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        path=write_review(load_matches(self.db),self.root/'review.html',self.db)
        self.assertTrue(path.is_file())
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(),before)

    def test_names_cannot_escape_embedded_json(self):
        path=write_review(load_matches(self.db),self.root/'review.html',self.db)
        page=path.read_text(encoding='utf-8')
        self.assertNotIn('</script><script>alert(1)',page)
        payload=re.search(r'<script id="data" type="application/json">(.*?)</script>',page,re.S)[1]
        self.assertEqual(json.loads(payload)['matches'][0]['players'],1)

    def test_missing_database_is_not_created(self):
        missing=self.root/'missing.sqlite3'
        with self.assertRaisesRegex(ValueError,'No match database'):
            load_matches(missing)
        self.assertFalse(missing.exists())

    def test_finish_capture_visible_without_duplicate_lobby_export(self):
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('CREATE TABLE match_journal(match_id TEXT, snapshot_json TEXT)')
            db.execute('CREATE TABLE completion_captures(match_id TEXT, normalized_json TEXT, captured_at REAL)')
            for mid in ('finish','old'):
                db.execute('INSERT INTO match_journal VALUES (?,?)',(mid,json.dumps({'map':'multi/river','loaded_at':1,'participants':[{'steam_id':'123'}]})))
                db.execute('INSERT INTO completion_captures VALUES (?,?,?)',(mid,json.dumps({'engine_outcome':{'winning_team':'b'},'rows':[{'kind':'player'}]}),3))
        before=self.db.read_bytes()
        rows=load_matches(self.db)
        self.assertEqual([r['id'] for r in rows],['finish','new','old'])
        self.assertEqual(rows[0]['winner'],'b')
        self.assertEqual(rows[0]['timestamp'],3)
        self.assertEqual(rows[0]['participants'],[{'steam_id':'123'}])
        self.assertEqual(rows[0]['capture_stage'],'finish_capture')
        self.assertIsNone(rows[2]['winner'])
        self.assertEqual(rows[2]['capture_stage'],'lobby_results')
        self.assertEqual(self.db.read_bytes(),before)
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('DROP TABLE matches')
            db.execute('DROP TABLE results')
        self.assertEqual(len(load_matches(self.db)),2)


if __name__=='__main__':unittest.main()
