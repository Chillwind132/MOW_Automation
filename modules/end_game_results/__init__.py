"""Public final-results API: completed, identity-checked persisted replays only.

Example with a database path and a recorded match ID:
    from modules.end_game_results import ensure_watcher, load_result
    ensure_watcher(database)  # Starts an independent singleton importer.
    result = load_result(database, match_id)

result is None until a replay final is saved. Use wait_for_match(database,
match, timeout=30) to wait; TimeoutError means the final remains pending.
"""
from .replays import SOURCE, ReplayImporter, read_replay, normalize, publish, wait_for_match, ensure_watcher, load_result
