"""Read, validate, archive and persist replay finals for engine 3.262.1.

Example inside your own polling loop (no game attachment or UI reads):
    from modules.end_game_results import ReplayImporter
    importer = ReplayImporter(database, profiles=profiles_directory)
    report = importer.poll()  # Call again on later ticks, typically each second.

Reuse the importer: two stable polls and a complete replay pair are required.
profiles_directory contains profile folders, each with replays/<name>/*.ss/.qm.
Report entries identify imported matches or pending files; never fill gaps
from live/UI counters. Use ensure_watcher() for an independent polling process.
"""
import argparse
import base64
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import zlib

SOURCE = 'persisted_replay_battleInfoTotal'
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES = Path.home() / 'Documents/My Games/men of war - assault squad 2/profiles'


def tree(text):
    """Parse the native brace document without interpreting strings as commands."""
    pattern=r'"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+'
    found=list(re.finditer(pattern,text))
    end=0
    for token in found:
        if text[end:token.start()].strip(): raise ValueError('Invalid replay document token')
        end=token.end()
    if text[end:].strip(): raise ValueError('Incomplete replay document token')
    tokens=[m.group() for m in found]
    root, stack = [], []
    current = root
    for token in tokens:
        if token == '{':
            child = []; current.append(child); stack.append(current); current = child
            if len(stack) > 64: raise ValueError('Replay document nesting limit')
        elif token == '}':
            if not stack: raise ValueError('Unbalanced replay document')
            current = stack.pop()
        else:
            current.append(re.sub(r'\\(["\\])', r'\1', token[1:-1]) if token.startswith('"') else token)
    if stack: raise ValueError('Incomplete replay document')
    return root


def section(nodes, key):
    found = [n[1:] for n in nodes if isinstance(n, list) and n and n[0] == key]
    if len(found) != 1: raise ValueError(f'Missing or duplicate replay section: {key}')
    return found[0]


def value(nodes, key):
    values = section(nodes, key)
    if len(values) != 1 or not isinstance(values[0], str):
        raise ValueError(f'Invalid replay value: {key}')
    return values[0]


class Binary:
    def __init__(self, data): self.data, self.pos = data, 0

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data): raise ValueError('Truncated replay statistics')
        out = self.data[self.pos:self.pos+n]; self.pos += n
        return out

    def number(self, fmt): return struct.unpack('<'+fmt, self.take(struct.calcsize('<'+fmt)))[0]

    def string(self):
        size = self.number('B')
        if size == 255: size = int.from_bytes(self.take(3), 'little')
        if size > 65536: raise ValueError('Replay string limit')
        return self.take(size).decode('utf-8')

    def count(self):
        count = self.number('I')
        if count > 100000: raise ValueError('Replay vector limit')
        return count

    def unit(self):
        # 009d48b0: strings + identity + type + five numeric detail fields.
        return [self.string(), self.number('Q'), self.string(), self.number('B'),
                self.string(), self.number('H'), *[self.number('I') for _ in range(5)]]


def unpack(encoded):
    if not encoded.startswith('B64:'): raise ValueError('Unsupported replay encoding')
    compressed = base64.b64decode(encoded[4:], validate=True)
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, 16 * 1024 * 1024)
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('Incomplete or oversized replay statistics')
    return raw


def decode_row(encoded):
    b = Binary(unpack(encoded))
    row = dict(team=b.string(), army=b.string(), key=b.string(), slot=b.number('B'),
               steam_id=str(b.number('Q')), ai=b.number('B'), name=b.string(), member_id=b.number('I'))
    fields = [b.number('i') for _ in range(8)]
    if any(n < 0 for n in fields): raise ValueError('Unsupported negative replay counters')
    row.update(victory_points=fields[0], score=fields[1], flags=fields[2:4],
               infantry=[fields[4], fields[6]], vehicles=[fields[5], fields[7]])
    entries, totals = [], [0, 0]
    for _ in range(b.count()):
        entry = dict(unit=b.string(), label=b.string(), category=b.string(),
                     amount=b.number('f'), cumulative_ordinary=b.number('f'),
                     cumulative_special=b.number('f'), tick=b.number('I'))
        if any(not math.isfinite(entry[k]) or not 0 <= entry[k] <= 2147483647 for k in
               ('amount','cumulative_ordinary','cumulative_special')):
            raise ValueError('Invalid replay resource amount')
        # AD1bf0 accumulates single precision amounts into integer display totals.
        index = int(entry['category'] == 'special')
        if totals[index]+entry['amount']>2147483647: raise ValueError('Replay resource total overflow')
        totals[index] = int(struct.unpack('<f', struct.pack('<f', totals[index] + entry['amount']))[0])
        entries.append(entry)
    row.update(resources=totals, resource_entries=entries)
    row['unit_details'] = [b.unit() for _ in range(b.count())]
    row['top_units'] = [b.unit() for _ in range(b.count())]
    # The native writer reuses its stream buffer; shorter rows can retain bytes
    # from a previous row after the two explicitly counted detail vectors.
    row['unused_buffer_bytes'] = len(b.data)-b.pos
    if row['ai'] not in (0,1): raise ValueError('Invalid replay controller kind')
    return row


def read_replay(path):
    path = Path(path)
    qm = path.with_suffix('.qm')
    before = [(p.stat().st_size, p.stat().st_mtime_ns) for p in (path,qm)]
    if not 0 < before[0][0] <= 16*1024*1024 or not 0 < before[1][0] <= 512*1024*1024:
        raise ValueError('Replay size limit')
    ss, stream = path.read_bytes(), qm.read_bytes()
    if before != [(p.stat().st_size, p.stat().st_mtime_ns) for p in (path,qm)]:
        raise ValueError('Replay is still being written')
    nodes = tree(ss.decode('utf-8-sig'))
    main = section(nodes, 'main')
    if value(main,'version') != '3.262.1': raise ValueError('Unsupported replay engine version')
    epoch = int(value(main,'gameStartTime'), 0)
    end = int(value(main,'gameEndTime'), 0)
    if not epoch or end < epoch: raise ValueError('Replay has no completed end time')
    if (not stream.startswith(b'\xfa\x24\0\0\0'+struct.pack('<I',epoch)+b'\0\0\0\0\x0cREPLAY_BEGIN')
            or not stream.endswith(b'\xff\x24\0\0\0'+struct.pack('<I',end)+b'\0\0\0\0\x0aREPLAY_END')):
        raise ValueError('Replay stream has no matching complete begin/end markers')
    saved = section(nodes,'battleInfoTotal')
    if any(not isinstance(n,list) or len(n)!=2 for n in saved): raise ValueError('Invalid replay results map')
    if len({n[0] for n in saved}) != len(saved): raise ValueError('Duplicate replay result key')
    blobs = dict(saved)
    info = Binary(unpack(blobs.pop('info')))
    info_string = info.string()
    if info.pos != len(info.data): raise ValueError('Unsupported replay info')
    rows = [decode_row(blob) for key,blob in blobs.items() if key != 'game']
    if any(row['key'] != key for key,row in zip((k for k in blobs if k!='game'),rows)):
        raise ValueError('Replay row key mismatch')
    members = []
    for member in section(nodes,'members'):
        kind = value(member,'type')
        if kind not in ('player','bot'): continue
        members.append(dict(member_id=int(value(member,'hostId')), team=value(member,'team'),
                            steam_id=value(member,'steamId'), ai=int(kind=='bot')))
    players = [r for r in rows if r['slot'] != 255]
    if not players or len(players)!=len(members): raise ValueError('Incomplete replay participants')
    if (len({m['member_id'] for m in members})!=len(members)
            or len({r['member_id'] for r in players})!=len(players)
            or any(r['slot']>=18 or r['team'] not in ('a','b') for r in players)):
        raise ValueError('Duplicate or unsupported replay participants')
    humans=[r['steam_id'] for r in players if not r['ai']]
    if len(set(humans))!=len(humans) or any(not re.fullmatch(r'7656119\d{10}',s) for s in humans):
        raise ValueError('Invalid or duplicate replay Steam identity')
    for member in members:
        matches = [r for r in players if r['member_id']==member['member_id']]
        if len(matches)!=1 or any(matches[0][k]!=v for k,v in member.items()):
            raise ValueError('Replay member identity mismatch')
    teams = [r for r in rows if r['slot']==255]
    if {r['key'] for r in teams}!={'a','b'} or len(teams)!=2: raise ValueError('Incomplete replay teams')
    return dict(epoch=epoch,end=end,map=value(main,'map'),mods=value(main,'mods'),rows=rows,
                info_raw=info_string,ss=ss,qm=stream,path=str(path.resolve()),
                ss_sha256=hashlib.sha256(ss).hexdigest(),qm_sha256=hashlib.sha256(stream).hexdigest())


def normalize(replay, match):
    roster=match.get('loaded_roster') or match.get('starting_roster') or {}
    if int(str(match.get('native_game_start_time')),0)!=replay['epoch'] or (match.get('map') or roster.get('map'))!=replay['map']:
        raise ValueError('Replay does not match recorded generation/map')
    people = [p for p in match.get('participants',[]) if p['role']=='participant']
    native = [r for r in replay['rows'] if r['slot']!=255]
    if len(people)!=len(native): raise ValueError('Replay participant count differs from recorded match')
    if (len({p['native_member_id'] for p in people})!=len(people)
            or len({p['participant_key'] for p in people})!=len(people)):
        raise ValueError('Duplicate recorded participant identity')
    bindings = {}
    for p in people:
        rows = [r for r in native if r['member_id']==p['native_member_id']]
        if len(rows)!=1: raise ValueError('Replay member association missing or ambiguous')
        r = rows[0]
        if (r['steam_id'] != (p['steam_id'] or '0') or r['team']!=p['starting_team']
                or bool(r['ai'])!=(p['controller_kind']=='ai')):
            raise ValueError('Replay identity/team differs from recorded match')
        bindings[r['key']] = p
    from .legacy import cell
    rows = []
    for r in replay['rows']:
        team = r['slot']==255
        fields = {'player':cell(r['name']), 'victory_points':cell(str(r['victory_points'])) if team else None,
                  'score':cell(str(r['score']))}
        for field in ('infantry','vehicles','resources'):
            fields[field] = None if team and field=='resources' else cell(' / '.join(map(str,r[field])))
        entry = dict(row_id='t'+r['key'] if team else 'p'+r['key'],kind='team' if team else 'player',
                     steam_id=None,fields=fields,army=r['army'],native_member_id=r['member_id'])
        if not team:
            p = bindings[r['key']]
            entry.update(participant_key=p['participant_key'],steam_id=p['steam_id'],
                         controller_kind=p['controller_kind'],identity_source='replay_member_id_steam_kind_team_and_recorded_epoch')
        rows.append(entry)
    # BC4020/BC5060 persist/restore collection's outcome row key. BC3F90
    # resolves that key; BC4360 -> BC4880 gives that team's rating outcome 1
    # and the opposite team's 0. It is independent of the VP leader.
    winner=replay['info_raw'] if replay['info_raw'] in ('a','b') else None
    outcome=dict(winning_team=winner,source='replay_battleInfoTotal_info') if winner else None
    return dict(schema_version=3,source=SOURCE,rows=rows,engine_outcome=outcome,
                outcome_status='recorded_replay_outcome' if winner else 'no_supported_replay_outcome',
                replay=dict(ss_sha256=replay['ss_sha256'],qm_sha256=replay['qm_sha256'],
                            game_start_time=replay['epoch'],game_end_time=replay['end'],info_raw=replay['info_raw']),
                paired_counter_meanings=dict(infantry=['enemy_kills','losses'],vehicles=['enemy_kills','losses'],
                                             resources=['ordinary','special']))


def candidates(database):
    records = {}
    with closing(sqlite3.connect(database)) as db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table,column in (('match_journal','snapshot_json'),('matches','observation_json')):
            if table in tables:
                for mid,encoded in db.execute(f'SELECT match_id,{column} FROM {table}'):
                    records.setdefault(mid,{}).update(json.loads(encoded))
        if 'lifecycle_observations' in tables:
            for mid,encoded in db.execute('SELECT match_id,evidence_json FROM lifecycle_observations ORDER BY sequence'):
                evidence=json.loads(encoded)
                if mid in records and isinstance(evidence,dict) and evidence.get('match_id')==mid:
                    records[mid].update(evidence)
    return list(records.values())


def replay_metadata(replay):
    """A replay can stand alone when no controller observed its start."""
    players=[r for r in replay['rows'] if r['slot']!=255]
    identity=json.dumps([replay['epoch'],replay['map'],sorted(
        (r['member_id'],r['steam_id'],r['team'],r['ai']) for r in players)],separators=(',',':'))
    mid=str(uuid.uuid5(uuid.NAMESPACE_URL,'mow-replay:'+identity))
    people=[dict(participant_key=('ai:'+mid+':'+r['key']) if r['ai'] else r['steam_id'],
                 native_member_id=r['member_id'],steam_id=None if r['ai'] else r['steam_id'],
                 controller_kind='ai' if r['ai'] else 'remote_human',role='participant',
                 starting_team=r['team'],display_name=r['name'],nation=r['army']) for r in players]
    return dict(match_id=mid,hosting_mode='replay_import',native_game_start_time=hex(replay['epoch']),
                created_at=replay['epoch'],map=replay['map'],mods=replay['mods'],participants=people,
                starting_roster_source='persisted_replay',trigger='replay_import',engine_outcome=None)


def publish(database, replay, match):
    """Atomically promote replay authority, retaining superseded UI evidence."""
    result = normalize(replay,match)
    metadata = dict(match, final_results_source=SOURCE, engine_outcome=result['engine_outcome'],
                    results_observed_at=replay['end'], replay=result['replay'])
    from headless.match_journal import canonical
    encoded = canonical(result)
    archive = Path(database).parent/'replays'/replay['ss_sha256']
    archive.mkdir(parents=True,exist_ok=True)
    for suffix in ('ss','qm'):
        target=archive/('replay.'+suffix)
        if target.exists():
            if target.read_bytes()!=replay[suffix]: raise ValueError('Replay archive hash conflict')
        else:
            temporary=None
            try:
                with tempfile.NamedTemporaryFile(dir=archive,delete=False) as output:
                    temporary=Path(output.name)
                    output.write(replay[suffix]);output.flush();os.fsync(output.fileno())
                os.replace(temporary,target)
            finally:
                if temporary is not None:temporary.unlink(missing_ok=True)
    raw = dict(source=SOURCE,original_path=replay['path'],archive=str(archive),
               decoded_rows=replay['rows'],replay=result['replay'])
    with closing(sqlite3.connect(database,timeout=10)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS matches (match_id TEXT PRIMARY KEY, observation_json TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS results (match_id TEXT PRIMARY KEY, normalized_json TEXT NOT NULL, raw_json TEXT NOT NULL)')
        db.execute('''CREATE TABLE IF NOT EXISTS superseded_results (
            match_id TEXT PRIMARY KEY, observation_json TEXT NOT NULL, normalized_json TEXT NOT NULL,
            raw_json TEXT NOT NULL, superseded_at REAL NOT NULL)''')
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT normalized_json,raw_json FROM results WHERE match_id=?',(match['match_id'],)).fetchone()
        if old and json.loads(old[0]).get('source')==SOURCE:
            if canonical(json.loads(old[0]))!=encoded: raise ValueError('Conflicting persisted replays for match')
            created=False
        else:
            if old:
                prior=db.execute('SELECT observation_json FROM matches WHERE match_id=?',(match['match_id'],)).fetchone()[0]
                db.execute('INSERT INTO superseded_results VALUES (?,?,?,?,?)',(match['match_id'],prior,*old,time.time()))
            db.execute('INSERT INTO matches VALUES (?,?) ON CONFLICT(match_id) DO UPDATE SET observation_json=excluded.observation_json',
                       (match['match_id'],canonical(metadata)))
            db.execute('INSERT INTO results VALUES (?,?,?) ON CONFLICT(match_id) DO UPDATE SET normalized_json=excluded.normalized_json,raw_json=excluded.raw_json',
                       (match['match_id'],encoded,canonical(raw)))
            created=True
    from headless.match_ratings import refresh
    refresh(database)
    return created


class ReplayImporter:
    def __init__(self,database,profiles=DEFAULT_PROFILES):
        self.database,self.profiles=Path(database),Path(profiles)
        self.observed,self.done={},set()

    def poll(self):
        report=[]
        matches=candidates(self.database)
        for path in self.profiles.glob('*/replays/*/*.ss'):
            try:
                pair=(path,path.with_suffix('.qm'))
                signature=tuple((p.stat().st_size,p.stat().st_mtime_ns) for p in pair)
                key=(str(path),signature)
                if key in self.done: continue
                if self.observed.get(str(path))!=signature:
                    self.observed[str(path)]=signature
                    continue # Require two separate stable polls as well as complete stream footer.
                replay=read_replay(path)
                associated=[m for m in matches if str(m.get('native_game_start_time')).lower()==hex(replay['epoch'])]
                if len(associated)>1: raise ValueError('Ambiguous recorded native generation for replay')
                match=associated[0] if associated else replay_metadata(replay)
                created=publish(self.database,replay,match)
                self.done.add(key)
                report.append(dict(path=str(path),match_id=match['match_id'],created=created))
            except (OSError,ValueError,KeyError,UnicodeError,zlib.error,struct.error) as error:
                report.append(dict(path=str(path),pending=str(error)))
        return report


def load_result(database,match_id):
    """Return an authoritative replay result, or None without creating a database."""
    path=Path(database).resolve()
    if not path.is_file(): return None
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)) as db:
        table=db.execute("SELECT 1 FROM sqlite_master WHERE name='results'").fetchone()
        row=db.execute('SELECT normalized_json FROM results WHERE match_id=?',(match_id,)).fetchone() if table else None
    result=json.loads(row[0]) if row else None
    return result if result and result.get('source')==SOURCE else None


def wait_for_match(database,match,timeout=30):
    importer=ReplayImporter(database)
    deadline=time.monotonic()+timeout
    while True:
        importer.poll()
        saved=load_result(database,match['match_id'])
        if saved: return saved
        if time.monotonic()>=deadline: raise TimeoutError('Complete matching replay not available; final results pending')
        time.sleep(1)


def ensure_watcher(database):
    """Independent singleton survives the game/controller so late replays are read."""
    database=Path(database).resolve()
    database.parent.mkdir(parents=True,exist_ok=True)
    with (database.parent/'replay_importer.log').open('a',encoding='utf-8') as log:
        subprocess.Popen([sys.executable,'-m','modules.end_game_results','--database',str(database),'--watch'],
                         cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),close_fds=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=ROOT/'data/rankbot.sqlite3')
    parser.add_argument('--profiles',type=Path,default=DEFAULT_PROFILES)
    parser.add_argument('--watch',action='store_true')
    parser.add_argument('--stop',action='store_true',help='Stop the persistent replay watcher; no game action')
    args=parser.parse_args()
    stop=args.database.parent/'replay_importer.stop'
    if args.stop:
        stop.write_text('stop',encoding='utf-8'); return
    lock=None
    if args.watch:
        from headless.match_journal import ProcessLock
        try: lock=ProcessLock(args.database.parent/'controller_locks',dict(replay_watcher=str(args.database.resolve())))
        except RuntimeError: return
        stop.unlink(missing_ok=True)
        print(json.dumps(dict(replay_watcher_pid=os.getpid(),database=str(args.database))),flush=True)
    importer=ReplayImporter(args.database,args.profiles)
    try: importer.poll()
    except (OSError,sqlite3.Error): pass  # Retry transient startup I/O in the normal reporting loop.
    time.sleep(1)
    previous=None
    while True:
        if args.watch and stop.exists(): break
        try: report=importer.poll()
        except (OSError,sqlite3.Error) as error: report=[dict(pending=str(error))]
        if report and report!=previous: print(json.dumps(report),flush=True)
        previous=report
        if not args.watch: break
        time.sleep(1)


if __name__=='__main__': main()
