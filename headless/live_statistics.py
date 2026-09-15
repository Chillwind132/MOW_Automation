"""Compatibility entry point; implementation is in modules/live_game_data/statistics.py."""
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parents[1]))
from modules.live_game_data.statistics import *
