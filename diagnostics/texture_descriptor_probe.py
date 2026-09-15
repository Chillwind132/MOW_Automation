"""Sample actual D3D texture descriptors without changing resources or settings."""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
import json
from pathlib import Path
import time
import frida
from friends_host import Control
from headless_host import ROOT,find_process,process_identity,SUPPORTED_SHA256,bounded


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('census',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();census=json.loads(args.census.read_text())
    pid=find_process();identity=process_identity(pid)
    if identity['sha256']!=SUPPORTED_SHA256 or identity!=census['identity']:
        raise RuntimeError('Supported census process identity required')
    candidates=[r for r in census['loaded'] if r.get('surface') and r['surface']['width']>=1024
                and not r['name'].startswith('resource/interface/')]
    candidates.sort(key=lambda r:(-r['surface']['width']*r['surface']['height'],r['name']))
    names=[];seen=set()
    for resource in candidates:
        hardware=resource['surface']['texture_address']
        if hardware in seen or hardware=='0x0':continue
        seen.add(hardware);names.append(resource['name'])
        if len(names)==24:break
    result={'time':time.time(),'identity':identity,'census':str(args.census),'context_before':Control(ROOT/'data/friends_control.sqlite3').status(),
        'limitation':'Bounded sample of large named textures; descriptors do not report CPU heap or total GPU residency.'}
    session=None
    try:
        with bounded(10):session=frida.attach(pid)
        script=session.create_script((ROOT/'diagnostics/texture_descriptor_probe.js').read_text())
        errors=[];script.on('message',lambda message,data:errors.append(message) if message['type']=='error' else None)
        with bounded(10):script.load()
        with bounded(12):result['probe']=script.exports_sync.probe(names)
        result['errors']=errors
    finally:
        if session:
            with bounded(5):session.detach()
    result['context_after']=Control(ROOT/'data/friends_control.sqlite3').status()
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps({'elapsed_ms':result['probe'].get('elapsed_ms'),
        'items':[{k:v for k,v in item.items() if k in ('name','width','height','logical_width','logical_height','error')}
                 for item in result['probe'].get('items',[])],
        'error':result['probe'].get('error')},indent=2))


if __name__=='__main__':main()
