// Exercise the actual locator while forbidding reads into unrelated UI trees.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('headless/headless_host.js','utf8');
const code=source.slice(source.indexOf('function lobbySocialContext('),source.indexOf('function socialProbe('));
const memory=new Map(),strings=new Map();
class Pointer {
    constructor(value){this.value=Number(value);}
    add(n){return new Pointer(this.value+n);}
    sub(p){return new Pointer(this.value-p.value);}
    toInt32(){return this.value|0;}
    toString(){return '0x'+this.value.toString(16);}
    isNull(){return this.value===0;}
    equals(p){return this.value===p.value;}
}
const ptr=value=>new Pointer(value);
const context={ptr,read:p=>{
    assert(memory.has(p.value),'Unexpected subtree read at '+p);
    return ptr(memory.get(p.value));
},rva:p=>p.value,stringAt:p=>strings.get(p.value),lobbyPage:()=>{},state:()=>({page:'0x1000'})};
vm.createContext(context);vm.runInContext(code,context);
function setup(names=['profile','chat','friends']) {
    memory.clear();strings.clear();
    memory.set(0x1090,0x2000);memory.set(0x1094,0x2000+names.length*4);
    names.forEach((name,i)=>{
        const address=0x3000+i*0x1000;
        memory.set(0x2000+i*4,address);memory.set(address+0x9c,0x1000);
        memory.set(address,name==='chat'?0xe0b1d4:0xe0d228);
        strings.set(address+0x2c,name==='chat'?'mp_steamsessionchat':name);
        // No child vectors exist in the mock: descending into any panel fails.
        if(name==='chat'){memory.set(address+0xf4,0x9000);memory.set(address+0xf8,0x9008);}
    });
    memory.set(0x9000,0xa000);memory.set(0xa000,0xe0be90);
}
setup();assert.strictEqual(context.lobbySocialContext().root.toString(),'0x4000');
assert.strictEqual(context.lobbySocialContext().channel.toString(),'0xa000');
setup(['chat','chat']);assert.throws(()=>context.lobbySocialContext(),/Expected one lobby chat panel/);
setup(['profile']);assert.throws(()=>context.lobbySocialContext(),/Expected one lobby chat panel/);
setup();memory.set(0x409c,0xb000);assert.throws(()=>context.lobbySocialContext(),/ownership mismatch/);
setup();memory.set(0x1094,0x2000+513*4);assert.throws(()=>context.lobbySocialContext(),/Invalid lobby page children/);
setup();assert.throws(()=>context.lobbySocialContext({deadline:0}),/time budget exceeded/);
console.log('Lobby chat locator regression checks passed');
