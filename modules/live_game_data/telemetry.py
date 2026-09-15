"""Persist live snapshots for matches already registered in the journal.

Example with durable match metadata and matching roster/live probes:
    from modules.live_game_data import MatchTelemetry
    telemetry = MatchTelemetry(database, interval=5)
    saved = telemetry.observe(match, roster_probe, live_probe)

Reuse the instance across polls; interval is seconds and observe() reports
whether a snapshot was saved. Controllers normally use observe_controller().
"""
from contextlib import closing
import copy
import json
import math
import sqlite3
import threading
import time
import uuid


class MatchTelemetry:
    def __init__(self, database, interval=30):
        if not math.isfinite(interval) or interval<=0:
            raise ValueError('Snapshot interval must be a positive finite number')
        self.database=database
        self.interval=interval
        self.lock=threading.RLock()
        self.samples={}
        self.saved_at={}
        self.events=set()
        with closing(self.connect()) as db,db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS match_snapshots (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id TEXT NOT NULL, recorded_at REAL NOT NULL,
                    sampled_at REAL, reason TEXT NOT NULL, snapshot_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS snapshots_by_match ON match_snapshots(match_id,sequence);
                CREATE TABLE IF NOT EXISTS match_observation_events (
                    event_id TEXT PRIMARY KEY, match_id TEXT NOT NULL,
                    observed_at REAL NOT NULL, kind TEXT NOT NULL, evidence_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS observation_events_by_match
                    ON match_observation_events(match_id,observed_at);
            ''')

    def connect(self):
        db=sqlite3.connect(self.database,timeout=10)
        db.execute('PRAGMA synchronous=FULL')
        return db

    @staticmethod
    def valid_match(match):
        return isinstance(match,dict) and bool(match.get('match_id') and match.get('native_game_start_time'))

    def _snapshot(self, db, match, reason, now):
        mid=match['match_id']
        if not db.execute('SELECT 1 FROM match_journal WHERE match_id=?',(mid,)).fetchone():
            raise ValueError('Progress requires a durable match identity')
        sample=self.samples.get(mid)
        from .statistics import normalize_live_statistics
        statistics=normalize_live_statistics(match,(sample or {}).get('live'))
        snapshot=dict(metadata=match,observation_status='undetermined',
                      sample=sample,per_player_statistics_status=(statistics['status']
                          if statistics['status']!='unavailable' else 'unavailable_in_live_probe'),
                      player_statistics=statistics)
        db.execute('INSERT INTO match_snapshots(match_id,recorded_at,sampled_at,reason,snapshot_json) VALUES (?,?,?,?,?)',
                   (mid,now,sample['observed_at'] if sample else None,reason,json.dumps(snapshot,allow_nan=False)))

    def observe(self, match, roster, live, now=None):
        if not self.valid_match(match):return False
        if (not isinstance(roster,dict) or not isinstance(live,dict)
                or roster.get('gameStartTimeRaw')!=match['native_game_start_time']
                or roster.get('steamLobbyId')!=match.get('starting_roster',{}).get('steamLobbyId')
                or live.get('state',{}).get('pageVtable')!=0xe2ae58
                or live.get('managerStateRaw') not in (0,1,2,3)):
            return False
        now=time.time() if now is None else now
        mid=match['match_id']
        with self.lock:
            self.samples[mid]=copy.deepcopy(dict(observed_at=now,roster=roster,live=live))
            last=self.saved_at.get(mid)
            if last is not None and 0<=now-last<self.interval:return False
            with closing(self.connect()) as db,db:
                self._snapshot(db,match,'observer_attached' if last is None else 'interval',now)
            self.saved_at[mid]=now
        return True

    def event(self, match, kind, evidence, now=None, deduplicate=True):
        if not self.valid_match(match):return False
        now=time.time() if now is None else now
        key=(match['match_id'],kind)
        with self.lock:
            if deduplicate and key in self.events:return False
            with closing(self.connect()) as db,db:
                # This can be older than the event: retain its own sample timestamp.
                self._snapshot(db,match,kind,now)
                db.execute('INSERT INTO match_observation_events VALUES (?,?,?,?,?)',
                    (str(uuid.uuid4()),match['match_id'],now,kind,
                     json.dumps({'source':'controller_observation','cause':'unknown',
                                 'intent':'unknown',**evidence},allow_nan=False)))
            self.saved_at[match['match_id']]=now
            self.events.add(key)
        return True

    def observe_state(self, match, state):
        page=state.get('pageVtable')
        if page==0xe2b2cc:
            self.event(match,'returned_to_lobby',dict(state=state))
        elif page==0xe2a3d0:  # Validated Internet lobby browser; actor is unknown.
            self.event(match,'left_match_session',dict(state=state,
                description='Internet lobby browser observed; host closure, kick or local exit not distinguished'))
        elif state.get('stageVtable')==0xe212f8:
            self.event(match,'left_match_session',dict(state=state,
                description='Main menu observed; closure cause not established'))


def record_controller(c, method, *args, **kwargs):
    """Use existing read-only samples in any controller mode; no additional native calls."""
    match=getattr(c,'active_match',None)
    if not MatchTelemetry.valid_match(match):return
    try:
        monitor=getattr(c,'match_telemetry',None)
        if not isinstance(monitor,MatchTelemetry):
            monitor=c.match_telemetry=MatchTelemetry(c.journal.path)
        return getattr(monitor,method)(match,*args,**kwargs)
    except (OSError,ValueError,KeyError,TypeError,AttributeError,sqlite3.Error) as error:
        c.record('match_telemetry_error',error=str(error))
