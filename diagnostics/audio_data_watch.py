"""Capture external audio evidence at bot-loop phase boundaries."""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
import json
from pathlib import Path
import time
from audio_data_census import scan
from friends_host import Control
from headless_host import ROOT, find_process
from heap_ownership import snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--hours', type=float, default=6)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    control = Control(ROOT/'data/friends_control.sqlite3')
    deadline = time.monotonic()+args.hours*3600
    previous = None
    while time.monotonic() < deadline and not (args.directory.parent/'STOP').exists():
        pid = find_process()
        context = control.status()
        key = (pid, context.get('match_id'), context.get('phase'), context.get('matches_saved'))
        if pid and key != previous and not context.get('stale') and context.get('phase') in (
                'playing', 'ready countdown', 'saving results / returning to lobby'):
            directory = args.directory/f'{pid}_{int(time.time()*1000)}'
            directory.mkdir()
            try:
                snapshot(directory)
                result = scan(directory/'address_space.jsonl', directory/'audio_data.json', seconds=10)
                (directory/'context.json').write_text(json.dumps({'before': context,
                    'after': control.status()}, indent=2), encoding='utf-8')
                print(directory, 'complete', result['completed'], 'buffers', result['unique_buffers'], flush=True)
            except Exception as error:
                (directory/'error.txt').write_text(str(error), encoding='utf-8')
                print('Audio observation failed:', error, flush=True)
            previous = key  # One bounded attempt per transition; never pause the game.
        time.sleep(5)


if __name__ == '__main__':
    main()
