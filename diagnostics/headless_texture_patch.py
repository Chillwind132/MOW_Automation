"""Reversible one-setting texture experiment, applied only with the game closed."""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from headless_host import ROOT,find_process

DETAIL=re.compile(rb'(?m)^([ \t]*\{detail[ \t]+)(detail_[a-z_]+)([ \t]*\}[ \t]*\r?$)')
def source_path():
    return Path.home()/'Documents/my games/men of war - assault squad 2/profiles/1101573056/options.set'
def digest(data):return hashlib.sha256(data).hexdigest()
def replace_detail(data,wanted,expected=None):
    matches=list(DETAIL.finditer(data))
    if len(matches)!=1:raise RuntimeError('Expected exactly one texture detail setting')
    current=matches[0].group(2).decode()
    if expected is not None and current!=expected:raise RuntimeError('Texture setting changed; preserving preferences')
    return DETAIL.sub(lambda m:m.group(1)+wanted.encode()+m.group(3),data),current
def prepare(directory):
    source=source_path();original=source.read_bytes()
    candidate,current=replace_detail(original,'detail_low')
    if current=='detail_low':raise RuntimeError('Textures are already low')
    directory.mkdir(parents=True,exist_ok=False)
    (directory/'original_options.set').write_bytes(original)
    (directory/'candidate_options.set').write_bytes(candidate)
    manifest={'source':str(source.resolve()),'original_sha256':digest(original),
        'candidate_sha256':digest(candidate),'original_detail':current,'candidate_detail':'detail_low',
        'scope':'Texture detail only; leaves resolution, models, gameplay and sound settings intact'}
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2))
    return manifest
def install(directory,restore=False):
    if find_process() is not None:raise RuntimeError('Stop the game before editing its preferences')
    manifest=json.loads((directory/'manifest.json').read_text());source=source_path()
    if Path(manifest['source']).resolve()!=source.resolve():raise RuntimeError('Unexpected options file')
    original=source.read_bytes()
    if restore:
        # Preserve unrelated preference changes the game may have saved meanwhile.
        incoming,_=replace_detail(original,manifest['original_detail'],'detail_low')
    else:
        if digest(original)!=manifest['original_sha256']:raise RuntimeError('Options changed since preparation')
        incoming=(directory/'candidate_options.set').read_bytes()
        if digest(incoming)!=manifest['candidate_sha256']:raise RuntimeError('Candidate changed')
        expected,_=replace_detail(original,'detail_low',manifest['original_detail'])
        if incoming!=expected:raise RuntimeError('Candidate changes more than texture detail')
    temporary=source.with_name('options.set.texture-experiment.tmp')
    with temporary.open('xb') as output:output.write(incoming)
    if source.read_bytes()!=original:raise RuntimeError('Options changed during installation')
    os.replace(temporary,source)
    if source.read_bytes()!=incoming:raise RuntimeError('Options verification failed')
    (directory/'last_operation.json').write_text(json.dumps({'time':datetime.now().isoformat(),
        'action':'restore' if restore else 'apply','sha256':digest(incoming)},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','apply','restore'])
    p.add_argument('--directory',type=Path);a=p.parse_args()
    if a.action=='prepare':
        directory=a.directory or ROOT/'validation'/datetime.now().strftime('texture_detail_%Y%m%d_%H%M%S')
        print(json.dumps(prepare(directory),indent=2));print(directory)
    else:
        if a.directory is None:p.error('--directory required')
        install(a.directory,a.action=='restore');print(a.action,'verified')
