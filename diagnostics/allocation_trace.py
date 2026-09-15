"""Bounded, observation-only allocation and same-map cleanup tracing."""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
from datetime import datetime
import hashlib
import json
import time
import frida
from headless_host import ROOT,find_process,process_identity,SUPPORTED_SHA256,bounded
from friends_host import Control

ADDRESSES=(0x512740,0x512780,0x5127f0,0x50e6a0,0x9e3c60,0x9ba180,0x73c8d0,0x719630,0x714260)

class AllocationTrace:
    def __init__(self,pid,directory):
        self.identity=process_identity(pid)
        if self.identity['sha256']!=SUPPORTED_SHA256:raise RuntimeError('Unsupported executable')
        dump=(ROOT/'diagnostics/reference/mowas_2_dumped.exe').read_bytes()
        signatures=[(a,dump[a-0x400000:a-0x400000+8].hex()) for a in ADDRESSES]
        source='const SIGNATURES='+json.dumps(signatures)+';\nconst NATIVE_SOURCE='+json.dumps((ROOT/'diagnostics/allocation_trace.c').read_text())+';\n'+(ROOT/'diagnostics/allocation_trace.js').read_text()
        self.directory=directory
        self.session=frida.attach(pid)
        self.script=self.session.create_script(source)
        self.errors=[]
        def message(m,data):
            with (directory/'trace_events.jsonl').open('a',encoding='utf-8') as out:
                out.write(json.dumps({'received':time.time(),'message':m})+'\n')
            if m['type']=='error':self.errors.append(m)
        self.script.on('message',message)
        try:
            with bounded(15):self.script.load()
        except BaseException:
            with bounded(5):self.session.detach()
            raise
        self.epoch=0
        self.last_context=None
        (directory/'trace_source.js').write_text(source,encoding='utf-8')
        (directory/'trace_identity.json').write_text(json.dumps({'identity':self.identity,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'modules':self.script.exports_sync.modules(),
            'coverage':'active game aligned allocator malloc/realloc/free; every >=64KiB request and 1/1024 smaller requests; best-effort frame-pointer stacks; no extrapolation'},indent=2))
    def snapshot(self,context,light=False):
        key=(context.get('match_id'),context.get('phase'))
        if key!=self.last_context:self.epoch+=1;self.last_context=key
        with bounded(10):
            result=(self.script.exports_sync.checkpoint(self.epoch) if light else
                    self.script.exports_sync.snapshot(self.epoch))
        result.update(time=time.time(),context=context,errors=self.errors)
        filename='allocation_checkpoints.jsonl' if light else 'allocations.jsonl'
        with (self.directory/filename).open('a',encoding='utf-8') as out:out.write(json.dumps(result)+'\n')
        return result
    def close(self):
        with bounded(5):self.session.detach()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--seconds',type=int,default=120);a=p.parse_args()
    directory=ROOT/'validation'/datetime.now().strftime('allocation_trace_%Y%m%d_%H%M%S');directory.mkdir()
    print(directory,flush=True)
    trace=AllocationTrace(find_process(),directory)
    try:
        deadline=time.monotonic()+a.seconds
        while time.monotonic()<deadline:
            status=Control(ROOT/'data/friends_control.sqlite3').status()
            result=trace.snapshot({k:status.get(k) for k in ('match_id','phase','matches_saved','roster')})
            print(result['context']['phase'],result['sampled_live_bytes']//2**20,'MiB tracked',result['counters'],'errors',result['errors'],flush=True)
            time.sleep(10)
    finally:trace.close()

if __name__=='__main__':main()
