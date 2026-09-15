// Execute the actual Frida reader against captured UI fixtures, without a game.
const fs=require('fs'), vm=require('vm');
const fixture=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const source=fs.readFileSync('headless/headless_host.js','utf8');
const options=JSON.parse(process.argv[3] || '{}');
const code=source.slice(source.indexOf('function statisticsProbe('),source.indexOf('function execute('));
const pointers=new Map(), numbers=new Map(), strings=new Map(), objects=new Map();
const children=new Map();
let next=0x100000000, protectedReads=0;
for(const n of fixture.nodes) {
    const a=Number(n.address); objects.set(a,n);
    if(!children.has(n.parent)) children.set(n.parent,[]);
    children.get(n.parent).push(n);
    pointers.set(a,n.vtable); pointers.set(a+0x9c,Number(n.nativeParent ?? n.parent ?? 0));
    strings.set(a+0x2c,n.name);strings.set(a+0x44,n.text);
}
const forbidden=[];
for(const [a,n] of objects) {
    const kids=children.get(n.address)||[];
    const rows=[0xd8e30c,0xd8e478].includes(n.vtable) ? kids.filter(k=>k.vtable===0xd82e0c &&
        /^(ta|tb|p\d+|\d{17}|\d+|[\da-z]+:[a-z]+)$/.test(k.name||'')) : [];
    const ordinary=kids.filter(k=>!rows.includes(k));
    function vector(offset,items) {
        const first=next;next+=Math.max(16,items.length*4+16);
        pointers.set(a+offset,first);pointers.set(a+offset+4,first+items.length*4);
        items.forEach((item,i)=>pointers.set(first+i*4,Number(item.address)));
        return first;
    }
    vector(0x90,ordinary);
    if([0xd8e30c,0xd8e478].includes(n.vtable)) {
        const main=rows.some(k=>k.name==='ta');
        const first=vector(0x100,rows);
        if(!main && n.vtable===0xd8e30c) {
            // Huge optional detail vector: reading its entries must never happen.
            pointers.set(a+0x104,first+1000000*4);
            forbidden.push([first,first+4]);
        }
    }
    if(n.vtable===0xe1ef14) {pointers.set(a+0xd4,0);pointers.set(a+0xd8,0);}
}
class Pointer {
    constructor(a){this.a=Number(a);}
    add(n){return new Pointer(this.a+n);}
    sub(p){return new Pointer(this.a-p.a);}
    toInt32(){return this.a|0;}
    toString(){return '0x'+this.a.toString(16);}
    isNull(){return this.a===0;}
    equals(p){return this.a===p.a;}
    readPointer(){
        if(forbidden.some(([a,b])=>this.a>=a&&this.a<b)) {protectedReads++;throw Error('Optional rows accessed');}
        return new Pointer(pointers.get(this.a)||0);
    }
    readU32(){return numbers.get(this.a)||0;}
    readByteArray(){
        if(options.includeRaw===false)throw Error('Unexpected raw header read');
        return Buffer.from(objects.get(this.a).rawHeaderHex,'hex');
    }
}
const ctx={ptr:a=>new Pointer(a),read:p=>p.readPointer(),rva:p=>p.a,
    stringAt:p=>strings.get(p.a)??null};
vm.createContext(ctx);vm.runInContext(code,ctx);
const active=fixture.nodes[0].name!=='mp_statistics';
const result=ctx.statisticsProbe(fixture.nodes[0].address,active,true,options);
if(protectedReads)throw Error('Read unit details');
if(!options.pruneName && !result.omittedLists.length)throw Error('Test did not exercise optional lists');
process.stdout.write(JSON.stringify(result));
