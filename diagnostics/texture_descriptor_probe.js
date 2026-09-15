'use strict';
// Read-only GetDesc calls on the same returning main-thread dispatch as the host.
const game=Process.getModuleByName('mowas_2.exe');
if(Process.arch!=='ia32'||!game.base.equals(ptr(0x400000)))throw Error('Unsupported image layout');
let pending=null;
function lookup(name) {
    const head=ptr(0xfbb050).readPointer();let node=head.add(4).readPointer();
    for(let depth=0;depth<64;depth++) {
        if(node.equals(head)||node.isNull())throw Error('Resource not found');
        if(node.add(13).readU8())throw Error('Unexpected resource sentinel');
        const length=node.add(32).readU32(),capacity=node.add(36).readU32();
        if(length>4096||capacity<length)throw Error('Invalid resource key');
        const key=(capacity>15?node.add(16).readPointer():node.add(16)).readUtf8String(length);
        if(key===name) {
            const wrapper=node.add(44).readPointer();if(wrapper.isNull())throw Error('Unloaded wrapper');
            return wrapper.add(4).readPointer();
        }
        node=node.add(name<key?0:8).readPointer();
    }
    throw Error('Resource lookup depth exceeded');
}
function descriptor(name) {
    const bitmap=lookup(name);
    if(bitmap.isNull()||bitmap.readU32()!==0xde4178||bitmap.add(4).readU32()===0)throw Error('Expected referenced bitmap');
    const surface=bitmap.add(0x30).readPointer();
    if(surface.isNull()||surface.readU32()!==0xdeb9a4)throw Error('Unexpected surface');
    const hardware=surface.add(0x28).readPointer();
    if(hardware.isNull()||hardware.readU32()!==0xdac990)throw Error('Expected DX11 plain texture');
    const texture=hardware.add(0x18).readPointer();
    if(texture.isNull())throw Error('Missing D3D texture');
    const method=texture.readPointer().add(0x28).readPointer(),owner=Process.findModuleByAddress(method);
    if(!owner||!['d3d11.dll','nvwgf2um.dll'].includes(owner.name.toLowerCase()))throw Error('Unexpected GetDesc implementation');
    const output=Memory.alloc(44);
    new NativeFunction(method,'void',['pointer','pointer'],{abi:'stdcall',exceptions:'propagate'})(texture,output);
    const fields=Array.from({length:11},(_,i)=>output.add(i*4).readU32());
    if(fields[0]<1||fields[0]>16384||fields[1]<1||fields[1]>16384||fields[2]<1||fields[2]>15||fields[3]<1||fields[3]>2048)throw Error('Invalid texture descriptor');
    return {name,bitmap:bitmap.toString(),hardware:hardware.toString(),get_desc_module:owner.name,
        logical_width:surface.add(0x14).readU32(),logical_height:surface.add(0x18).readU32(),
        width:fields[0],height:fields[1],mip_levels:fields[2],array_size:fields[3],dxgi_format:fields[4],
        sample_count:fields[5],sample_quality:fields[6],usage:fields[7],bind_flags:fields[8],cpu_access_flags:fields[9],misc_flags:fields[10]};
}
Interceptor.attach(ptr(0x7105a0),{
    onEnter(){this.mainTick=this.returnAddress.equals(ptr(0x663314));},
    onLeave(){
        if(!this.mainTick||!pending)return;
        const job=pending;pending=null;
        if(Date.now()>job.deadline){job.resolve({error:'Probe expired'});return;}
        const started=Date.now(),items=[];
        for(const name of job.names){
            if(Date.now()-started>100){items.push({name,error:'Main-thread time budget reached'});break;}
            try{items.push(descriptor(name));}catch(error){items.push({name,error:String(error)});}
        }
        job.resolve({thread:Process.getCurrentThreadId(),elapsed_ms:Date.now()-started,items});
    }
});
rpc.exports={probe(names){
    if(pending||!Array.isArray(names)||names.length>32||names.some(n=>typeof n!=='string'||n.length>4096))throw Error('Invalid bounded request');
    return new Promise(resolve=>{pending={names,resolve,deadline:Date.now()+10000};});
}};
