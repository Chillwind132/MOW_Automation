"""Shared import setup for unittest discovery and direct test execution."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
for folder in ('headless', 'diagnostics', 'tests'):
    path = str(ROOT / folder)
    if path not in sys.path:
        sys.path.insert(0, path)

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.append(str(Path(__file__).resolve().parents[1]))
