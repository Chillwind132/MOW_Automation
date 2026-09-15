import _test_paths  # Shared paths for direct runs and test discovery.
import unittest
from unittest.mock import patch
from pymem.exception import WinAPIError
from headless_host import scan_with_partial_copy_retry


class PartialCopyTests(unittest.TestCase):
    def test_transient_scan_retries_without_treating_failure_as_empty(self):
        with patch('headless_host.pymem.pattern.pattern_scan_all',side_effect=[WinAPIError(299),[123]]) as scan, patch('headless_host.time.sleep'):
            self.assertEqual(scan_with_partial_copy_retry(1,b'test'),[123])
            self.assertEqual(scan.call_count,2)

    def test_persistent_or_unrelated_errors_still_surface(self):
        for code,expected_calls in ((299,3),(5,1)):
            with self.subTest(code=code), patch('headless_host.pymem.pattern.pattern_scan_all',side_effect=WinAPIError(code)) as scan, patch('headless_host.time.sleep'):
                with self.assertRaises(WinAPIError):scan_with_partial_copy_retry(1,b'test')
                self.assertEqual(scan.call_count,expected_calls)


if __name__=='__main__':unittest.main()
