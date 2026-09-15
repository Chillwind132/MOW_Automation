"""Normalize passive counters against a durable roster; never infer a winner.

Example with match metadata and the raw live probe (no database writes):
    from modules.live_game_data import normalize_live_statistics
    statistics = normalize_live_statistics(match, live_probe)
    players = statistics["players"]

Check statistics["status"]: observed, partial or unavailable. Missing counters
remain None/unavailable; infantry and vehicle pairs are enemy kills / losses.
"""
import math


def normalize_live_statistics(match, live):
    raw = (live or {}).get('playerStatistics') or {}
    unavailable = dict(status='unavailable', source='native_battle_counters', players=[], teams=[])
    if raw.get('status') != 'observed':
        return dict(unavailable, reason=raw.get('error', 'No native player counters captured'))
    if raw.get('nativeGameStartTime') != match.get('native_game_start_time'):
        return dict(unavailable, reason='Native match generation mismatch')
    expected = {p['native_member_id']: p for p in match.get('participants', [])
                if p.get('role') == 'participant'}
    rows = raw.get('players', [])
    if (not expected or len(rows) != len(expected)
            or {p.get('nativeMemberId') for p in rows} != set(expected)
            or len({p.get('gamePlayerSlot') for p in rows}) != len(rows)):
        return dict(unavailable, reason='Incomplete or duplicate native player identities')
    players = []
    for row in rows:
        participant = expected[row['nativeMemberId']]
        words = row.get('steamWords', [])
        if len(words) != 2 or any(type(w) is not int or not 0 <= w <= 0xffffffff for w in words):
            return dict(unavailable, reason='Invalid native Steam identity')
        steam = str((words[1] << 32) | words[0]) if any(words) else None
        if (steam != participant.get('steam_id') or row.get('team') != participant.get('starting_team')
                or row.get('ai') != (participant.get('controller_kind') == 'ai')):
            return dict(unavailable, reason='Native player Steam/team/controller mismatch')
        values = {}
        for key, count in [('infantry', 2), ('vehicles', 2), ('resources', 2), ('score', 1)]:
            value = row.get(key)
            sequence = [value] if key == 'score' and value is not None else value
            if sequence is not None and (not isinstance(sequence, list) or len(sequence) != count
                    or any(type(v) is not int or abs(v) > 0x7fffffff for v in sequence)):
                return dict(unavailable, reason='Invalid native numeric counters')
            values[key] = value
        players.append(dict(participant_key=participant['participant_key'], steam_id=steam,
            display_name=participant['display_name'], team=row['team'], **values))
    teams = []
    for team in ('a', 'b'):
        scores = [s.get('values', []) for s in raw.get('scores', []) if s.get('key') == team]
        vp = score = None
        if len(scores) == 1 and len(scores[0]) == 6:
            value = scores[0][1]
            if type(value) in (float, int) and math.isfinite(value) and abs(value) <= 0x7fffffff:
                vp = math.trunc(value)
            value = scores[0][2]
            if type(value) in (float, int) and math.isfinite(value) and abs(value) <= 0x7fffffff:
                score = math.trunc(value)
        members = [p for p in players if p['team'] == team]
        totals = {key: ([sum(p[key][i] for p in members) for i in range(2)]
                       if members and all(p[key] is not None for p in members) else None)
                  for key in ('infantry', 'vehicles')}
        teams.append(dict(team=team, victory_points=vp, score=score, **totals))
    partial = any(p[k] is None for p in players for k in ('infantry', 'vehicles', 'score', 'resources'))
    return dict(status='partial' if partial else 'observed', source='native_battle_counters',
        players=players, teams=teams, paired_counter_meanings=['enemy_kills', 'losses'],
        resource_pair_meanings=['non_special', 'special'])


def compare_final_statistics(result, native):
    """Keep both observations intact and disclose disagreements, including zeros."""
    if native.get('status') not in ('observed', 'partial'):
        return dict(status='unavailable', reason=native.get('reason'))
    differences = []
    compared = 0
    for player in native['players']:
        rows = [r for r in result['rows'] if r.get('participant_key') == player['participant_key']]
        if len(rows) != 1:
            return dict(status='unavailable', reason='Final participant identity mismatch')
        for key in ('infantry', 'vehicles', 'score', 'resources'):
            observed = player[key]
            cell = rows[0]['fields'].get(key)
            if observed is None or not cell or cell.get('values_in_display_order') is None:
                continue
            expected = [observed] if key == 'score' else observed
            compared += 1
            if cell['values_in_display_order'] != expected:
                differences.append(dict(participant_key=player['participant_key'], field=key,
                    scoreboard=cell['values_in_display_order'], native=expected))
    return dict(status='disagrees' if differences else 'matched' if compared else 'unavailable',
                compared_fields=compared, differences=differences)
