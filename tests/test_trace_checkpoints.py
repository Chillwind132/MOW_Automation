"""Deferred allocation snapshots must preserve generations without false empty censuses."""
import _test_paths  # Shared paths for direct runs and test discovery.
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from allocation_trace import AllocationTrace

class CheckpointTests(unittest.TestCase):
    def test_generation_boundaries_and_separate_evidence(self):
        with TemporaryDirectory() as temporary:
            trace=AllocationTrace.__new__(AllocationTrace)
            trace.directory=Path(temporary);trace.epoch=0;trace.last_context=None;trace.errors=[]
            calls=[]
            def full(epoch):
                calls.append(('full',epoch));return {'epoch':epoch,'groups':[{'bytes':1024}],'sampled_live_bytes':1024}
            def light(epoch):
                calls.append(('light',epoch));return {'epoch':epoch,'counters':[epoch,1,0,1,0,0]}
            trace.script=SimpleNamespace(exports_sync=SimpleNamespace(snapshot=full,checkpoint=light))
            trace.snapshot({'match_id':'one','phase':'playing'})
            trace.snapshot({'match_id':'two','phase':'loading'},light=True)
            trace.snapshot({'match_id':'two','phase':'loading'},light=True)
            trace.snapshot({'match_id':'two','phase':'playing'})
            self.assertEqual(calls,[('full',1),('light',2),('light',2),('full',3)])
            records=[json.loads(x) for x in (trace.directory/'allocations.jsonl').read_text().splitlines()]
            self.assertEqual([r['epoch'] for r in records],[1,3])
            self.assertTrue(all(r['sampled_live_bytes']==1024 for r in records))
            checkpoints=[json.loads(x) for x in (trace.directory/'allocation_checkpoints.jsonl').read_text().splitlines()]
            self.assertEqual(len(checkpoints),2)
            self.assertTrue(all('groups' not in r for r in checkpoints))

if __name__=='__main__':unittest.main()
