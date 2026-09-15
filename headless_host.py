"""Stable entry point for the host; implementation lives in headless/."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'headless'))
from headless_host import main

if __name__ == '__main__':
    raise SystemExit(main())
