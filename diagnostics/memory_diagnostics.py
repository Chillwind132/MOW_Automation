"""External address-space snapshots and one high-memory game dump."""
import _bootstrap  # Set up imports for direct CLI execution.
import ctypes
from ctypes import wintypes
import json
import msvcrt
import time


class Region(ctypes.Structure):
    _fields_ = [('base',ctypes.c_void_p),('allocation',ctypes.c_void_p),
        ('allocation_protect',wintypes.DWORD),('partition',wintypes.WORD),
        ('size',ctypes.c_size_t),('state',wintypes.DWORD),
        ('protect',wintypes.DWORD),('type',wintypes.DWORD)]


class Diagnostics:
    def __init__(self, handle, pid, directory):
        self.handle,self.pid,self.directory=handle,pid,directory
        self.last=0
        self.phase=None
        self.dump_attempted=False
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.query=kernel.VirtualQueryEx
        self.query.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.POINTER(Region),ctypes.c_size_t]
        self.query.restype=ctypes.c_size_t

    def observe(self, sample, context):
        phase=(context.get('match_id'),context.get('phase'))
        if time.monotonic()-self.last>=30 or phase!=self.phase:
            self.last=time.monotonic()
            self.phase=phase
            regions=[]
            address=0
            # This diagnostic is deliberately restricted to the x86 game space.
            while address<0x100000000:
                region=Region()
                if not self.query(self.handle,address,ctypes.byref(region),ctypes.sizeof(region)):
                    break
                size=min(region.size,0x100000000-address)
                if not size:break
                regions.append({'base':address,'allocation':region.allocation,
                    'size':size,'state':region.state,'type':region.type,'protect':region.protect})
                address+=size
            free=[r['size'] for r in regions if r['state']==0x10000]
            report={'time':time.time(),'pid':self.pid,'match_id':phase[0],'phase':phase[1],
                'scanned_bytes':address,'free_bytes':sum(free),
                'largest_free_region':max(free,default=0),
                'reserved_bytes':sum(r['size'] for r in regions if r['state']==0x2000),
                'committed_bytes':sum(r['size'] for r in regions if r['state']==0x1000),
                'regions':regions}
            with (self.directory/'address_space.jsonl').open('a') as output:
                output.write(json.dumps(report)+'\n')
            sample['address_space']={k:v for k,v in report.items() if k!='regions'}
            self.latest_report=report
        if not self.dump_attempted and sample.get('PrivateUsage',0)>=3.1*1024**3:
            self.dump_attempted=True
            path=self.directory/'high_memory.dmp'
            result={'time':time.time(),'pid':self.pid,'phase':phase,'path':str(path)}
            dump=ctypes.WinDLL('dbghelp',use_last_error=True).MiniDumpWriteDump
            dump.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.HANDLE,wintypes.DWORD,
                           ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p]
            dump.restype=wintypes.BOOL
            print('Capturing one high-memory dump for diagnosis...',flush=True)
            with path.open('wb') as output:
                result['success']=bool(dump(self.handle,self.pid,msvcrt.get_osfhandle(output.fileno()),
                                           0x1802,None,None,None))
                result['error']=0 if result['success'] else ctypes.get_last_error()
            result['finished']=time.time()
            (self.directory/'dump_status.json').write_text(json.dumps(result,indent=2))
            print('Memory dump saved' if result['success'] else f"Memory dump failed: {result['error']}",flush=True)
