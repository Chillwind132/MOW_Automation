"""Diagnostic suspension must not consume game RPC timeouts."""
import _test_paths  # Shared paths for direct runs and test discovery.
import threading
import unittest

from stability_loop import serialized
from stress_supervisor import fatal_allocation,new_fatal_allocation,completed_restart


class DiagnosticCoordinationTests(unittest.TestCase):
    def test_ordinary_log_append_does_not_reclassify_old_crash_as_new(self):
        marker='***************** Exception *****************\n'
        failure=marker+'Failed to allocate memory.\nRequested 524288 bytes. E=12 (Not enough space) (ememory.cpp, 94)'
        baseline='old session\n'+failure
        self.assertFalse(new_fatal_allocation(baseline,baseline))
        self.assertFalse(new_fatal_allocation(baseline+'\nordinary startup message',baseline))
        self.assertFalse(new_fatal_allocation('rewritten header\n'+failure,baseline))
        self.assertTrue(new_fatal_allocation(baseline+'\n'+failure,baseline))
        self.assertTrue(new_fatal_allocation('new session\n'+failure,'startup without exception'))
        self.assertFalse(new_fatal_allocation(baseline+'\n'+marker+'Access violation',baseline))
        changed=failure.replace('524288','16935406')
        self.assertTrue(new_fatal_allocation('new session\n'+changed,baseline))

    def test_completed_restart_honors_stop_and_failures(self):
        valid={'matches_saved':1,'desired':'run'}
        self.assertTrue(completed_restart(True,0,valid))
        self.assertFalse(completed_restart(False,0,valid))
        self.assertFalse(completed_restart(True,1,valid))
        self.assertFalse(completed_restart(True,0,{**valid,'desired':'stop'}))
        self.assertFalse(completed_restart(True,0,{**valid,'matches_saved':0}))
        self.assertFalse(completed_restart(True,0,{**valid,'error':'save failed'}))

    def test_recovery_requires_latest_exception_to_be_allocator_failure(self):
        marker='***************** Exception *****************\n'
        failure=marker+'Failed to allocate memory.\nRequested 524288 bytes. E=12 (Not enough space) (ememory.cpp, 94)'
        self.assertTrue(fatal_allocation(failure))
        self.assertFalse(fatal_allocation('Unknown props in entity'))
        self.assertFalse(fatal_allocation(failure+marker+'Access violation'))
        self.assertFalse(fatal_allocation('Failed to allocate memory.'))

    def test_rpc_waits_for_dump_and_nested_calls_are_reentrant(self):
        lock = threading.RLock()
        started, entered, finished = (threading.Event() for _ in range(3))
        inner = serialized(lock, entered.set)
        def rpc():
            inner()
            finished.set()
        operation = serialized(lock, rpc)
        def worker():
            started.set()
            operation()
        with lock:  # Simulated MiniDumpWriteDump suspension.
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            self.assertTrue(started.wait(2))
            self.assertFalse(entered.wait(.05))
        self.assertTrue(finished.wait(2))
        thread.join(2)
        self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()
