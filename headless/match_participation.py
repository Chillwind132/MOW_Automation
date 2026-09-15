"""Compatibility entry point; implementation is in modules/live_game_data/participation.py."""
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parents[1]))
from modules.live_game_data.participation import *

if __name__ == "__main__":
    main()
