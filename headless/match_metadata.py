"""Compatibility exports for shared player identity validation."""
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parents[1]))
from modules.live_game_data.identity import *
