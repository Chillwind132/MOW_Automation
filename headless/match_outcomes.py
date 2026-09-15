"""Review/rating outcome policy; raw engine evidence is never rewritten."""
from functools import lru_cache
from pathlib import Path


def positive_number(value):
    try:
        number = float(value)
        return number if 0 < number < float('inf') else None
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=256)
def archived_target(path, modified):
    from modules.end_game_results.replays import tree, section, value
    return positive_number(value(section(tree(Path(path).read_text(encoding='utf-8-sig')), 'settings'), 'scoreFinal'))


def final_vp(result, metadata, database=None):
    digest = (result.get('replay') or {}).get('ss_sha256')
    if database and isinstance(digest, str) and len(digest) == 64 and all(c in '0123456789abcdef' for c in digest):
        path = Path(database).resolve().parent / 'replays' / digest / 'replay.ss'
        try:
            return archived_target(str(path), path.stat().st_mtime_ns)
        except (OSError, ValueError, KeyError):
            pass
    if '_final_vp' in metadata:
        return metadata['_final_vp']
    roster = metadata.get('loaded_roster') or metadata.get('starting_roster') or metadata.get('pre_quit_roster') or {}
    settings = metadata.get('effective_settings') or roster.get('settings') or {}
    return positive_number(settings.get('victoryPoints', settings.get('scoreFinal')))


def automatic_winner(result, metadata, database=None):
    outcome = result.get('engine_outcome') or metadata.get('engine_outcome') or {}
    winner = outcome.get('winning_team')
    if winner not in ('a', 'b'):
        return None
    roster = metadata.get('loaded_roster') or metadata.get('starting_roster') or {}
    if not (metadata.get('map') or roster.get('map') or '').endswith(':battle_zones'):
        return winner
    target = final_vp(result, metadata, database)
    if target is None:
        return None
    teams = {}
    for row in result.get('rows', []):
        if row.get('kind') != 'team' or row.get('row_id') not in ('ta', 'tb'):
            continue
        field = (row.get('fields') or {}).get('victory_points') or {}
        values = field.get('values_in_display_order') or [field.get('text')]
        try:
            points = float(values[0])
        except (TypeError, ValueError, IndexError):
            return None
        team = row['row_id'][1:]
        if team in teams or not 0 <= points < float('inf'):
            return None
        teams[team] = points
    return winner if set(teams) == {'a', 'b'} and teams[winner] >= target and teams['b' if winner == 'a' else 'a'] < target else None
