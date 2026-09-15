"""Record departure/rejoin evidence without inferring intent or penalties.

Example using durable match metadata and native probe dictionaries:
    from modules.live_game_data import Participation, history
    tracker = Participation(database)
    events = tracker.observe(match, roster_probe, live_probe)
    recorded = history(database, match["match_id"])

Reuse the tracker across polls. observe_controller() integrates this with
snapshots; history() reads saved events without attaching to the game.
"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time
import uuid


def native_reason(flags):
    # Steam LobbyChatUpdate bitfield; lobby membership is not gameplay intent.
    labels=[name for bit,name in ((1,'entered'),(2,'left'),(4,'disconnected'),(8,'kicked'),(16,'banned')) if flags & bit]
    return '+'.join(labels) if labels and not flags & ~31 else 'unknown_flags'


class Participation:
    def __init__(self, path):
        self.path=path
        self.run_id=str(uuid.uuid4())
        with closing(self.connect()) as db,db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS participation_state (
                    match_id TEXT PRIMARY KEY, state_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS participation_events (
                    event_id TEXT PRIMARY KEY, match_id TEXT, steam_id TEXT,
                    observed_at REAL NOT NULL, kind TEXT NOT NULL, evidence_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS participation_by_match ON participation_events(match_id,observed_at);
            ''')

    def connect(self):
        return sqlite3.connect(self.path,timeout=10)

    @staticmethod
    def event(db, mid, steam, now, kind, evidence):
        item=dict(event_id=str(uuid.uuid4()),match_id=mid,steam_id=steam,
                  observed_at=now,kind=kind,evidence=evidence)
        db.execute('INSERT INTO participation_events VALUES (?,?,?,?,?,?)',
                   (item['event_id'],mid,steam,now,kind,json.dumps(evidence,allow_nan=False)))
        return item

    def observe(self, match, roster, live, now=None):
        now=time.time() if now is None else now
        mid=match['match_id']; epoch=match.get('native_game_start_time')
        if (not epoch or roster.get('gameStartTimeRaw')!=epoch
                or roster.get('steamLobbyId')!=match.get('starting_roster',{}).get('steamLobbyId')):
            return [] # Never associate another generation/lobby.
        manager=live.get('managerStateRaw')
        if manager not in (0,1,2,3):
            return [] # An unreadable probe does not mean someone left.
        players=[p for p in match.get('participants',[]) if p.get('role')=='participant'
                 and p.get('controller_kind') in ('remote_human','local_host') and p.get('steam_id')]
        if not players:
            return []
        current={}
        for p in players:
            rows=[r for r in roster.get('rows',[]) if r.get('typeRaw') in (1,4)
                  and str((r['identityWordsRaw'][1]<<32)|r['identityWordsRaw'][0])==p['steam_id']]
            if len(rows)!=1:
                current[p['steam_id']]=dict(status='missing' if not rows else 'ambiguous_identity')
                continue
            row=rows[0]
            slots=[s for s in roster.get('slots',[]) if s.get('memberIdRaw')==row['memberIdRaw']]
            present=row['typeRaw']==1 and len(slots)==1 and slots[0].get('teamRaw')==p['starting_team']
            current[p['steam_id']]=dict(status='present' if present else 'role_or_team_changed',
                                      member_id=row['memberIdRaw'],team=slots[0].get('teamRaw') if len(slots)==1 else None)
        events=[]
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            saved=db.execute('SELECT state_json FROM participation_state WHERE match_id=?',(mid,)).fetchone()
            prior=json.loads(saved[0]) if saved else None
            if prior and prior.get('finished'):
                return []
            def emit(kind,steam=None,**evidence):
                events.append(self.event(db,mid,steam,now,kind,dict(
                    source='native_roster_poll',intent='unknown',penalty_applied=False,
                    native_epoch=epoch,**evidence)))
            if manager==3:
                emit('finish_observed',roster=roster)
                state=dict(finished=True,run_id=self.run_id,last_at=now,players=current)
            else:
                continuous=bool(prior and prior['run_id']==self.run_id and 0<=now-prior['last_at']<=5)
                if not prior:
                    emit('observation_started',roster=roster)
                elif not continuous:
                    emit('observation_gap',previous_observed_at=prior['last_at'],roster=roster)
                for steam,entry in current.items():
                    before=(prior or {}).get('players',{}).get(steam)
                    if before==entry:
                        continue
                    if not continuous:
                        if entry['status']!='present' or before is not None:
                            emit('state_observed_without_continuous_coverage',steam,before=before,after=entry,roster=roster)
                    elif entry['status']=='missing':
                        emit('roster_missing',steam,before=before,after=entry,roster=roster,
                             absent_players=sum(p['status']=='missing' for p in current.values()))
                    elif entry['status']=='present':
                        emit('roster_restored' if before and before['status']!='present' else 'member_binding_changed',
                             steam,before=before,after=entry,roster=roster)
                    else:
                        emit(entry['status'],steam,before=before,after=entry,roster=roster)
                state=dict(finished=False,run_id=self.run_id,last_at=now,players=current)
            db.execute('INSERT INTO participation_state VALUES (?,?) ON CONFLICT(match_id) DO UPDATE SET state_json=excluded.state_json',
                       (mid,json.dumps(state)))
        return events

    def native(self, payload, match=None):
        """Keep the callback even when no active match can safely be associated."""
        mid=None
        if (match and payload.get('lobby_id')==match.get('starting_roster',{}).get('steamLobbyId')
                and payload.get('page_vtable')==0xe2ae58
                and payload.get('manager_state') in (0,1,2)
                and match.get('native_game_start_time')):
            mid=match['match_id']
        flags=payload['flags']
        participant=next((p for p in (match or {}).get('participants',[]) if p.get('steam_id')==payload.get('steam_id')),None)
        starting=(match or {}).get('starting_roster',{})
        host=next((r for r in starting.get('rows',[]) if r.get('memberIdRaw')==starting.get('hostMemberIdRaw')),None)
        host_steam=str((host['identityWordsRaw'][1]<<32)|host['identityWordsRaw'][0]) if host else None
        evidence=dict(payload,reason=native_reason(flags),intent='unknown',penalty_applied=False,
                      participant_role=participant.get('role') if participant else 'unknown',
                      is_starting_host=bool(host_steam and host_steam==payload.get('steam_id')),
                      controller_native_epoch=(match or {}).get('native_game_start_time'),
                      association='active_controller_match_and_same_lobby' if mid else 'unassociated_or_outside_active_play')
        with closing(self.connect()) as db,db:
            return self.event(db,mid,payload.get('steam_id'),time.time(),'steam_lobby_membership',evidence)


def history(database, match_id=None):
    path=Path(database).resolve()
    if not path.is_file():return []
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='participation_events'").fetchone():return []
        where=' WHERE match_id=?' if match_id else ''
        rows=db.execute('SELECT event_id,match_id,steam_id,observed_at,kind,evidence_json FROM participation_events'+where+' ORDER BY observed_at,event_id',
                        (match_id,) if match_id else ()).fetchall()
    return [dict(event_id=r[0],match_id=r[1],steam_id=r[2],observed_at=r[3],kind=r[4],evidence=json.loads(r[5])) for r in rows]


def observe_controller(c, roster, live):
    from .telemetry import record_controller
    record_controller(c,'observe',roster,live)
    # Keep telemetry failures separate from game lifecycle actions.
    try:
        monitor=getattr(c,'participation',None)
        if not isinstance(monitor,Participation):
            monitor=c.participation=Participation(c.journal.path)
        for event in monitor.observe(c.active_match,roster,live):
            c.record('participation',**event)
            record_controller(c,'event','participation_changed',dict(participation_event=event),deduplicate=False)
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as error:
        c.record('participation_capture_error',error=str(error))


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=Path(__file__).resolve().parents[2]/'data/rankbot.sqlite3')
    parser.add_argument('--match-id')
    args=parser.parse_args()
    print(json.dumps(history(args.database,args.match_id),indent=2))


if __name__ == "__main__":
    main()
