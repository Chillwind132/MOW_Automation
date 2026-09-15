"""Passive game-log archive; no injection, game calls, or process restarts."""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
import base64
import json
from pathlib import Path
import re
import time

from headless_host import GAME_LOG
from friends_host import Control


def classify(text):
    labels = []
    if re.search(r'AI Player: Normal \{[^}\r\n]+\}', text):
        labels.append('kill_feed_text')
    if 'CaptureFlag' in text:
        labels.append('flag_ai_message_unverified_capture')
    if 'SpawnUnit ' in text or 'OnGameSpawn ' in text:
        labels.append('unit_spawn_message')
    return labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    control = Control(Path(__file__).resolve().parent.parent/'data/friends_control.sqlite3')
    args.directory.mkdir(parents=True, exist_ok=True)
    position = 0
    generation = 0
    initial = True
    file_identity = None
    with (args.directory/'game_log_stream.jsonl').open('a',encoding='utf-8') as output:
        while True:
            status = control.status()
            try:
                with GAME_LOG.open('rb') as source:
                    import os
                    stat = os.fstat(source.fileno())
                    identity = (stat.st_dev, stat.st_ino)
                    if stat.st_size < position or (file_identity is not None and identity != file_identity):
                        position = 0
                        generation += 1
                        initial = True
                    file_identity = identity
                    source.seek(position)
                    while chunk := source.read(65536):
                        text = chunk.decode('utf-8',errors='replace')
                        item = {'observed_at':time.time(), 'source':str(GAME_LOG),
                            'generation':generation, 'byte_offset':position,
                            'bytes':len(chunk), 'backfill':initial,
                            'controller_match_id_at_read':status.get('match_id'),
                            'controller_phase_at_read':status.get('phase'),
                            'association':'read-time context only; backfill may span matches',
                            'labels':classify(text), 'text':text,
                            'raw_base64':base64.b64encode(chunk).decode('ascii')}
                        output.write(json.dumps(item,ensure_ascii=False)+'\n')
                        output.flush()
                        position += len(chunk)
                initial = False
            except OSError as error:
                output.write(json.dumps({'observed_at':time.time(),'read_error':str(error)})+'\n')
                output.flush()
            if not status.get('running') or status.get('stale'):
                break
            time.sleep(1)


if __name__ == '__main__':
    main()
