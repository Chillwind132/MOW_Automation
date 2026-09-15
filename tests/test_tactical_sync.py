import _test_paths
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tactical_sync import SyncLogMonitor


class SyncMonitorTests(unittest.TestCase):
    def test_only_new_current_match_errors_are_reported_with_exact_offset(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'game.log'
            old = b'Out Of Sync at quant 100\n'
            path.write_bytes(old)
            monitor = SyncLogMonitor(path, 130)
            self.assertIsNone(monitor.poll(205))
            with path.open('ab') as out:
                out.write(b'Out Of Sync at quant 120\nDesync detected on quant 205\n')
            result = monitor.poll(205)
            self.assertEqual(result['nativeQuant'], 205)
            self.assertEqual(result['logOffset'], len(old)+len(b'Out Of Sync at quant 120\n'))
            self.assertEqual(monitor.status, 'native_desync_observed')

    def test_split_error_is_completed_without_reprocessing_old_lines(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'game.log'
            path.touch()
            monitor = SyncLogMonitor(path, 100)
            with path.open('ab') as out:
                out.write(b'Desync detected on qu')
            self.assertIsNone(monitor.poll(110))
            with path.open('ab') as out:
                out.write(b'ant 110\n')
            self.assertEqual(monitor.poll(110)['nativeQuant'], 110)
            self.assertIsNone(monitor.poll(110))

    def test_missing_and_truncated_logs_do_not_claim_desync(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'game.log'
            missing = SyncLogMonitor(path, 1)
            self.assertIsNone(missing.poll(100))
            path.write_bytes(b'x'*200)
            monitor = SyncLogMonitor(path, 1)
            path.write_bytes(b'Out Of Sync at quant 100\n')
            self.assertIsNone(monitor.poll(100))
            self.assertIn('association_unproven', monitor.status)

    def test_read_and_pending_buffers_are_bounded(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'game.log'
            path.touch()
            monitor = SyncLogMonitor(path, 0)
            path.write_bytes(b'x'*(monitor.MAX_READ*2)+b'\nOut Of Sync at quant 205\n')
            self.assertIsNone(monitor.poll(205))
            self.assertEqual(monitor.offset, monitor.MAX_READ)
            self.assertLessEqual(len(monitor.pending), 4096)
            self.assertIsNone(monitor.poll(205))
            self.assertEqual(monitor.poll(205)['nativeQuant'], 205)


if __name__ == '__main__':
    unittest.main()
