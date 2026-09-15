"""The lobby chat locator must not descend into unrelated growing UI panels."""
import _test_paths
import subprocess
import unittest


class LobbyChatContextTests(unittest.TestCase):
    def test_locator_is_scoped_and_keeps_identity_guards(self):
        result = subprocess.run(
            ['node', 'tests/lobby_chat_context_harness.js'],
            cwd=_test_paths.ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
