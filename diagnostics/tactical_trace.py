"""Bounded Frida observation hooks; never calls native game functions or sends orders.

Unlike tactical_observe, this installs temporary code instrumentation. Hooks are
removed on detach. Target unit is explicitly supplied and events are capped.
"""
import argparse
import json
import time
import frida
from tactical_map import Image, OUT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pid',type=int,required=True)
    p.add_argument('--actor',type=lambda x:int(x,0),required=True)
    p.add_argument('--duration',type=float,default=90)
    p.add_argument('--name',default='native_trace')
    a=p.parse_args()
    if not 0<a.duration<=180:p.error('duration must be 0..180 seconds')
    if not a.name.replace('_','').isalnum():p.error('invalid name')
    im=Image()
    sites=[(0x8e8c80,'movement_mode'),(0x8317c0,'actor_order'),(0xa57cf0,'direct_control'),
           (0x8eac40,'brain_order')]
    configs=[{'address':hex(addr),'name':name,'expected':list(im.data[im.offset(addr):im.offset(addr)+16])} for addr,name in sites]
    source="""
    const actor=ptr(ACTOR), configs=CONFIGS;
    let count=0;
    for(const c of configs){
      const actual=new Uint8Array(ptr(c.address).readByteArray(c.expected.length));
      if(!c.expected.every((v,i)=>actual[i]===v))throw new Error('Code mismatch '+c.address);
    }
    if(actor.add(0x78c).readPointer().readPointer().toString()!=='0xdfbed0')throw new Error('Not human brain');
    for(const c of configs){
      Interceptor.attach(ptr(c.address),{
        onEnter(args){
          if(count>=200)return;
          try{
            const ctx=this.context.ecx;
            if(c.name==='actor_order' && !ctx.equals(actor))return;
            if((c.name==='brain_order'||c.name==='movement_mode') && !ctx.add(0x20).readPointer().equals(actor))return;
            const e={event:c.name,thread:this.threadId,context:ctx.toString(),return_address:this.returnAddress.toString(),time:Date.now()};
            if(c.name==='movement_mode')e.mode=args[0].toUInt32();
            if(c.name==='actor_order'||c.name==='brain_order'){
              e.order=args[0].toString();e.order_vtable=args[0].readPointer().toString();
              const size=e.order_vtable==='0xdfa324'?44:(e.order_vtable==='0xdf92a0'?40:32);
              e.order_head=Array.from(new Uint8Array(args[0].readByteArray(size)));
              e.parameters=args[1].toString();e.parameter_bytes=Array.from(new Uint8Array(args[1].readByteArray(8)));
              this.report=e;
            }
            count++;send(e);
          }catch(e){send({error:String(e),site:c.name});}
        },
        onLeave(ret){if(this.report)send({event:this.report.event+'_return',thread:this.threadId,result:ret.toString(),time:Date.now()});}
      });
    }
    send({event:'attached',actor:actor.toString(),sites:configs.map(c=>c.name)});
    """.replace('ACTOR',str(a.actor)).replace('CONFIGS',json.dumps(configs))
    OUT.mkdir(exist_ok=True,parents=True)
    with (OUT/(a.name+'.jsonl')).open('x',encoding='utf-8') as f:
        def message(msg,data):
            f.write(json.dumps(msg)+'\n');f.flush()
            if msg.get('type')=='error' or msg.get('payload',{}).get('event')=='attached':print(json.dumps(msg),flush=True)
        session=frida.attach(a.pid)
        try:
            script=session.create_script(source);script.on('message',message);script.load()
            time.sleep(a.duration)
        finally:session.detach()
    print('Detached; observation saved.',flush=True)


if __name__=='__main__':main()
