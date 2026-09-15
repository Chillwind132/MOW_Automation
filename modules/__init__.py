"""Shared match-data APIs for host, observer and bot integrations.

Example (import from the public packages):
    from modules.live_game_data import normalize_live_statistics
    from modules.end_game_results import load_result
    live_rows = normalize_live_statistics(match, live_probe)
    final_rows = load_result(database, match["match_id"])  # None until replay saved.
"""
