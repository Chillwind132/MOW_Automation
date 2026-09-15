"""Low-cost external lifetime counters across process restarts; no injected code."""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
import json
from pathlib import Path
import time
import pymem
from friends_host import Control
from headless_host import ROOT,find_process,process_identity,SUPPORTED_SHA256
from heap_ownership import engine_owners,heap_accounting

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path);p.add_argument('--hours',type=float,default=9)
    a=p.parse_args();a.directory.mkdir(parents=True,exist_ok=True)
    control=Control(ROOT/'data/friends_control.sqlite3')
    deadline=time.monotonic()+a.hours*3600
    identity=None;pm=None;accounting=None;last_accounting=0
    try:
        with (a.directory/'engine_owners.jsonl').open('a') as output:
            while time.monotonic()<deadline and not (a.directory/'STOP').exists():
                try:
                    pid=find_process()
                    if pid is None:
                        if pm:pm.close_process();pm=None
                        identity=None
                    else:
                        if pm is None or identity['pid']!=pid:
                            if pm:pm.close_process()
                            identity=process_identity(pid)
                            if identity['sha256']!=SUPPORTED_SHA256:raise RuntimeError('Unsupported game')
                            pm=pymem.Pymem(pid)
                            accounting=None;last_accounting=0
                        context=control.status()
                        if time.monotonic()-last_accounting>=30:
                            accounting=heap_accounting(pm);last_accounting=time.monotonic()
                        row={'time':time.time(),'identity':identity,
                            'phase':context.get('phase'),'match_id':context.get('match_id'),
                            'owners':engine_owners(pm),'heap_accounting':accounting}
                        output.write(json.dumps(row)+'\n');output.flush()
                except Exception as error:
                    output.write(json.dumps({'time':time.time(),'error':str(error)})+'\n');output.flush()
                    if pm:pm.close_process();pm=None
                time.sleep(5)
    finally:
        if pm:pm.close_process()

if __name__=='__main__':main()
