"""Compatibility entry point; implementation is in modules/end_game_results/replays.py."""
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parents[1]))
from modules.end_game_results.replays import *

if __name__=='__main__':main()
