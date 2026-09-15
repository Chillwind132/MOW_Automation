"""Versioned two-team TrueSkill fallback. No fitted TrueSkill 2 score model yet.

Rebuilds are small, chronological, immutable snapshots; one transaction publishes
all players. Raw match evidence is never rewritten by the rating subsystem.
"""
from contextlib import closing
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from statistics import NormalDist

VERSION = 'robz-outcome-v1'
POOL = 'robz-battle-zones'
PARAMETERS = dict(mu=25.0, sigma=25/3, beta=25/6, tau=25/300,
                  draw_probability=0, display_center=1000, display_scale=40,
                  provisional_sigma=6.0, performance_model=None)
# User identified these two historical games as eligible Robz matches on 2026-09-05.
# This is an explicit historical attestation, not inferred native mod telemetry.
HISTORICAL_ROBZ = {
    'b85905e2-e9f6-42c9-a0cb-72861b5e07a3': 'multi/8v8_river_valley:battle_zones',
    '871cf553-558f-4959-bfc7-2e4d227a470d': 'multi/6v6_kalinina:battle_zones',
}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def display(mu=25.0, sigma=25/3, games=0):
    return dict(mu=mu, sigma=sigma, games=games, value=1000+40*(mu-25),
                provisional=sigma > PARAMETERS['provisional_sigma'])


def update(teams, ratings, winner):
    """Exact Gaussian moment update for two teams, decisive result, no draw margin."""
    if winner not in ('a', 'b') or not teams['a'] or len(teams['a']) != len(teams['b']):
        raise ValueError('Require a decisive equal-team result')
    ids = teams['a'] + teams['b']
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate player')
    prior = {s: ratings.get(s, display()) for s in ids}
    variance = {s: prior[s]['sigma']**2 + PARAMETERS['tau']**2 for s in ids}
    c = math.sqrt(math.fsum(variance.values()) + len(ids)*PARAMETERS['beta']**2)
    delta = math.fsum(prior[s]['mu'] for s in teams['a']) - math.fsum(prior[s]['mu'] for s in teams['b'])
    probability = NormalDist().cdf(delta/c)
    t = delta/c * (1 if winner == 'a' else -1)
    # Stable inverse Mills ratio in the extreme upset tail (CDF underflows there).
    if t < -10:
        x = -t
        v = x + 1/x - 2/x**3 + 10/x**5 - 74/x**7
        w = 1 - 1/x**2 + 6/x**4 - 50/x**6
    else:
        v = math.exp(-t*t/2)/math.sqrt(2*math.pi)/(0.5*math.erfc(-t/math.sqrt(2)))
        w = v*(v+t)
    output = {}
    for team in ('a', 'b'):
        for s in sorted(teams[team]):
            p = prior[s]
            mu = p['mu'] + (1 if team == winner else -1)*variance[s]/c*v
            sigma = math.sqrt(variance[s]*max(1e-12, 1-variance[s]/c**2*w))
            if not math.isfinite(mu) or not math.isfinite(sigma):
                raise ValueError('Non-finite rating')
            output[s] = dict(before=p, after=display(mu, sigma, p['games']+1), team=team)
    return probability, output


def read_inputs(db):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    records = {}
    if {'match_journal', 'completion_captures'} <= tables:
        for mid, snapshot, result in db.execute('SELECT j.match_id,j.snapshot_json,c.normalized_json FROM match_journal j JOIN completion_captures c USING(match_id)'):
            records[mid] = dict(id=mid, metadata=json.loads(snapshot), finish=json.loads(result))
        columns = {r[1] for r in db.execute('PRAGMA table_info(completion_captures)')}
        if 'evidence_json' in columns:
            for mid, evidence in db.execute('SELECT match_id,evidence_json FROM completion_captures'):
                if mid in records:
                    records[mid]['finish_roster'] = (json.loads(evidence) or {}).get('roster')
    if {'matches', 'results'} <= tables:
        for mid, observation, result in db.execute('SELECT m.match_id,m.observation_json,r.normalized_json FROM matches m JOIN results r USING(match_id)'):
            record = records.setdefault(mid, dict(id=mid, metadata=json.loads(observation)))
            record['lobby'] = json.loads(result)
            record['lobby_metadata'] = json.loads(observation)
            if record['lobby'].get('source') == 'persisted_replay_battleInfoTotal':
                # Replay is authoritative, including an unavailable outcome.
                record.pop('finish',None)
                record.pop('finish_roster',None)
                record['metadata']=record['lobby_metadata']
    from headless.match_outcomes import final_vp
    database = next((row[2] for row in db.execute('PRAGMA database_list') if row[1]=='main'), None)
    for record in records.values():
        for result_key, metadata_key in (('finish','metadata'),('lobby','lobby_metadata')):
            if record.get(result_key):
                metadata = dict(record.get(metadata_key) or record['metadata'])
                metadata['_final_vp'] = final_vp(record[result_key],metadata,database)
                record[metadata_key] = metadata
        primary = record.get('finish') or record.get('lobby') or {}
        record['metadata'] = dict(record['metadata'],_final_vp=final_vp(primary,record['metadata'],database))
    from headless.match_adjudication import read_adjudications
    for mid,decision in read_adjudications(db).items():
        if mid not in records and 'match_snapshots' in tables:
            row=db.execute('SELECT snapshot_json FROM match_snapshots WHERE match_id=? ORDER BY sequence DESC LIMIT 1',(mid,)).fetchone()
            if row:records[mid]=dict(id=mid,metadata=json.loads(row[0])['metadata'])
        if mid in records:
            records[mid]['metadata']=dict(records[mid]['metadata'],operator_adjudication=decision)
    return sorted(records.values(), key=lambda r: (r['metadata'].get('created_at') or r['metadata'].get('loaded_at') or 0, r['id']))


def result_signature(result):
    return sorted((r.get('participant_key') or r.get('steam_id') or r.get('row_id'),
                   r.get('steam_id'), encoded({k: (r.get('fields', {}).get(k) or {}).get('values_in_display_order')
                       for k in ('score', 'victory_points', 'infantry', 'vehicles')}))
                  for r in result.get('rows', []))


def classify(record):
    m = record['metadata']; result = record.get('finish') or record.get('lobby') or {}
    from headless.match_outcomes import automatic_winner
    winner = automatic_winner(result,m)
    attestation = m.get('operator_adjudication') or {}
    adjudicated = (attestation.get('source') == 'explicit_user_confirmation'
                   and attestation.get('match_id') == record['id']
                   and attestation.get('winning_team') in ('a', 'b'))
    if adjudicated:
        if winner not in (None, attestation['winning_team']):
            return 'conflicting_captures', None
        winner = attestation['winning_team']
    if winner not in ('a', 'b'):
        return 'no_confirmed_winner', None
    if not adjudicated and not record.get('finish') and m.get('trigger') != 'normal_completion_observed':
        return 'no_natural_finish', None
    roster = m.get('loaded_roster') or m.get('starting_roster') or {}
    map_id = m.get('map') or roster.get('map') or ''
    if not map_id.endswith(':battle_zones'):
        return 'unsupported_mode', None
    people = m.get('participants') or []
    players = [p for p in people if p.get('role') != 'spectator']
    if not players or any(p.get('role') != 'participant' or p.get('controller_kind') not in ('remote_human', 'local_host') for p in players):
        return 'nonhuman_or_unknown_participant', None
    ids = [p.get('steam_id') for p in players]
    if any(not re.fullmatch(r'7656119\d{10}', s or '') for s in ids) or len(set(ids)) != len(ids):
        return 'invalid_or_duplicate_identity', None
    teams = {t: sorted(p['steam_id'] for p in players if p.get('starting_team') == t) for t in ('a', 'b')}
    if not teams['a'] or len(teams['a']) != len(teams['b']) or len(teams['a'])*2 != len(players):
        return 'unequal_or_unknown_teams', None
    rows = [r for r in result.get('rows', []) if r.get('kind') == 'player']
    if len(rows) != len(ids) or {r.get('steam_id') for r in rows} != set(ids):
        return 'incomplete_result_identities', None
    for p in players:
        row = next(r for r in rows if r.get('steam_id') == p['steam_id'])
        if row.get('participant_key') != p.get('participant_key') or row.get('controller_kind') != p.get('controller_kind'):
            return 'conflicting_result_identity', None
    final = record.get('finish_roster')
    if final:
        for p in players:
            slots = [s for s in final.get('slots', []) if s.get('memberIdRaw') == p.get('native_member_id')]
            if len(slots) != 1 or slots[0].get('teamRaw') != p['starting_team']:
                return 'changed_or_unresolved_participation', None
    if any(r.get('kind') not in ('player', 'team') for r in result.get('rows', [])):
        return 'unknown_result_rows', None
    if record.get('finish') and record.get('lobby'):
        other = record['lobby']; om = record['lobby_metadata']
        other_winner = automatic_winner(other,om)
        association = lambda ps: sorted((p.get('steam_id') or '', p.get('starting_team') or '', p.get('role') or '') for p in ps)
        if (other_winner not in (None, winner) or result_signature(result) != result_signature(other)
                or association(people) != association(om.get('participants', []))):
            return 'conflicting_captures', None
    historical = HISTORICAL_ROBZ.get(record['id']) == map_id
    profile = m.get('rating_profile')
    if not (adjudicated and attestation.get('pool')==POOL) and not historical and not (isinstance(profile, dict) and profile.get('pool') == POOL and profile.get('source') == 'operator_cli_declaration'):
        return 'robz_not_confirmed', None
    if m.get('start_observation') == 'attached_in_progress' and not historical:
        return 'partial_participation', None
    if m.get('rating_eligible') is False and not (adjudicated and m.get('trigger') == 'returned_to_lobby_without_observed_natural_completion'):
        return 'participation_or_outcome_unresolved', None
    return 'rated', dict(teams=teams, winner=winner,
                         outcome_source='explicit_user_confirmation' if adjudicated else 'native_completion',
                         profile_source='explicit_user_confirmation' if adjudicated and attestation.get('pool')==POOL else 'user_historical_attestation_2026-09-05' if historical else profile['source'],
                         participation_policy='complete_result_roster; continuous participation not measured')


def evaluate(records):
    ratings = {}; matches = {}
    for record in records:
        try:
            reason, match = classify(record)
        except (ValueError, TypeError, KeyError):
            reason, match = 'malformed_capture', None
        audit = dict(status=reason, model=VERSION, pool=POOL, updates={})
        if match:
            probability, changes = update(match['teams'], ratings, match['winner'])
            ratings.update({s: r['after'] for s, r in changes.items()})
            audit.update(match, probability_a=probability, updates=changes,
                         fallback='outcome_only; individual performance model not fitted')
        matches[record['id']] = audit
    return dict(model=VERSION, pool=POOL, parameters=PARAMETERS, matches=matches, players=ratings)


def refresh(database, dry_run=False):
    """Read, replay and publish under one writer lock; retries cannot double-rate."""
    with closing(sqlite3.connect(database, timeout=10)) as db, db:
        db.execute('BEGIN' if dry_run else 'BEGIN IMMEDIATE')
        return refresh_connection(db,dry_run)


def refresh_connection(db, dry_run=False):
    """Publish within the caller's transaction, including manual outcome submissions."""
    if not db.in_transaction:raise RuntimeError('Rating publication requires a transaction')
    records = read_inputs(db)
    digest = hashlib.sha256(encoded([VERSION, PARAMETERS, 'final-vp-required-v1', records]).encode()).hexdigest()
    if not dry_run:
        db.execute('CREATE TABLE IF NOT EXISTS rating_runs (model TEXT, digest TEXT, payload TEXT NOT NULL, PRIMARY KEY(model,digest))')
        db.execute('CREATE TABLE IF NOT EXISTS rating_head (model TEXT PRIMARY KEY, digest TEXT NOT NULL)')
        previous = db.execute('SELECT payload FROM rating_runs WHERE model=? LIMIT 1', (VERSION,)).fetchone()
        if previous and json.loads(previous[0])['parameters'] != PARAMETERS:
            raise ValueError('Published parameters are frozen; use a new model version')
        existing = db.execute('SELECT payload FROM rating_runs WHERE model=? AND digest=?', (VERSION, digest)).fetchone()
    else:
        existing = None
    payload = json.loads(existing[0]) if existing else evaluate(records)
    if not dry_run:
        db.execute('INSERT OR IGNORE INTO rating_runs VALUES (?,?,?)', (VERSION, digest, encoded(payload)))
        db.execute('INSERT INTO rating_head VALUES (?,?) ON CONFLICT(model) DO UPDATE SET digest=excluded.digest', (VERSION, digest))
    return payload


def stored(database):
    path = Path(database).resolve()
    if not path.is_file():
        return {}
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='rating_head'").fetchone():
            return {}
        row = db.execute('SELECT r.payload FROM rating_runs r JOIN rating_head h USING(model,digest) WHERE model=?', (VERSION,)).fetchone()
        return json.loads(row[0]) if row else {}


def capture_profile(controller):
    return dict(pool=POOL, source='operator_cli_declaration') if getattr(controller, 'rating_profile', None) == POOL else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path(__file__).resolve().parent.parent/'data/rankbot.sqlite3')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error('Match database does not exist')
    print(json.dumps(refresh(args.database, args.dry_run), indent=2))


if __name__ == '__main__':
    main()
