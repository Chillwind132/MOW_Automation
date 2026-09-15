"""Exercise Windows exit evidence on disposable Python processes, not the game."""
import _test_paths  # Shared paths for direct runs and test discovery.
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from host_diagnostics import ProcessDiagnostics
from headless_host import HostController


class DiagnosticsTests(unittest.TestCase):
    def test_live_and_exited_process_keep_exact_exit_code(self):
        for code in (37, 259):
            with self.subTest(code=code):
                child = subprocess.Popen([sys.executable, '-c',
                    f'import sys; sys.stdin.readline(); sys.exit({code})'], stdin=subprocess.PIPE)
                diagnostic = None
                try:
                    diagnostic = ProcessDiagnostics(child.pid)
                    self.assertEqual(diagnostic.snapshot(), {'alive': True})
                    child.communicate(b'quit\n', timeout=10)
                    evidence = diagnostic.snapshot()
                    self.assertFalse(evidence['alive'])
                    self.assertEqual(evidence['exit_code'], code)
                    self.assertEqual(evidence['exit_code_hex'], f'0x{code:08X}')
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.communicate(timeout=10)
                    if diagnostic:
                        diagnostic.close()
                        diagnostic.close()

    def test_failure_evidence_keeps_target_and_probe_step(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = HostController(123, Path(directory))
            try:
                controller.last_command = {'action': 'probe', 'target': 'social'}
                controller.instrumentation_message({'type': 'send', 'payload': {
                    'event': 'social_probe_step', 'step': 'messages'}}, None)
                controller.on_detached('process-terminated', None)
                result = controller.failure_diagnostics()
                self.assertEqual(result['last_probe_step']['step'], 'messages')
                self.assertEqual(result['last_command']['target'], 'social')
                self.assertEqual(result['detachment']['reason'], 'process-terminated')
                events = [json.loads(line) for line in (Path(directory)/'events.jsonl').read_text().splitlines()]
                self.assertEqual(events[-1]['event'], 'failure_diagnostics')
            finally:
                controller.close()


if __name__ == '__main__':
    unittest.main()
