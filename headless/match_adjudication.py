"""Explicit manual outcomes, kept separately from captured match evidence."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time
import uuid


class ConflictError(ValueError):
    pass


def read_adjudications(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='match_adjudications'").fetchone():return {}
    return {mid:json.loads(payload) for mid,payload in db.execute('SELECT match_id,adjudication_json FROM match_adjudications')}


def save_adjudication(database, match_id, winning_team, reason, robz=False):
    if not isinstance(match_id,str) or not 1<=len(match_id)<=128:raise ValueError('Match ID required')
    if winning_team not in ('a','b'):raise ValueError('Select Team A or Team B')
    if not isinstance(reason,str) or not 1<=len(reason.strip())<=2000:raise ValueError('Enter a reason (1–2000 characters)')
    if not isinstance(robz,bool):raise ValueError('Robz confirmation must be true or false')
    from match_ratings import POOL,read_inputs,refresh_connection
    from match_review import load_matches
    reason=reason.strip();pool=POOL if robz else None
    path=Path(database).resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=10)) as db,db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        existing=read_adjudications(db).get(match_id)
        if existing:
            if (existing['winning_team'],existing['reason'],existing.get('pool'))!=(winning_team,reason,pool):
                raise ConflictError('This match already has a manual decision; the original is preserved')
            decision=existing
        else:
            match=next((m for m in load_matches(path) if m['id']==match_id),None)
            if match is None:raise ValueError('Match not found')
            if match['winner']:raise ConflictError('This match already has a confirmed winner')
            # A final capture can exist alongside a lobby export that lacks a winner.
            record=next((r for r in read_inputs(db) if r['id']==match_id),{})
            from match_outcomes import automatic_winner
            for source, metadata_key in (('finish','metadata'),('lobby','lobby_metadata')):
                if record.get(source) and automatic_winner(record[source],record.get(metadata_key) or record.get('metadata',{}),path):
                    raise ConflictError('A completed winning result already exists for this match')
            decision=dict(adjudication_id=str(uuid.uuid4()),match_id=match_id,
                winning_team=winning_team,reason=reason,pool=pool,confirmed_at=time.time(),
                source='explicit_user_confirmation',entry_point='local_match_review')
            db.execute('CREATE TABLE IF NOT EXISTS match_adjudications (match_id TEXT PRIMARY KEY,adjudication_json TEXT NOT NULL)')
            db.execute('INSERT INTO match_adjudications VALUES (?,?)',(match_id,json.dumps(decision,sort_keys=True)))
        # Declaration, immutable audit and rating publication commit or roll back together.
        ratings=refresh_connection(db)
        return dict(decision=decision,rating=ratings['matches'].get(match_id,{'status':'incomplete_result_identities'}))
