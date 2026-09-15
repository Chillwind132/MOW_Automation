"""External, bounded census of resource repository references; never mutates refcounts."""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
from collections import Counter
import json
from pathlib import Path
import struct
import time
import pymem
from friends_host import Control
from headless_host import ROOT,find_process,process_identity,SUPPORTED_SHA256

def census(directory,seconds=20):
    pid=find_process();identity=process_identity(pid)
    if identity['sha256']!=SUPPORTED_SHA256:raise RuntimeError('Unsupported executable')
    pm=pymem.Pymem(pid)
    started=time.time();deadline=time.monotonic()+seconds
    result={'started':started,'identity':identity,'context':Control(ROOT/'data/friends_control.sqlite3').status(),
        'loaded':[],'limitation':'External non-atomic tree walk; refcounts and addresses alone do not establish leaks.'}
    seen=set();metadata=0;counts=Counter();vtables=Counter()
    try:
        head,count=struct.unpack('<2I',pm.read_bytes(0xfbb050,8))
        result['initial_entries']=count
        pending=[pm.read_uint(head+4)]
        while pending:
            if time.monotonic()>deadline:raise TimeoutError('Census time budget reached')
            node=pending.pop()
            if node==head:continue
            if not node or node in seen or len(seen)>400000:raise RuntimeError('Repository changed during walk')
            seen.add(node)
            data=pm.read_bytes(node,48);words=struct.unpack('<12I',data)
            if data[13]:raise RuntimeError('Unexpected repository sentinel')
            pending.extend([words[0],words[2]])
            wrapper=words[11]
            if not wrapper:metadata+=1;continue
            wrapper_vtable,obj=struct.unpack('<2I',pm.read_bytes(wrapper,8))
            if not obj:metadata+=1;continue
            vtable,refs,flags=struct.unpack('<3I',pm.read_bytes(obj,12))
            length,capacity=words[8:10]
            if length>4096 or capacity<length:raise RuntimeError('Invalid resource path')
            name=(pm.read_bytes(words[4],length) if capacity>15 else data[16:16+length]).decode('utf-8',errors='replace')
            suffix=Path(name).suffix.lower() or '<no extension>'
            counts[suffix]+=1;vtables[hex(vtable)]+=1
            entry={'name':name,'object':hex(obj),'wrapper':hex(wrapper),
                'vtable':hex(vtable),'references':refs,'flags':flags}
            if vtable==0xde4178:
                surface=pm.read_uint(obj+0x30)
                if surface:
                    fields=struct.unpack('<14I',pm.read_bytes(surface,56))
                    if fields[0]!=0xdeb9a4:raise RuntimeError('Unexpected bitmap surface type')
                    entry['surface']={'address':hex(surface),'texture_address':hex(fields[10]),
                        'width':fields[5],'height':fields[6],
                        'original_width':fields[12],'original_height':fields[13],
                        'format_flags':fields[4]}
            result['loaded'].append(entry)
        result['completed']=True
    except Exception as error:
        result.update(completed=False,error=str(error))
    finally:
        try:result['final_entries']=pm.read_uint(0xfbb054)
        except Exception:pass
        pm.close_process()
    result.update(finished=time.time(),visited=len(seen),metadata_only=metadata,
        loaded_count=len(result['loaded']),loaded_by_extension=dict(counts),loaded_by_vtable=dict(vtables),
        references_one=sum(x['references']==1 for x in result['loaded']),
        references_multiple=sum(x['references']>1 for x in result['loaded']))
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/f'resources_{pid}_{int(started*1000)}.json'
    path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return path,result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path)
    p.add_argument('--follow',action='store_true');p.add_argument('--hours',type=float,default=9)
    a=p.parse_args()
    if a.follow:
        deadline=time.monotonic()+a.hours*3600;previous=None
        control=Control(ROOT/'data/friends_control.sqlite3')
        while time.monotonic()<deadline and not (a.directory.parent/'STOP').exists():
            pid=find_process();context=control.status()
            key=(pid,context.get('match_id'),context.get('phase'),context.get('matches_saved'))
            if pid and key!=previous and not context.get('stale') and context.get('phase') in (
                    'playing','ready countdown','saving results / returning to lobby'):
                try:
                    path,r=census(a.directory);previous=key
                    print(path,'complete',r['completed'],'payloads',r['loaded_count'],flush=True)
                except Exception as error:print('Census observation error:',error,flush=True)
            time.sleep(5)
    else:
        path,r=census(a.directory)
        print(path);print(json.dumps({k:v for k,v in r.items() if k not in ('loaded','context','identity')},indent=2))
