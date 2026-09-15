import _test_paths
import json
from pathlib import Path
import subprocess
import unittest
import tempfile


class BridgeTests(unittest.TestCase):
    def test_explicit_human_opponents_preserve_ownership_and_roster_guards(self):
        from tactical_scenarios import BOT_TRIAL_JS
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary)/'bridge.js'
            script.write_text('const humanOpponentTrial = true;\n' +
                              (root/'headless/tactical_bridge.js').read_text() + BOT_TRIAL_JS)
            result = subprocess.run(['node', str(root/'tests/tactical_bridge_harness.js'), str(script)],
                                    capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['passed'], 9)

    def test_native_path_trace_is_owned_bounded_and_observational(self):
        from tactical_scenarios import PATH_WATCH_JS
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / 'bridge.js'
            script.write_text((root / 'headless/tactical_bridge.js').read_text() + PATH_WATCH_JS)
            result = subprocess.run(['node', str(root / 'tests/tactical_bridge_harness.js'), str(script)],
                                    capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['passed'], 4)

    def test_bot_trial_rechecks_native_roster_before_commands(self):
        from tactical_scenarios import BOT_TRIAL_JS
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / 'bridge.js'
            script.write_text((root / 'headless/tactical_bridge.js').read_text() + BOT_TRIAL_JS)
            result = subprocess.run(['node', str(root / 'tests/tactical_bridge_harness.js'), str(script)],
                                    capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['passed'], 13)

    def test_native_admission_and_serialization_fixture(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', str(root / 'tests/tactical_bridge_harness.js'),
                                 str(root / 'headless/tactical_bridge.js')],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['passed'], 190)

    def test_friendly_weapon_diagnostic_identity_and_no_orders(self):
        from tactical_scenarios import FRIENDLY_RELOAD_JS, FRIENDLY_AIM_JS, FRIENDLY_COVER_JS
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / 'bridge.js'
            script.write_text((root / 'headless/tactical_bridge.js').read_text() + FRIENDLY_RELOAD_JS + FRIENDLY_AIM_JS + FRIENDLY_COVER_JS)
            result = subprocess.run(['node', str(root / 'tests/tactical_bridge_harness.js'), str(script)],
                                    capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['passed'], 210)
