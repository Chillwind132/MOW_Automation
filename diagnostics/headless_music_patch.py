"""Prepare/apply/restore a reversible silent menu-theme patch for headless tests.

Only the supported Robz 1.30.10 music archive and exact diagnosed WAV size are
accepted. Applying/restoring requires no running game. Original archives are
backed up and hash checked; this is a headless audio workaround, not a leak fix.
"""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import wave
import zipfile
from headless_host import ROOT,find_game_executable,find_process

ENTRY='music/main_theme.wav'
ORIGINAL_SIZE=101043628

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def prepare(source,directory):
    directory.mkdir(parents=True,exist_ok=False)
    original=digest(source)
    backup=directory/'original_music.pak';shutil.copy2(source,backup)
    if digest(backup)!=original or digest(source)!=original:raise RuntimeError('Archive changed while backing up')
    candidate=directory/'headless_music.pak'
    silence=io.BytesIO()
    with wave.open(silence,'wb') as wav:
        wav.setparams((1,2,8000,0,'NONE','not compressed'));wav.writeframes(bytes(16000))
    with zipfile.ZipFile(backup) as old,zipfile.ZipFile(candidate,'w') as new:
        if old.getinfo(ENTRY).file_size!=ORIGINAL_SIZE:raise RuntimeError('Unexpected menu theme; refusing replacement')
        if any(not i.is_dir() and i.filename!=ENTRY for i in old.infolist()):
            raise RuntimeError('Unexpected additional archive content')
        for info in old.infolist():
            new.writestr(info,silence.getvalue() if info.filename==ENTRY else old.read(info))
    with zipfile.ZipFile(candidate) as z:
        if z.testzip() is not None:raise RuntimeError('Candidate CRC failure')
        with wave.open(io.BytesIO(z.read(ENTRY))) as wav:
            if wav.getnframes()!=8000 or wav.getframerate()!=8000:raise RuntimeError('Candidate WAV validation failed')
    manifest={'source':str(source.resolve()),'original_sha256':original,'candidate_sha256':digest(candidate),
              'original_wav_bytes':ORIGINAL_SIZE,'candidate_wav_bytes':len(silence.getvalue()),
              'purpose':'Headless-only silence replaces menu music; original archive retained; no engine allocations freed'}
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest

def install(directory,restore=False):
    if find_process() is not None:raise RuntimeError('Stop the game before changing its resource archive')
    manifest=json.loads((directory/'manifest.json').read_text())
    source=Path(manifest['source'])
    expected=(find_game_executable().parent/'mods/robz realism mod 1.30.10/resource/music.pak').resolve()
    if source.resolve()!=expected:raise RuntimeError('Manifest does not name the supported music archive')
    current=manifest['candidate_sha256'] if restore else manifest['original_sha256']
    wanted=manifest['original_sha256'] if restore else manifest['candidate_sha256']
    incoming=directory/('original_music.pak' if restore else 'headless_music.pak')
    if digest(source)!=current or digest(incoming)!=wanted:raise RuntimeError('Archive hash mismatch; preserving files')
    temporary=source.with_name('music.pak.headless-patch.tmp')
    if temporary.exists():raise RuntimeError('Patch temporary file already exists')
    with incoming.open('rb') as src,temporary.open('xb') as dst:shutil.copyfileobj(src,dst)
    if digest(temporary)!=wanted:raise RuntimeError('Copied archive hash mismatch')
    os.replace(temporary,source)
    if digest(source)!=wanted:raise RuntimeError('Installed archive verification failed')
    (directory/'last_operation.json').write_text(json.dumps({'action':'restore' if restore else 'apply',
        'source':str(source),'sha256':wanted,'time':datetime.now().isoformat()},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','apply','restore'))
    p.add_argument('--directory',type=Path);a=p.parse_args()
    if a.action=='prepare':
        directory=a.directory or ROOT/'validation'/datetime.now().strftime('headless_music_%Y%m%d_%H%M%S')
        source=find_game_executable().parent/'mods/robz realism mod 1.30.10/resource/music.pak'
        print(json.dumps(prepare(source,directory),indent=2));print('Prepared:',directory)
    else:
        if a.directory is None:p.error('--directory required')
        install(a.directory,a.action=='restore');print(a.action,'verified')
