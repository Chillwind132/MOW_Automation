"""Bounded passive observation of the supported engine's DX11 Present wrapper."""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
import json
from pathlib import Path
import time
import frida
from headless_host import ROOT, find_process, process_identity, SUPPORTED_SHA256, bounded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seconds', type=int, default=30, choices=range(1, 46))
    args = parser.parse_args()
    pid = find_process()
    identity = process_identity(pid)
    if identity['sha256'] != SUPPORTED_SHA256:
        raise RuntimeError('Unsupported game image')
    expected = list((ROOT / 'diagnostics/reference/mowas_2_dumped.exe').read_bytes()[0x1e5160:0x1e5168])
    source = """
    const game=Process.getModuleByName('mowas_2.exe');
    if(Process.arch!=='ia32'||!game.base.equals(ptr(0x400000)))throw Error('Unsupported layout');
    const expected=EXPECTED;
    const actual=new Uint8Array(ptr(0x5e5160).readByteArray(expected.length));
    if(expected.some((v,i)=>actual[i]!==v))throw Error('Present wrapper signature mismatch');
    const stats={calls:0,test_flag_calls:0,occluded_after:0,devices:{},threads:{},errors:[],flush_calls:0};
    let flushHook=null;
    Interceptor.attach(ptr(0x5e5160),{
      onEnter(){
        this.device=this.context.ecx;
        try {
          if(this.device.readU32()!==0xdabf34)throw Error('Unexpected device vtable');
          this.valid=true;stats.calls++;
          const tid=Process.getCurrentThreadId();stats.threads[tid]=(stats.threads[tid]||0)+1;
          if(this.device.add(0x8c).readU8())stats.test_flag_calls++;
          stats.devices[this.device.toString()]=true;
          if(!flushHook){
            const wrapper=this.device.add(0x88).readPointer();
            if(wrapper.readU32()!==0xdac3a8||wrapper.add(0x1c).readU8()!==1)throw Error('Expected immediate context wrapper');
            const context=wrapper.add(0xc).readPointer();
            const method=context.readPointer().add(111*4).readPointer();
            const owner=Process.findModuleByAddress(method);
            if(!owner||!['d3d11.dll','nvwgf2um.dll'].includes(owner.name.toLowerCase()))throw Error('Unexpected Flush implementation');
            stats.flush_method=method.toString();stats.flush_module=owner.name;
            stats.immediate_context=context.toString();
            flushHook=Interceptor.attach(method,{onEnter(args){if(args[0].equals(context))stats.flush_calls++;}});
          }
        }catch(e){this.valid=false;if(stats.errors.length<4)stats.errors.push(String(e));}
      },
      onLeave(){if(this.valid&&this.device.add(0x8c).readU8())stats.occluded_after++;}
    });
    rpc.exports={snapshot(){return stats;}};
    """.replace('EXPECTED', json.dumps(expected))
    result = {'started': time.time(), 'identity': identity,
              'scope': 'Passive engine Present-wrapper counts; no Flush, ClearState or graphics mutation. Zero calls does not identify the cause.'}
    session = None
    errors = []
    try:
        with bounded(10):
            session = frida.attach(pid)
            script = session.create_script(source)
            script.on('message', lambda m, d: errors.append(m) if m['type'] == 'error' else None)
            script.load()
        time.sleep(args.seconds)
        with bounded(5):
            result['counts'] = script.exports_sync.snapshot()
    finally:
        if session:
            with bounded(5):
                session.detach()
    result.update(ended=time.time(), errors=errors)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
