// Execute the production passive reader with distinct native-layout counters.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('headless/headless_host.js','utf8').replace('// @include modules/live_game_data/bridge.js',fs.readFileSync('modules/live_game_data/bridge.js','utf8'));
const code=source.slice(source.indexOf('function battleStatisticsProbe('),source.indexOf('function readLiveHud('));
const memory=new Map(),strings=new Map(),floats=new Map();
class Pointer {
 constructor(a){this.a=Number(a)}
 add(n){return new Pointer(this.a+n)} sub(p){return new Pointer(this.a-p.a)}
 toInt32(){return this.a|0} toString(){return '0x'+this.a.toString(16)}
 isNull(){return !this.a} equals(p){return this.a===p.a}
 readPointer(){return new Pointer(this.readU32())}
 readU32(){if(!memory.has(this.a))throw Error('Unmapped read '+this);return memory.get(this.a)}
 readU8(){return this.readU32()}
 readFloat(){if(!floats.has(this.a))throw Error('Unmapped float');return floats.get(this.a)}
}
const ptr=a=>new Pointer(a),put=(a,v)=>memory.set(a,v);
function vector(a,first,count,stride){put(a,first);put(a+4,first+count*stride);put(a+8,first+count*stride)}
put(0xfed0c4,0x1000);put(0x1000,0xe317f0);put(0x1058,0x2000);
put(0x2000,0xe274dc);strings.set(0x2544,'epoch');
put(0xfe41d8,0x3000);put(0x3114,0x4000);put(0x4000,0xe07e08);
vector(0x108c,0x5000,1,0x5c);strings.set(0x5044,'2');
[0,1,83.9,3,4,5].forEach((v,i)=>floats.set(0x5000+i*4,v));
vector(0x1068,0x6000,1,4);put(0x6000,0x7000);put(0x7000,27);put(0x7004,2);
strings.set(0x7008,'BOT');strings.set(0x704c,'a');put(0x70ec,0);put(0x70f0,0);put(0x70f5,1);
put(0x4018,0x8000);put(0x8000,0xe07db4);put(0x8004,2);
put(0x8008,23);put(0x8014,7);put(0x802c,2);put(0x8038,3);
put(0x4060,0x9000);put(0x9000,0xe07dec);put(0x9004,2);put(0x9008,0xa000);put(0x900c,2);
put(0xa00d,1);put(0xa004,0xb000);
put(0xb000,0xa000);put(0xb004,0xa000);put(0xb008,0xc000);put(0xb00d,0);
put(0xc000,0xa000);put(0xc004,0xb000);put(0xc008,0xa000);put(0xc00d,0);
strings.set(0xb040,'default');floats.set(0xb058,10.8);
strings.set(0xc040,'special');floats.set(0xc058,4.5);
const ctx={ptr,va:ptr,read:p=>p.readPointer(),rva:p=>p.a,stringAt:p=>strings.get(p.a)??null};
vm.createContext(ctx);vm.runInContext(code,ctx);
const capture=()=>JSON.parse(JSON.stringify(ctx.battleStatisticsProbe(ptr(0x1000))));
const p=capture().players[0];
assert.deepEqual(p.infantry,[23,7]);assert.deepEqual(p.vehicles,[2,3]);
assert.equal(p.score,83);assert.deepEqual(p.resources,[10,4]);assert.equal(p.nativeMemberId,27);
put(0x8004,3);assert.throws(capture,/owner mismatch/);put(0x8004,2);
put(0xc004,0xffff);assert.throws(capture,/ownership/);put(0xc004,0xb000);
put(0x900c,2049);assert.throws(capture,/resource tree/);put(0x900c,2);
put(0x4018,0);assert.equal(capture().players[0].infantry,null);put(0x4018,0x8000);
put(0x8008,0);assert.deepEqual(capture().players[0].infantry,[0,7]);
vector(0x108c,0x5000,0,0x5c);assert.equal(capture().players[0].score,null);
process.stdout.write('PASS passive native counters, identity guards, missing data and resource tree bounds');
