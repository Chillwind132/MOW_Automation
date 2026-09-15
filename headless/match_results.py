"""Compatibility entry point; implementation is in modules/end_game_results/legacy.py."""
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parents[1]))
from modules.end_game_results.legacy import *
