import _test_paths  # Shared paths for direct runs and test discovery.
import unittest
from overnight_investigation import safe_handoff

class HandoffTests(unittest.TestCase):
    def test_success_requires_completed_matches_and_honors_stop(self):
        self.assertTrue(safe_handoff({}, {'matches_saved':2,'desired':'run'}, ''))
        self.assertFalse(safe_handoff({}, {'matches_saved':1,'desired':'run'}, ''))
        self.assertFalse(safe_handoff({}, {'matches_saved':2,'desired':'stop'}, ''))

    def test_only_confirmed_allocator_failure_can_recover_failed_run(self):
        log='***************** Exception *****************\nFailed to allocate memory.\nememory.cpp, 94'
        self.assertTrue(safe_handoff({'error':'timeout'}, {'desired':'run'},log))
        self.assertFalse(safe_handoff({'error':'timeout'}, {'desired':'stop'},log))
        self.assertFalse(safe_handoff({'error':'timeout'}, {'desired':'run'},'access violation'))

if __name__=='__main__':unittest.main()
