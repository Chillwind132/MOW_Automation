"""Offline exploratory replay inventory; does not import results or attach to a game.

QM history is found by a text signature, then validated length-prefixed fields.
This is not a complete QM packet decoder and does not guarantee all event types.
Usage: py diagnostics/replay_inventory.py path/to/replay.ss
"""
import _bootstrap
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import struct

from modules.end_game_results.replays import Binary, decode_row, read_replay, section, tree


def history(raw):
    events = []
    for match in re.finditer(rb'<f\(arial_hq', raw):
        offset = match.start()
        for prefix in (1, 4):
            if offset < prefix or (prefix == 4 and raw[offset - 4] != 255):
                continue
            reader = Binary(raw)
            reader.pos = offset - prefix
            try:
                label = reader.string()
                seconds = reader.number('I')
                icon = reader.string()
                if not label.startswith('<f(arial_hq') or not icon.startswith('/interface/scene/controlbar/log/'):
                    continue
                events.append(dict(offset=offset, seconds=seconds,
                                   text=re.sub(r'<[^>]+>', '', label),
                                   icon=icon.rsplit('/', 1)[-1]))
                break
            except (ValueError, UnicodeError, struct.error):
                continue
    return events


def inventory(path):
    replay = read_replay(path)
    events = history(replay['qm'])
    weapons = Counter()
    for event in events:
        match = re.match(r'^(.*?) \{(.*?)\} (.*)$', event['text'])
        if match:
            weapons[(match[1], match[2])] += 1
    nodes = tree(replay['ss'].decode('utf-8-sig'))
    game = decode_row(dict(section(nodes, 'battleInfoTotal'))['game'])
    return dict(path=str(path), map=replay['map'],
                elapsed_wall_seconds=replay['end'] - replay['epoch'],
                extraction='Exploratory signature scan with validated string fields; not a full QM decoder',
                event_counts=dict(Counter(e['icon'] for e in events)),
                weapon_events=[dict(player=p, weapon=w, events=n)
                               for (p, w), n in weapons.most_common()],
                history=events, rows=replay['rows'], game_row=game)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('replays', type=Path, nargs='+')
    args = parser.parse_args()
    print(json.dumps([inventory(path) for path in args.replays], ensure_ascii=True, indent=2))
