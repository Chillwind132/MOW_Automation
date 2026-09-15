"""Read-only x86 NT-heap/address-space ownership snapshots on build 26200.

Offsets are verified against this machine's ntdll symbols in
analysis/heap_layout.txt and analysis/heap_virtual_layout.txt. Traversals are
not atomic; changed/unreadable lists are reported, never treated as corruption.
No remote calls, heap walks through busy entries, or heap mutations.
"""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime
import json
import struct
import sys
import time
from pathlib import Path
import pymem
from headless_host import ROOT,find_process,process_identity,SUPPORTED_SHA256
from friends_host import Control
from memory_diagnostics import Diagnostics

def heap_accounting(pm):
    """Header accounting; free LFH slots may remain charged to backend busy blocks."""
    if sys.getwindowsversion().build!=26200:raise RuntimeError('Unverified heap header layout')
    nt=ctypes.WinDLL('ntdll').NtQueryInformationProcess
    nt.argtypes=[wintypes.HANDLE,wintypes.ULONG,ctypes.c_void_p,wintypes.ULONG,ctypes.c_void_p]
    nt.restype=wintypes.LONG
    peb=ctypes.c_size_t()
    if nt(pm.process_handle,26,ctypes.byref(peb),ctypes.sizeof(peb),None)!=0 or not peb.value:
        raise RuntimeError('WOW64 PEB unavailable')
    count=pm.read_uint(peb.value+0x88);array=pm.read_uint(peb.value+0x90)
    if not 0<count<=512:raise RuntimeError('Invalid heap count')
    heaps=struct.unpack('<'+'I'*count,pm.read_bytes(array,count*4))
    result={'time':time.time(),'heaps':[],'errors':[],
        'limitation':'Non-atomic header counters; backend free excludes free slots inside LFH busy subsegments.'}
    for heap in heaps:
        try:
            reserved,committed,large_ucr,virtual_reserved,virtual_committed=struct.unpack('<5I',pm.read_bytes(heap+0x1f4,20))
            # TotalFreeSize units verified against !heap -s in the saved full dump.
            free=pm.read_uint(heap+0x74)*8
            result['heaps'].append({'heap':hex(heap),'backend_free_mib':round(free/2**20,3),
                'reserved_mib':round(reserved/2**20,3),'committed_mib':round(committed/2**20,3),
                'virtual_reserved_mib':round(virtual_reserved/2**20,3),
                'virtual_committed_mib':round(virtual_committed/2**20,3),
                'frontend_type':pm.read_uchar(heap+0xea)})
        except Exception as error:result['errors'].append({'heap':hex(heap),'error':str(error)})
    result['backend_free_mib']=round(sum(h['backend_free_mib'] for h in result['heaps']),3)
    return result

def engine_owners(pm):
    """Known retail globals; external observations, never pointer mutations."""
    result={}
    try:
        allocations,reallocations,frees=struct.unpack('<3I',pm.read_bytes(0xfac4f8,12))
        result['allocator_calls']={'allocations_u32':allocations,'reallocations_u32':reallocations,
            'frees_u32':frees,
            'scope':'Engine wrapper call counters, not live-block counts; non-atomic sample, unsigned wrap possible.'}
    except Exception as error:result['allocator_calls_error']=str(error)
    def vector(address,stride,limit):
        start,end,capacity=struct.unpack('<3I',pm.read_bytes(address,12))
        if not start<=end<=capacity or (end-start)%stride or (capacity-start)//stride>limit:
            raise RuntimeError('Unstable or invalid owner vector')
        return start,end,(end-start)//stride
    try:
        start,end,count=vector(0xfb5b6c,4,4096)
        chunks=struct.unpack('<'+'I'*count,pm.read_bytes(start,end-start)) if count else ()
        issued=[pm.read_uint(chunk+0x160000) for chunk in chunks]
        if any(x>0x4000 for x in issued):raise RuntimeError('Invalid pool chunk counter')
        _,_,recycled=vector(0xfb5b6c+12,8,4096*0x4000)
        result['serialization']={'chunks':count,'capacity_bytes':count*0x160004,
            'issued_slots':sum(issued),'recycled_slots':recycled,
            'in_use_estimate':sum(issued)-recycled,
            'vector_stable':(start,end)==struct.unpack('<2I',pm.read_bytes(0xfb5b6c,8))}
        _,_,count=vector(0xfb1408+0x24,8,1000000)
        result['audio_cache']={'sample_entries':count,'key_entries':pm.read_uint(0xfb1408+0x20)}
        _,_,count=vector(0xf31e9c+8,0x4c,100000)
        result['audio_streams']={'entries':count}
        profile=pm.read_uint(0xfbaa50+0x6c)
        result['texture_profile']=None
        if profile:
            length,capacity=struct.unpack('<2I',pm.read_bytes(profile+16,8))
            if not 0<length<=80 or capacity<length:raise RuntimeError('Invalid texture profile string')
            address=pm.read_uint(profile) if capacity>15 else profile
            result['texture_profile']={'name':pm.read_bytes(address,length).decode('utf-8'),
                'default_mips_dropped':pm.read_uint(profile+24)}
    except Exception as error:result['observation_error']=str(error)
    return result

def snapshot(directory):
    if sys.getwindowsversion().build!=26200:raise RuntimeError('Heap layouts are only verified for build 26200')
    pid=find_process();identity=process_identity(pid)
    if identity['sha256']!=SUPPORTED_SHA256:raise RuntimeError('Unsupported game')
    pm=pymem.Pymem(pid)
    try:
        nt=ctypes.WinDLL('ntdll').NtQueryInformationProcess
        nt.argtypes=[wintypes.HANDLE,wintypes.ULONG,ctypes.c_void_p,wintypes.ULONG,ctypes.c_void_p]
        nt.restype=wintypes.LONG
        peb=ctypes.c_size_t()
        if nt(pm.process_handle,26,ctypes.byref(peb),ctypes.sizeof(peb),None)!=0 or not peb.value:
            raise RuntimeError('Could not identify the WOW64 PEB')
        count=pm.read_uint(peb.value+0x88);array=pm.read_uint(peb.value+0x90)
        if not 0<count<=512:raise RuntimeError('Invalid heap count')
        heaps=struct.unpack('<'+'I'*count,pm.read_bytes(array,count*4))
        ownership={};details=[];errors=[]
        for heap in heaps:
            item={'heap':hex(heap),'segments':[],'large_blocks':[]}
            try:
                for offset,name,limit in ((0xa4,'segments',4096),(0x9c,'large_blocks',65536)):
                    head=heap+offset;link=pm.read_uint(head);seen=set()
                    while link!=head:
                        if not link or link in seen or len(seen)>=limit:raise RuntimeError('Unstable or invalid linked list')
                        seen.add(link)
                        if name=='segments':
                            base=link-0x10;words=struct.unpack('<15I',pm.read_bytes(base,60))
                            if words[6]!=heap or words[7]!=base:raise RuntimeError('Segment ownership mismatch')
                            item[name].append({'base':hex(base),'pages':words[8],'uncommitted_pages':words[11]})
                        else:
                            base=link;words=struct.unpack('<6I',pm.read_bytes(base,24))
                            item[name].append({'base':hex(base),'commit_size':words[4],'reserve_size':words[5]})
                        ownership[base]=(heap,name)
                        link=pm.read_uint(link)
                    if pm.read_uint(head) not in seen and seen:raise RuntimeError('List head changed during observation')
            except Exception as error:
                errors.append({'heap':hex(heap),'error':str(error)})
            details.append(item)
        context=Control(ROOT/'data/friends_control.sqlite3').status()
        diagnostic=Diagnostics(pm.process_handle,pid,directory);diagnostic.dump_attempted=True
        sample={};diagnostic.observe(sample,context)
        addresses=diagnostic.latest_report
        totals={};heap_totals={}
        for r in addresses['regions']:
            owner=ownership.get(r['allocation'])
            label=('free' if r['state']==0x10000 else 'image' if r['type']==0x1000000 else
                   'mapped' if r['type']==0x40000 else 'heap_'+owner[1] if owner else 'unattributed_private')
            state='committed' if r['state']==0x1000 else 'reserved' if r['state']==0x2000 else 'free'
            key=label+'/'+state;totals[key]=totals.get(key,0)+r['size']
            if owner:
                h=heap_totals.setdefault(hex(owner[0]),{});h[state]=h.get(state,0)+r['size']
        report={'time':time.time(),'identity':identity,'phase':context.get('phase'),'match_id':context.get('match_id'),
                'engine_owners':engine_owners(pm),
                'totals_mib':{k:round(v/2**20,2) for k,v in totals.items()},'heaps':details,
                'per_heap_mib':{k:{s:round(v/2**20,2) for s,v in h.items()} for k,h in heap_totals.items()},
                'traversal_errors':errors,'address_space':sample['address_space'],
                'limitation':'Non-atomic external snapshot. Unattributed private regions are not automatically driver memory.'}
        with (directory/'heap_ownership.jsonl').open('a',encoding='utf-8') as out:out.write(json.dumps(report)+'\n')
        return report
    finally:pm.close_process()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path);a=p.parse_args()
    directory=a.directory or ROOT/'validation'/datetime.now().strftime('heap_ownership_%Y%m%d_%H%M%S')
    directory.mkdir(parents=True,exist_ok=True)
    r=snapshot(directory)
    print(directory);print(json.dumps({k:r[k] for k in ('phase','match_id','totals_mib','traversal_errors')},indent=2))
