import _test_paths  # Shared paths for direct runs and test discovery.
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import headless_music_patch as music

class MusicPatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.exe=self.root/'game/mowas_2.exe'
        self.source=self.exe.parent/'mods/robz realism mod 1.30.10/resource/music.pak'
        self.source.parent.mkdir(parents=True)
        with zipfile.ZipFile(self.source,'w') as z:z.writestr(music.ENTRY,b'original theme')
        self.directory=self.root/'patch'
        with patch.object(music,'ORIGINAL_SIZE',len(b'original theme')):
            self.manifest=music.prepare(self.source,self.directory)

    def test_prepare_leaves_original_and_roundtrip_restores_exact_archive(self):
        self.assertEqual(music.digest(self.source),self.manifest['original_sha256'])
        with patch.object(music,'find_process',return_value=None),patch.object(music,'find_game_executable',return_value=self.exe):
            music.install(self.directory)
            self.assertEqual(music.digest(self.source),self.manifest['candidate_sha256'])
            music.install(self.directory,restore=True)
            self.assertEqual(music.digest(self.source),self.manifest['original_sha256'])

    def test_running_game_prevents_any_archive_change(self):
        with patch.object(music,'find_process',return_value=123):
            with self.assertRaisesRegex(RuntimeError,'Stop the game'):music.install(self.directory)
        self.assertEqual(music.digest(self.source),self.manifest['original_sha256'])

    def test_changed_original_is_not_overwritten(self):
        self.source.write_bytes(b'new user version')
        with patch.object(music,'find_process',return_value=None),patch.object(music,'find_game_executable',return_value=self.exe):
            with self.assertRaisesRegex(RuntimeError,'hash mismatch'):music.install(self.directory)
        self.assertEqual(self.source.read_bytes(),b'new user version')

    def test_manifest_cannot_redirect_install(self):
        self.manifest['source']=str(self.root/'other.pak')
        (self.directory/'manifest.json').write_text(json.dumps(self.manifest))
        with patch.object(music,'find_process',return_value=None),patch.object(music,'find_game_executable',return_value=self.exe):
            with self.assertRaisesRegex(RuntimeError,'supported music archive'):music.install(self.directory)

if __name__=='__main__':unittest.main()
