"""Durable intent and conservative recovery. Native calls are never replayed here."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class ProcessLock:
    """Windows kernel releases this byte lock even when the controller crashes."""
    def __init__(self, directory, identity):
        import msvcrt
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.file = (directory / (fingerprint(identity) + '.lock')).open('a+b')
        try:
            self.file.seek(0, 2)
            if not self.file.tell():
                self.file.write(b'0')
                self.file.flush()
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        except BaseException:
            self.file.close()
            raise RuntimeError('Another controller owns this game process')

    def close(self):
        self.file.close()


class Journal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 2:
                raise RuntimeError('Unsupported newer journal schema')
            if version == 0:
                # SQLite backup includes committed WAL data; preserve historical results verbatim.
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    backup = self.path.with_name(self.path.name + '.pre-journal-' + uuid.uuid4().hex + '.bak')
                    with closing(sqlite3.connect(backup)) as target:
                        db.backup(target)
                with db:
                    db.executescript('''
                        BEGIN IMMEDIATE;
                        CREATE TABLE IF NOT EXISTS process_instances (
                            process_key TEXT PRIMARY KEY, identity_json TEXT NOT NULL);
                        CREATE TABLE IF NOT EXISTS hosting_sessions (
                            session_id TEXT PRIMARY KEY, process_key TEXT NOT NULL,
                            native_json TEXT NOT NULL, created_at REAL NOT NULL);
                        CREATE TABLE IF NOT EXISTS match_journal (
                            match_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                            generation INTEGER NOT NULL, state TEXT NOT NULL,
                            snapshot_json TEXT NOT NULL, created_at REAL NOT NULL,
                            UNIQUE(session_id,generation));
                        CREATE TABLE IF NOT EXISTS command_journal (
                            request_id TEXT PRIMARY KEY, process_key TEXT NOT NULL,
                            match_id TEXT, action TEXT NOT NULL, status TEXT NOT NULL,
                            intent_json TEXT NOT NULL, evidence_json TEXT, updated_at REAL NOT NULL);
                        CREATE TABLE IF NOT EXISTS lifecycle_observations (
                            sequence INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT,
                            observed_at REAL NOT NULL, evidence_json TEXT NOT NULL);
                        PRAGMA user_version=1;
                        COMMIT;
                    ''')
            if db.execute('PRAGMA user_version').fetchone()[0]<2:
                backup=self.path.with_name(self.path.name+'.pre-completion-'+uuid.uuid4().hex+'.bak')
                with closing(sqlite3.connect(backup)) as target:
                    db.backup(target)
                with db:
                    db.execute('''CREATE TABLE IF NOT EXISTS completion_captures (
                        match_id TEXT PRIMARY KEY, normalized_json TEXT NOT NULL,
                        raw_json TEXT NOT NULL, evidence_json TEXT NOT NULL, captured_at REAL NOT NULL)''')
                    db.execute('PRAGMA user_version=2')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        return db

    def save_completion(self, match_id, normalized, raw, evidence):
        encoded=canonical(normalized)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT normalized_json FROM completion_captures WHERE match_id=?',(match_id,)).fetchone()
            if row:
                if row[0]!=encoded:
                    raise RuntimeError('Conflicting completion capture; original preserved')
                return False
            if not db.execute('SELECT 1 FROM match_journal WHERE match_id=?',(match_id,)).fetchone():
                raise RuntimeError('Completion requires a durable match identity')
            db.execute('INSERT INTO completion_captures VALUES (?,?,?,?,?)',(match_id,encoded,canonical(raw),canonical(evidence),time.time()))
            return True

    def register(self, identity, native):
        key = fingerprint(identity)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO process_instances VALUES (?,?)', (key, canonical(identity)))
            rows = db.execute('SELECT * FROM hosting_sessions WHERE process_key=? ORDER BY created_at DESC', (key,)).fetchall()
            if rows and rows[0]['native_json'] == canonical(native):
                return key, rows[0]['session_id']
            session_id = str(uuid.uuid4())
            db.execute('INSERT INTO hosting_sessions VALUES (?,?,?,?)', (session_id,key,canonical(native),time.time()))
            return key, session_id

    def new_match(self, session_id, snapshot, match_id=None):
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM match_journal WHERE session_id=? AND state NOT IN ('lobby_returned','failed')", (session_id,)).fetchone():
                raise RuntimeError('Active match requires reconciliation before another Start')
            generation = db.execute('SELECT COALESCE(MAX(generation),0)+1 FROM match_journal WHERE session_id=?', (session_id,)).fetchone()[0]
            match_id = match_id or str(uuid.uuid4())
            db.execute('INSERT INTO match_journal VALUES (?,?,?,?,?,?)', (match_id, session_id,generation,'lobby',canonical(snapshot),time.time()))
            return match_id

    def request(self, process_key, match_id, action, intent, request_id=None):
        request_id = request_id or str(uuid.uuid4())
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM command_journal WHERE request_id=?',(request_id,)).fetchone():
                raise RuntimeError('Duplicate command ID; reconcile without replay')
            if db.execute("SELECT 1 FROM command_journal WHERE process_key=? AND status IN ('requested','executing','unknown')",(process_key,)).fetchone():
                raise RuntimeError('Unresolved native command; needs_reconciliation')
            db.execute('INSERT INTO command_journal VALUES (?,?,?,?,?,?,?,?)',
                       (request_id,process_key,match_id,action,'requested',canonical(intent),None,time.time()))
        return request_id

    def command_state(self, request_id, status, evidence=None):
        allowed = {'requested':{'executing','failed'}, 'executing':{'observed-complete','failed','unknown'},
                   'unknown':{'observed-complete','failed'}}
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT status FROM command_journal WHERE request_id=?',(request_id,)).fetchone()
            if not old or status not in allowed.get(old[0],set()):
                raise RuntimeError('Invalid or out-of-order command transition')
            db.execute('UPDATE command_journal SET status=?,evidence_json=?,updated_at=? WHERE request_id=?',
                       (status,canonical(evidence),time.time(),request_id))

    def transition(self, match_id, expected, state, evidence):
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE match_journal SET state=? WHERE match_id=? AND state=?',(state,match_id,expected)).rowcount
            if changed != 1:
                raise RuntimeError('Stale lifecycle transition')
            db.execute('INSERT INTO lifecycle_observations(match_id,observed_at,evidence_json) VALUES (?,?,?)',
                       (match_id,time.time(),canonical(evidence)))

    def archived_completion_results(self, process_key, session_id, match_id, observation):
        """Recover already-captured final statistics; never dismiss or replay UI actions."""
        record = self.inspect(process_key)
        active = [m for m in record['matches'] if m['state'] not in ('lobby_returned', 'failed')]
        if (len(active) != 1 or active[0]['match_id'] != match_id or
                active[0]['state'] not in ('results_available', 'results_saved') or
                observation.get('lobby_loaded') is not True or observation.get('loaded') is not False or
                observation.get('results_visible') is not False):
            raise RuntimeError('Hidden results recovery requires a completed match in the lobby')
        # Reuse all process/session/generation and unresolved-command checks.
        decision = reconcile(record, process_key, session_id, dict(observation, results_visible=True))
        if decision['status'] != 'results_available':
            raise RuntimeError('Hidden results identity is not reconciled')
        with closing(self.connect()) as db:
            completion = db.execute('SELECT raw_json,captured_at FROM completion_captures WHERE match_id=?',
                                    (match_id,)).fetchone()
            commands = [dict(r) for r in db.execute('''SELECT * FROM command_journal
                WHERE process_key=? AND match_id=? AND action IN ('exit-completed','results')
                ORDER BY updated_at DESC''', (process_key, match_id))]
        exit_command = next((r for r in commands if r['action'] == 'exit-completed'), None)
        result_command = next((r for r in commands if r['action'] == 'results'), None)
        if not completion or not exit_command or not result_command:
            raise RuntimeError('Hidden results require durable completion, exit and statistics captures')
        epoch = observation.get('native_game_start_time')
        terminal = json.loads(completion['raw_json'])
        exit_intent = json.loads(exit_command['intent_json'])
        if (terminal.get('match_id') != match_id or terminal.get('native_game_start_time') != epoch or
                exit_intent.get('controlled', {}).get('epoch') != epoch or
                not completion['captured_at'] <= exit_command['updated_at'] <= result_command['updated_at'] or
                any(r['status'] != 'observed-complete' or json.loads(r['evidence_json']).get('ok') is not True
                    for r in (exit_command, result_command))):
            raise RuntimeError('Hidden results lack an observed normal completion sequence')
        evidence = json.loads(result_command['evidence_json'])
        state = evidence.get('state', {})
        if (not isinstance(evidence.get('probe'), dict) or
                any(not observation.get(k) or state.get(k) != observation[k] for k in ('session', 'card'))):
            raise RuntimeError('Archived statistics came from a different native lobby')
        return dict(evidence['probe'], state=state, observed_at=result_command['updated_at']), {
            'source': 'durable_statistics_after_observed_completion_exit',
            'exit_request_id': exit_command['request_id'], 'results_request_id': result_command['request_id']}

    def inspect(self, process_key):
        with closing(self.connect()) as db:
            matches=[dict(r) for r in db.execute('''SELECT m.* FROM match_journal m
                JOIN hosting_sessions s USING(session_id) WHERE s.process_key=? ORDER BY m.created_at''',(process_key,))]
            for match in matches:
                match['latest_match_observation']=json.loads(match['snapshot_json'])
                for row in db.execute('SELECT evidence_json FROM lifecycle_observations WHERE match_id=? ORDER BY sequence',(match['match_id'],)):
                    evidence=json.loads(row[0])
                    if isinstance(evidence,dict) and evidence.get('match_id')==match['match_id']:
                        match['latest_match_observation'].update(evidence)
            return {'matches':matches,'unresolved_commands':[dict(r) for r in db.execute("SELECT * FROM command_journal WHERE process_key=? AND status IN ('requested','executing','unknown')",(process_key,))]}


def reconcile(record, process_key, session_id, observation):
    """Return a decision, never a native mutation. Pointers/roster/scores aren't freshness proof."""
    if not observation.get('process_alive', True):
        return {'status':'process_exited','match_id':None,'may_mutate':False}
    if observation.get('process_key') != process_key or observation.get('session_id') != session_id:
        return {'status':'needs_reconciliation','reason':'process_or_session_changed','may_mutate':False}
    active = [m for m in record['matches'] if m['state'] not in ('lobby_returned','failed')]
    if record['unresolved_commands'] or len(active) > 1:
        return {'status':'needs_reconciliation','reason':'unresolved_command_or_generation','may_mutate':False}
    if not active:
        return {'status':'unassociated_results' if observation.get('results_visible') else 'idle',
                'match_id':None,'may_mutate':not observation.get('results_visible',False)}
    match = active[0]
    if match['session_id'] != session_id:
        return {'status':'needs_reconciliation','reason':'session_changed','may_mutate':False}
    epoch=match.get('latest_match_observation',{}).get('native_game_start_time')
    if not epoch or epoch!=observation.get('native_game_start_time'):
        return {'status':'needs_reconciliation','reason':'native_match_generation_unproven','may_mutate':False}
    # Continuing observation is safe; ambiguous results never authorize cleanup.
    if observation.get('loaded') and match['state'] in ('loading','playing'):
        return {'status':'playing','match_id':match['match_id'],'may_mutate':False}
    if observation.get('loaded') and match['state']=='completion_observed':
        return {'status':'completion_observed','match_id':match['match_id'],'may_mutate':False}
    if observation.get('lobby_loaded') and observation.get('replay_saved') and match['state'] in ('results_available','results_saved'):
        return {'status':'results_available','match_id':match['match_id'],'may_mutate':False,
                'association':'persisted_replay_and_unchanged_native_epoch'}
    if observation.get('results_visible') and match['state'] in ('playing','completion_observed','exit_requested','results_available','results_saved'):
        return {'status':'results_available','match_id':match['match_id'],'may_mutate':False,
                'association':'durable_loaded_match_and_unchanged_native_epoch'}
    return {'status':'needs_reconciliation','match_id':match['match_id'],'may_mutate':False}
