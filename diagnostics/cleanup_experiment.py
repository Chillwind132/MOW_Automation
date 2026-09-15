"""Measure allocator-owned cache cleanup after preserving completed results."""
import _bootstrap  # Set up imports for direct CLI execution.
import ctypes
import argparse
from ctypes import wintypes
from datetime import datetime
import json
import time

from headless_host import ROOT,HostController,find_process
from stability_loop import MemoryCounters
from memory_diagnostics import Diagnostics


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources',action='store_true')
    args=parser.parse_args()
    pid=find_process()
    if pid is None: raise RuntimeError('Existing game required')
    directory=ROOT/'validation'/datetime.now().strftime('heap_cleanup_%Y%m%d_%H%M%S')
    directory.mkdir()
    print(directory,flush=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    get_memory=ctypes.WinDLL('psapi',use_last_error=True).GetProcessMemoryInfo
    get_memory.argtypes=[wintypes.HANDLE,ctypes.POINTER(MemoryCounters),wintypes.DWORD]
    handle=kernel.OpenProcess(0x410,False,pid)
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    diagnostics=Diagnostics(handle,pid,directory)
    diagnostics.dump_attempted=True
    report={'pid':pid,'samples':[]}
    controller=HostController(pid,directory)
    def snapshot(phase):
        counters=MemoryCounters();counters.cb=ctypes.sizeof(counters)
        if not get_memory(handle,ctypes.byref(counters),counters.cb): raise ctypes.WinError(ctypes.get_last_error())
        sample={'time':time.time(),**{name:getattr(counters,name) for name,_ in counters._fields_}}
        diagnostics.observe(sample,{'match_id':controller.match_id,'phase':phase})
        report['samples'].append(sample)
        print(phase,'private MiB',round(sample['PrivateUsage']/2**20),
              'free MiB',round(sample['address_space']['free_bytes']/2**20),
              'largest MiB',round(sample['address_space']['largest_free_region']/2**20),flush=True)
    try:
        controller.attach()
        report['identity']=controller.identity
        snapshot('before_completed_exit')
        if controller.active_match:
            if controller.recovery['status'] not in ('playing','completion_observed'):
                raise RuntimeError('Completed match requires reconciliation before cleanup')
            controller.finish_ai(120)
            controller.bind_session()
            controller.save_ai_results(120)
            controller.bind_session()
        snapshot('lobby_before_heap_optimization')
        if args.resources:
            report['resource_operation']=controller.command('cleanup-resources')['resourceCleanup']
            snapshot('lobby_after_resource_cleanup')
        report['operation']=controller.command('optimize-heap')['heapOptimization']
        snapshot('lobby_after_heap_optimization')
        time.sleep(5)
        snapshot('lobby_five_seconds_after')
    except BaseException as error:
        report['error']=str(error)
        raise
    finally:
        (directory/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        controller.close()
        kernel.CloseHandle(handle)


if __name__=='__main__': main()
