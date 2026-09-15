"""Real persisted replay fixtures, source precedence and delayed-file recovery."""
import _test_paths
from contextlib import closing
import copy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from modules.end_game_results.replays import (Binary, SOURCE, ReplayImporter, read_replay, normalize,
                            publish, unpack, tree, section)

FIXTURES = _test_paths.ROOT/'tests/fixtures/replays'


def metadata(replay):
    return dict(match_id='replay-test',native_game_start_time=hex(replay['epoch']),map=replay['map'],
                created_at=replay['epoch'],engine_outcome={'winning_team':'b'},
                trigger='normal_completion_observed',participants=[dict(
                    participant_key='member:'+r['key'],native_member_id=r['member_id'],
                    starting_team=r['team'],steam_id=None if r['ai'] else r['steam_id'],
                    controller_kind='ai' if r['ai'] else 'local_host',role='participant',display_name=r['name'])
                    for r in replay['rows'] if r['slot']!=255])


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.replay=read_replay(FIXTURES/'replay2/replay2.ss')
        self.match=metadata(self.replay)

    def test_real_vehicle_and_special_resource_results_match_game_screenshot(self):
        rows={r['name']:r for r in self.replay['rows']}
        for name,values in [('Player21',([109,41],[0,2],2288,[2045,4])),
                            ('AI Player: Heroic',([40,109],[2,0],1601,[1694,0]))]:
            r=rows[name]
            self.assertEqual((r['infantry'],r['vehicles'],r['score'],r['resources']),values)
        self.assertEqual(rows['Team A']['victory_points'],26)
        self.assertEqual(rows['Team B']['victory_points'],86)

    def test_original_xilyy_zeros_are_persisted_in_replay_not_defaults(self):
        replay=read_replay(FIXTURES/'replay1/replay1.ss')
        rows={r['name']:r for r in replay['rows']}
        self.assertEqual(rows['Player20']['resources'],[0,0])
        self.assertEqual(rows['Player20']['infantry'],[0,0])
        self.assertEqual(rows['Player07']['resources'],[881,0])
        self.assertGreater(rows['Player20']['unused_buffer_bytes'],0)

    def test_mismatched_epoch_map_identity_kind_and_team_are_rejected(self):
        for field,val in [('native_game_start_time','0x123'),('map','different')]:
            m=copy.deepcopy(self.match);m[field]=val
            with self.assertRaises(ValueError):normalize(self.replay,m)
        for field,val in [('steam_id','76561190000000000'),('starting_team','a'),
                          ('native_member_id',500),('controller_kind','ai')]:
            m=copy.deepcopy(self.match);m['participants'][0][field]=val
            with self.assertRaises(ValueError):normalize(self.replay,m)

    def test_replay_outcome_does_not_borrow_ui_winner_or_infer_from_vp(self):
        result=normalize(self.replay,self.match)
        self.assertEqual(result['engine_outcome']['winning_team'],'a')
        self.assertEqual(result['replay']['info_raw'],'a')
        missing=copy.deepcopy(self.replay);missing['info_raw']=''
        self.assertIsNone(normalize(missing,self.match)['engine_outcome'])

    def test_incomplete_stream_and_bad_compressed_data_rejected(self):
        folder=self.root/'replay';shutil.copytree(FIXTURES/'replay2',folder)
        qm=folder/'replay2.qm';qm.write_bytes(qm.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError,'begin/end'):read_replay(folder/'replay2.ss')
        with self.assertRaises(ValueError):unpack('B64:not-valid')
        self.assertEqual(Binary(b'\xff\x03\x00\x00abc').string(),'abc')

    def test_replay_promotes_once_preserves_old_evidence_and_excludes_old_finish(self):
        database=self.root/'matches.sqlite3'
        old=dict(source='native_statistics_ui',rows=[],engine_outcome={'winning_team':'b'})
        with closing(sqlite3.connect(database)) as db, db:
            db.executescript('CREATE TABLE matches(match_id TEXT PRIMARY KEY,observation_json TEXT);'
                'CREATE TABLE results(match_id TEXT PRIMARY KEY,normalized_json TEXT,raw_json TEXT);'
                'CREATE TABLE match_journal(match_id TEXT PRIMARY KEY,snapshot_json TEXT);'
                'CREATE TABLE completion_captures(match_id TEXT PRIMARY KEY,normalized_json TEXT);')
            db.execute('INSERT INTO matches VALUES (?,?)',(self.match['match_id'],json.dumps(self.match)))
            db.execute('INSERT INTO results VALUES (?,?,?)',(self.match['match_id'],json.dumps(old),'{}'))
            db.execute('INSERT INTO match_journal VALUES (?,?)',(self.match['match_id'],json.dumps(self.match)))
            db.execute('INSERT INTO completion_captures VALUES (?,?)',(self.match['match_id'],json.dumps(old)))
        self.assertTrue(publish(database,self.replay,self.match))
        self.assertFalse(publish(database,self.replay,self.match))
        with closing(sqlite3.connect(database)) as db, db:
            self.assertEqual(json.loads(db.execute('SELECT normalized_json FROM superseded_results').fetchone()[0]),old)
            from match_ratings import read_inputs
            record=read_inputs(db)[0]
            self.assertNotIn('finish',record)
            self.assertEqual(record['lobby']['source'],SOURCE)
            self.assertEqual(record['metadata']['engine_outcome']['winning_team'],'a')
        archive=database.parent/'replays'/self.replay['ss_sha256']
        self.assertEqual((archive/'replay.qm').read_bytes(),self.replay['qm'])

    def test_watcher_retries_late_complete_file_without_game_or_ui(self):
        profiles=self.root/'profiles';folder=profiles/'123/replays/replay2'
        shutil.copytree(FIXTURES/'replay2',folder)
        database=self.root/'db.sqlite3'
        with closing(sqlite3.connect(database)) as db, db:
            db.execute('CREATE TABLE matches(match_id TEXT PRIMARY KEY,observation_json TEXT)')
            db.execute('INSERT INTO matches VALUES (?,?)',(self.match['match_id'],json.dumps(self.match)))
        qm=folder/'replay2.qm';data=qm.read_bytes();qm.write_bytes(data[:-5])
        importer=ReplayImporter(database,profiles)
        self.assertEqual(importer.poll(),[])

        self.assertIn('pending',importer.poll()[0])
        qm.write_bytes(data)
        self.assertEqual(importer.poll(),[])
        self.assertTrue(importer.poll()[0]['created'])
        self.assertEqual(importer.poll(),[])

    def test_unobserved_replay_is_imported_with_deterministic_identity(self):
        profiles=self.root/'profiles'
        shutil.copytree(FIXTURES/'replay2',profiles/'123/replays/replay2')
        database=self.root/'standalone.sqlite3'
        importer=ReplayImporter(database,profiles)
        self.assertEqual(importer.poll(),[])
        first=importer.poll()[0]
        self.assertTrue(first['created'])
        second=ReplayImporter(database,profiles);second.poll()
        repeat=second.poll()[0]
        self.assertEqual(repeat['match_id'],first['match_id'])
        self.assertFalse(repeat['created'])


if __name__=='__main__':unittest.main()
