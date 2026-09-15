"""Run the active regression suite, or selected modules, from any directory."""
import os
import sys
import unittest
import _test_paths

if __name__ == '__main__':
    os.chdir(_test_paths.ROOT)
    loader = unittest.defaultTestLoader
    suite = (loader.loadTestsFromNames(sys.argv[1:]) if len(sys.argv) > 1
             else loader.discover(str(_test_paths.ROOT / 'tests'), pattern='test_*.py'))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    raise SystemExit(not result.wasSuccessful())
