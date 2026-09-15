'use strict';
const game=Process.getModuleByName('mowas_2.exe');
const va=a=>game.base.add(a-0x400000);
if(Process.arch!=='ia32')throw Error('Expected x86');
// Python supplies signatures from the hash-checked supported dump.
for(const [address,signature] of SIGNATURES) {
  const actual=Array.from(new Uint8Array(va(address).readByteArray(signature.length/2)))
    .map(x=>x.toString(16).padStart(2,'0')).join('');
  if(actual!==signature)throw Error('Unexpected code at '+va(address));
}
const storage=Memory.alloc(2*1024*1024);
const cm=new CModule(NATIVE_SOURCE,{state:storage});
const selfTest=new NativeFunction(cm.self_test,'uint',[])();
if(selfTest!==0)throw Error('Native trace table self-test failed: '+selfTest);
const size=new NativeFunction(cm.state_size,'uint',[])();
if(size>2*1024*1024)throw Error('Trace storage too small');
const output=Memory.alloc(size);
const offset=new NativeFunction(cm.entries_offset,'uint',[])();
const countersOffset=new NativeFunction(cm.counters_offset,'uint',[])();
const take=new NativeFunction(cm.snapshot,'void',['pointer','uint']);
const allocator=va(0xfac4f0).readPointer().readPointer();
for(const [slot,address] of [[4,0x512740],[5,0x512780],[6,0x5127f0]])
  if(!allocator.add(slot*4).readPointer().equals(va(address)))throw Error('Unexpected active allocator');
Interceptor.attach(va(0x512740),{onEnter:cm.alloc_enter,onLeave:cm.alloc_leave});
Interceptor.attach(va(0x512780),{onEnter:cm.realloc_enter,onLeave:cm.alloc_leave});
Interceptor.attach(va(0x5127f0),{onEnter:cm.free_enter});
let events=[],overflow=0;
function emit(e) {
  const item={time:Date.now()/1000,...e};
  if(e.event!=='reserve' && e.event!=='virtual_free')send(item);
  if(events.length<4096)events.push(item); else overflow++;
}
function frameStack(context,caller) {
  const stack=[caller.toString()];let frame=context.ebp;
  for(let i=0;i<15;i++) {
    try {
      if(frame.isNull() || (frame.toUInt32()&3))break;
      const next=frame.readPointer(),ret=frame.add(4).readPointer();stack.push(ret.toString());
      if(next.compare(frame)<=0 || next.sub(frame).toUInt32()>1048576)break;
      frame=next;
    }catch(_){break;}
  }
  return stack;
}
Interceptor.attach(va(0x50e6a0),{onEnter(a){emit({event:'allocation_failure',requested:a[0].toUInt32(),
  stack:frameStack(this.context,this.returnAddress),stack_kind:'best_effort_frame_pointer'});}});
for(const [address,name] of [[0x9e3c60,'scene_load'],[0x9ba180,'engine_cleanup'],
  [0x73c8d0,'subsystem_cleanup'],[0x719630,'repository_prune']]) {
  Interceptor.attach(va(address),{onEnter(){this.before=va(0xfbb054).readU32();
    emit({event:name+'_enter',resources:this.before,world:va(0xfe17d4).readPointer().toString()});},
    onLeave(){emit({event:name+'_leave',before:this.before,resources:va(0xfbb054).readU32()});}});
}
// Observe only the existing same-map option query; do not replace its result.
Interceptor.attach(va(0x714260),{onEnter(){this.reload=this.returnAddress.equals(va(0x9e3cd9));},
  onLeave(r){if(this.reload)emit({event:'no_reload_caching_query',present:!!(r.toUInt32()&255)});}});
// Do not hook Windows heap/virtual-memory primitives: they are also used by
// Frida itself. External VirtualQueryEx snapshots provide reservation changes.
rpc.exports={
  checkpoint(epoch){
    // Reuse preallocated native buffers and preserve generation boundaries,
    // without constructing a megabyte-sized JS array or allocation groups.
    take(output,epoch);
    return {epoch,frida_private_heap_bytes:Frida.heapSize,counters:Array.from(new Uint32Array(output.add(countersOffset).readByteArray(24))),
      resources:va(0xfbb054).readU32(),world:va(0xfe17d4).readPointer().toString()};
  },
  snapshot(epoch){take(output,epoch);const data=new Uint32Array(output.add(offset).readByteArray(32768*36));
    const groups=new Map();let bytes=0,count=0;
    for(let i=0;i<data.length;i+=9){if(!data[i])continue;
      const stack=Array.from(data.slice(i+3,i+9)).filter(Boolean).map(x=>'0x'+x.toString(16));
      const key=data[i+2]+':'+stack.join(',');let g=groups.get(key);
      if(!g){g={birth:data[i+2],stack,bytes:0,count:0};groups.set(key,g);}g.bytes+=data[i+1];g.count++;bytes+=data[i+1];count++;
    }
    const counters=Array.from(new Uint32Array(output.add(countersOffset).readByteArray(24)));
    const pending=events;events=[];
    return {epoch,frida_private_heap_bytes:Frida.heapSize,counters,sampled_live_bytes:bytes,sampled_live_count:count,
      groups:Array.from(groups.values()).sort((a,b)=>b.bytes-a.bytes),events:pending,event_overflow:overflow,
      resources:va(0xfbb054).readU32(),world:va(0xfe17d4).readPointer().toString(),trace_storage_bytes:2*1024*1024+size};
  },
  modules(){return Process.enumerateModules().map(m=>({name:m.name,base:m.base.toString(),size:m.size,path:m.path}));}
};
