"""CLI entry point for the same replay API used by every controller mode.

Examples, run from the project root (no game attachment):
    py -m modules.end_game_results --help
    py -m modules.end_game_results --database data/rankbot.sqlite3
    py -m modules.end_game_results --watch
    py -m modules.end_game_results --stop

Without --watch, performs one import pass after checking file stability.
"""
from .replays import main

if __name__ == "__main__":
    main()
