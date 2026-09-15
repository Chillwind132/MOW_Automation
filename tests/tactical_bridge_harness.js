'use strict';
// Mock native memory: validates bridge admission/serialization, never engine behavior.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');

function environment(badBuild = false) {
    const memory = new Map(), hooks = new Map(), submitted = [];
    const timers = [], coverLifecycle = [], pathLifecycle = [], reads = new Map();
    let testNow = Date.now();
    class ClockDate extends Date { static now() { return testNow; } }
    let heap = 0x20000000;
    class Pointer {
        constructor(value) { this.value = Number(value instanceof Pointer ? value.value : value); }
        add(n) { return new Pointer(this.value + Number(n)); }
        sub(n) { return new Pointer(this.value - Number(n instanceof Pointer ? n.value : n)); }
        equals(p) { return this.value === new Pointer(p).value; }
        compare(p) { return Math.sign(this.value - new Pointer(p).value); }
        toString() { return '0x' + this.value.toString(16); }
        toInt32() { return this.value | 0; }
        toUInt32() { return this.value >>> 0; }
        isNull() { return this.value === 0; }
        readByteArray(n) { reads.set(this.value, (reads.get(this.value) || 0) + 1); return Uint8Array.from({length: n}, (_, i) => memory.get(this.value + i) || 0).buffer; }
        writeByteArray(bytes) { Array.from(bytes).forEach((b, i) => memory.set(this.value + i, b)); }
        readU8() { return new DataView(this.readByteArray(1)).getUint8(0); }
        readU16() { return new DataView(this.readByteArray(2)).getUint16(0, true); }
        readU32() { return new DataView(this.readByteArray(4)).getUint32(0, true); }
        readS32() { return new DataView(this.readByteArray(4)).getInt32(0, true); }
        readFloat() { return new DataView(this.readByteArray(4)).getFloat32(0, true); }
        readPointer() { return new Pointer(this.readU32()); }
        readUtf8String(n) { return Buffer.from(new Uint8Array(this.readByteArray(n))).toString('utf8'); }
        write(n, bytes, method) {
            if (n === undefined) throw Error('missing argument');
            const buffer = new ArrayBuffer(bytes);
            new DataView(buffer)[method](0, n instanceof Pointer ? n.value : n, true);
            this.writeByteArray(new Uint8Array(buffer));
        }
        writeU8(n) { this.write(n, 1, 'setUint8'); }
        writeU16(n) { this.write(n, 2, 'setUint16'); }
        writeU32(n) { this.write(n, 4, 'setUint32'); }
        writeS32(n) { this.write(n, 4, 'setInt32'); }
        writeFloat(n) { this.write(n, 4, 'setFloat32'); }
        writePointer(n) { this.writeU32(n); }
    }
    const ptr = n => new Pointer(n);
    // Emulate a matching build. Actual retail bytes are checked by live trials.
    const signatures = vm.runInNewContext('(' + source.match(/const sites = (\{[\s\S]*?\});/)[1] + ')');
    for (const [address, hex] of Object.entries(signatures)) ptr(address).writeByteArray(Buffer.from(hex, 'hex'));
    ptr(0x84d8a0).writeByteArray(Buffer.from('558bec83ec08578bf9807f0e000f859f', 'hex'));
    ptr(0x84d0a0).writeByteArray(Buffer.from('568bf18b4e048b4160837810007428e8', 'hex'));
    if (source.includes('const pathWatchAddress')) {
        ptr(0x8c3c40).writeByteArray(Buffer.from('558bec83ec348b55105356578b028bf9', 'hex'));
        ptr(0x8b2740).writeByteArray(Buffer.from('558bec8b450c8b4d083d555555157734', 'hex'));
    }
    if (badBuild) ptr('0x715c60').writeU8(0);
    const world = ptr(0x100000), head = ptr(0x110000), node = ptr(0x110100);
    const actor = ptr(0x120000), brain = ptr(0x130000), chassis = ptr(0x140000);
    ptr('0xfe17d4').writePointer(world); world.writePointer(ptr('0xe05fe8'));
    world.add(0x30).writePointer(head); world.add(0x34).writeU32(1);
    head.add(4).writePointer(node); node.writePointer(head); node.add(8).writePointer(head);
    node.add(16).writeU16(18); node.add(20).writePointer(actor);
    actor.add(0x776).writeU16(18); actor.add(0x774).writeU8(2);
    actor.add(0x78c).writePointer(brain); brain.writePointer(ptr('0xdfbed0'));
    brain.add(0x20).writePointer(actor); actor.add(0x798).writePointer(chassis);
    chassis.writePointer(ptr('0xdf6990')); actor.add(0x32c).writePointer(ptr(0x150000));
    actor.add(0x320).writePointer(ptr(0x160000)); actor.add(0x780).writeU32(0x100);
    actor.add(0x788).writePointer(ptr(0x170000)); ptr(0x170000).writePointer(ptr('0xdf8380'));
    ptr('0xf39e64').writeU8(2); ptr('0xfbb000').writeU32(1000);
    ptr('0xfed0c4').writePointer(ptr(0x220000)); ptr(0x220000).writePointer(ptr('0xe317f0'));
    ptr(0x22000c).writeU32(1);
    const move = ptr(0x180000);
    ptr('0xfe7eac').writePointer(move); move.writePointer(ptr('0xe1a3a0')); move.add(0x2fc).writeU8(3);
    const entityHead = ptr(0x490000), entityNode = ptr(0x4a0000), coverEntity = ptr(0x4b0000);
    ptr('0xfe3ff4').writePointer(entityHead); entityHead.add(4).writePointer(entityNode);
    entityHead.add(13).writeU8(1); entityNode.writePointer(entityHead); entityNode.add(8).writePointer(entityHead);
    entityNode.add(16).writeU16(765); entityNode.add(20).writePointer(coverEntity);
    coverEntity.add(0x54).writeU16(765); coverEntity.add(0x18).writeU8(1);
    const context = vm.createContext({ptr, Process: {arch: 'ia32', getModuleByName: () => ({base: ptr('0x400000')})},
        NativeFunction: function(address, resultType, argumentTypes, options) {
            if (address.equals(ptr('0xba7c00'))) assert.equal(options.abi, 'stdcall');
            if (address.equals(ptr('0xaa3e20'))) assert.equal(options.abi, 'thiscall');
            if (address.equals(ptr('0x644480'))) assert.equal(options.abi, 'thiscall');
            return (...args) => {
                if (address.equals(ptr('0x8c44d0'))) {
                    assert.equal(options.abi,'thiscall');args[0].writePointer(args[1]);
                    pathLifecycle.push('descriptor');return args[0];
                }
                if (address.equals(ptr('0x8c3c40'))) {
                    assert.equal(options.abi,'thiscall');pathLifecycle.push('query');
                    const mode=ptr(0x790000).readU8(),task=args[0],out=args[2],origin=args[3],points=ptr(0x791000);
                    assert.equal(task.readPointer().toString(),'0xdf8728');
                    if(mode===1)return 0;
                    out.writePointer(points);out.add(4).writePointer(points.add(mode===4?25:24));
                    out.add(8).writePointer(points.add(24));out.add(0x20).writeU8(1);
                    out.add(0x21).writeU8(mode===2?1:0);out.add(0xc).writeFloat(10);
                    points.writeFloat(task.add(0xc).readFloat()+(mode===3?20:0));points.add(4).writeFloat(task.add(0x10).readFloat());
                    points.add(12).writeFloat(origin.readFloat());points.add(16).writeFloat(origin.add(4).readFloat());
                    if(mode===5)throw Error('mock path failure');
                    return 1;
                }
                if (address.equals(ptr('0x8b2740'))) {
                    assert.equal(options.abi,'mscdecl');assert.equal(args[1],2);pathLifecycle.push('release');return;
                }
                if (address.equals(ptr('0x8a68a0'))) {
                    assert.equal(options.abi, 'thiscall'); assert.equal(args[1].equals(actor), true);
                    assert.equal(args[3], 60); coverLifecycle.push('construct');
                    args[0].add(0x68).writeFloat(10); return args[0];
                }
                if (address.equals(ptr('0x8a6a50'))) {
                    coverLifecycle.push('query');
                    const mode = ptr(0x370003).readU8();
                    if (mode === 3) throw Error('mock cover query failure');
                    if (!mode) return 0;
                    const candidates = ptr(0x780000);
                    args[0].writePointer(candidates); args[0].add(4).writePointer(candidates.add(mode === 2 ? 129 : 128));
                    args[0].add(8).writePointer(candidates.add(256));
                    candidates.add(0x18).writeU16(765); candidates.add(0x58).writeFloat(.5);
                    candidates.add(0x7c).writeFloat(5); return 1;
                }
                if (address.equals(ptr('0x513b80'))) {
                    coverLifecycle.push('destroy');
                    args[0].writePointer(ptr(0)); args[0].add(4).writePointer(ptr(0)); args[0].add(8).writePointer(ptr(0));
                    return;
                }
                if (address.equals(ptr('0xbbf230'))) return ptr(0x270000);
                if (address.equals(ptr('0xbbf290'))) return ptr(0x280000).readU8();
                if (address.equals(ptr('0xaa3e20'))) return ptr(0x370000).readU8();
                if (address.equals(ptr('0x644480'))) return ptr(0x370001).readU8();
                if (address.equals(ptr('0x8a65f0')) && ptr(0x370002).readU8()) {
                    args[0].add(0x18).writeU16(765); return 1;
                }
                if (address.equals(ptr('0xba7c00'))) submitted.push({purchase: true});
                if (address.equals(ptr('0xaa9b20'))) submitted.push({type: args[1].add(4).readU16(),
                    actorIds: Array.from({length: args[1].add(0x14).readPointer().sub(args[1].add(0x10).readPointer()).toInt32() / 4},
                        (_, i) => args[1].add(0x10).readPointer().add(i * 4).readPointer().add(0x776).readU16()),
                    flags: args[1].add(0xc).readU16(), stance: args[1].add(0x1c).readS32(),
                    targetType: args[1].add(0x2c).readU32(), entity: args[1].add(0x4c).readPointer().toString(),
                    targetNameLength: args[1].add(0x90).readU32(), targetNameCapacity: args[1].add(0x94).readU32(),
                    primary: [0, 4, 8].map(o => args[1].add(0x30 + o).readFloat()),
                    secondary: [0, 4, 8].map(o => args[1].add(0x3c + o).readFloat())});
                return 0;
            };
        },
        Memory: {alloc: n => { const result = ptr(heap); heap += n + 16; return result; }},
        Interceptor: {attach: (p, handler) => { hooks.set(p.toUInt32(), handler); return {detach() {}}; }},
        rpc: {exports: {}}, setInterval: callback => { timers.push(callback); return timers.length; },
        clearInterval() {}, Date: ClockDate, Uint8Array,
    });
    vm.runInContext(source, context);
    const api = context.rpc.exports;
    function pump() {
        if (ptr('0xfbaffc').readU32()) {
            hooks.get(0x715b60).onEnter.call({returnAddress: ptr('0x665556'), context: {ecx: ptr('0xfbafdc')}});
            return;
        }
        const handler = hooks.get(0x715c60);
        const invocation = {returnAddress: ptr('0x6654d7'), context: {ecx: ptr('0xfbafdc')}};
        handler.onEnter.call(invocation); handler.onLeave.call(invocation);
    }
    async function snapshot() { const promise = api.snapshot(); pump(); return promise; }
    async function trial(options) { const promise = api.trialstance(options); pump(); return promise; }
    return {ptr, actor, brain, world, hooks, submitted, coverLifecycle, pathLifecycle, reads, api, snapshot, trial, pump,
        elapse: milliseconds => { testNow += milliseconds; },
        advance: milliseconds => { testNow += milliseconds; timers.forEach(callback => callback()); }};
}

(async () => {
    if (source.includes('const pathWatchAddress')) {
        let passed = 0;
        for (const variation of ['valid', 'ordinary', 'foreign', 'oversized']) {
            const e=environment(); await e.snapshot();
            const descriptor=e.ptr(0x7300000),output=e.ptr(0x7310000),origin=e.ptr(0x7320000);
            const task=e.ptr(0x7330000),points=e.ptr(0x7340000);
            descriptor.writePointer(e.actor);task.writePointer(e.ptr(variation==='ordinary'?'0xdf8728':'0xdf9858'));
            task.add(4).writeU8(1);task.add(8).writeFloat(100000);
            task.add(0xc).writeFloat(100);task.add(0x10).writeFloat(200);
            output.writePointer(points);output.add(4).writePointer(points.add(variation==='oversized'?4097*12:24));
            output.add(8).writePointer(output.add(4).readPointer());output.add(0x20).writeU8(1);
            if(variation==='foreign')e.actor.add(0x774).writeU8(3);
            const hook=e.hooks.get(0x8c3c40),invocation={context:{ecx:task},returnAddress:e.ptr(0x8d2f40)};
            hook.onEnter.call(invocation,[descriptor,output,origin]);hook.onLeave.call(invocation,e.ptr(1));
            e.hooks.get(0x8b2740).onEnter.call({},[points,e.ptr(2)]);
            const raw=await e.snapshot(),events=raw.events.filter(x=>x.kind==='native_path_result');
            assert.equal(events.length,['valid','ordinary'].includes(variation)?1:0);
            if(events.length){assert.equal(events[0].pointCount,2);assert.equal(events[0].resultByte,1);}
            assert.equal(raw.events.filter(x=>x.kind==='native_path_release').length,events.length);
            if(variation==='oversized')assert.match(raw.fault,/path trace vector/);
            assert.equal(e.submitted.length,0);passed++;
        }
        console.log(JSON.stringify({passed,nativeBehavior:'mocked'}));return;
    }
    if (source.includes('const humanOpponentTrial = true;')) {
        let passed=0;
        for(const variation of ['valid','ally','missing','duplicate','wrong_host','changed_owner','changed_team','bots_only','excess_humans']) {
            const e=environment(),vector=e.ptr(0x7200000),service=e.ptr(0x7210000),card=e.ptr(0x7220000),rows=e.ptr(0x7230000);
            e.api.capabilities().contacts=false;
            e.ptr('0xfead5c').writePointer(vector);e.ptr('0xfead60').writePointer(vector.add(4));
            vector.writePointer(service);service.writePointer(e.ptr('0xde0fd0'));service.add(8).writeU32(8);
            service.add(0x184).writePointer(card);service.add(0x20).writeU32(2);
            card.writePointer(e.ptr('0xe274dc'));card.add(0xcc).writeU32(variation==='wrong_host'?3:2);
            const count=variation==='excess_humans'?5:2;
            card.add(0x4f4).writePointer(rows);card.add(0x4f8).writePointer(rows.add(count*4));
            for(let n=0;n<count;n++) {
                const row=e.ptr(0x7240000+n*0x1000);rows.add(n*4).writePointer(row);
                row.add(4).writeU32(n&&variation==='bots_only'?2:1);
                row.add(8).writeU32(n?variation==='duplicate'?2:n+2:variation==='missing'?10:2);
                row.add(0x50).writeByteArray(Buffer.from(n&&variation!=='ally'?'a':'b'));
                row.add(0x60).writeU32(1);row.add(0x64).writeU32(15);
            }
            const initial=await e.snapshot();
            if(['valid','changed_owner','changed_team'].includes(variation)) {
                assert.ok(initial.botTrialRoster);
                if(variation!=='valid') {
                    if(variation==='changed_owner')e.ptr('0xf39e64').writeU8(3);
                    else e.ptr(0x7241050).writeByteArray(Buffer.from('b'));
                    const result=await e.trial({generation:initial.generation,revision:0,sequence:1,id:'18',incarnation:1,action:'stance',stance:1});
                    assert.ok(result.error);
                }
            } else assert.ok(initial.error,variation);
            assert.equal(e.submitted.length,0);passed++;
        }
        console.log(JSON.stringify({passed}));return;
    }
    if (source.includes('function botRosterGuard()')) {
        let passed = 0;
        for (const variation of ['valid', 'remote', 'duplicate', 'owner', 'changed', 'missing',
            'adopt','adopt_manual','adopt_timeout','adopt_control', 'remapped', 'remapped_remote', 'changed_owner']) {
            const e = environment(), vector = e.ptr(0x7200000), service = e.ptr(0x7210000);
            const card = e.ptr(0x7220000), rows = e.ptr(0x7230000), human = e.ptr(0x7240000), bot = e.ptr(0x7250000);
            e.api.capabilities().contacts = false; // Isolate scope guard from sensor fixtures.
            e.ptr('0xfead5c').writePointer(vector); e.ptr('0xfead60').writePointer(vector.add(4));
            vector.writePointer(service); service.writePointer(e.ptr('0xde0fd0')); service.add(8).writeU32(8);
            service.add(0x184).writePointer(card); service.add(0x20).writeU32(2);
            card.writePointer(e.ptr('0xe274dc')); card.add(0xcc).writeU32(variation === 'owner' ? 3 : 2);
            card.add(0x4f4).writePointer(rows); card.add(0x4f8).writePointer(rows.add(8));
            rows.writePointer(human); rows.add(4).writePointer(bot);
            human.add(4).writeU32(1); human.add(8).writeU32(variation === 'missing' ? 5 : 2);
            bot.add(4).writeU32(variation === 'remote' ? 1 : 2);
            bot.add(8).writeU32(variation === 'duplicate' ? 2 : 3);
            if (variation.startsWith('remapped')) {
                service.add(0x20).writeU32(4); card.add(0xcc).writeU32(4); human.add(8).writeU32(4);
                if (variation === 'remapped_remote') bot.add(4).writeU32(1);
            }
            if(variation.startsWith('adopt'))e.brain.add(0x210).writeU32(0x1000);
            let snapshot = await e.snapshot();
            if (['valid', 'changed', 'remapped', 'changed_owner'].includes(variation) || variation.startsWith('adopt')) {
                assert.ok(snapshot.botTrialRoster);
                if (variation === 'changed' || variation === 'changed_owner') {
                    if (variation === 'changed') bot.add(8).writeU32(4);
                    else e.ptr('0xf39e64').writeU8(3);
                    const reply = await e.trial({generation:snapshot.generation, revision:0, sequence:1,
                        id:snapshot.units[0].id, incarnation:1, action:'stance', stance:1});
                    assert.match(reply.error, /roster changed/);
                }
                if(variation.startsWith('adopt')) {
                    const reply=await e.trial({generation:snapshot.generation,revision:0,sequence:1,
                        id:'18',incarnation:1,unitRevision:0,action:'mode',mode:0,adoptAfterMode:true});
                    assert.equal(reply.status,'serialized');
                    assert.equal((await e.snapshot()).units[0].enrolled,false,'serialization is not observed mode completion');
                    e.brain.add(0x210).writeU32(0);
                    if(variation==='adopt_timeout')e.ptr('0xfbb000').writeU32(4000);
                    if(variation==='adopt_control')e.brain.add(0x214).writeU32(1);
                    if(variation==='adopt_manual') {
                        const command=e.ptr(0x790000),addressed=e.ptr(0x791000);
                        command.add(4).writeU8(1);command.add(0x10).writePointer(addressed);
                        command.add(0x14).writePointer(addressed.add(4));addressed.writePointer(e.actor);
                        e.hooks.get(0xaaa1a0).onEnter.call({context:{ecx:command},returnAddress:e.ptr(1)});
                    }
                    assert.equal((await e.snapshot()).units[0].enrolled,variation==='adopt');
                }
            } else assert.match(snapshot.error, /Bot trial/);
            assert.equal(e.submitted.length, variation.startsWith('adopt')?1:0);
            passed++;
        }
        console.log(JSON.stringify({passed, nativeBehavior:'mocked'}));
        return;
    }
    assert.throws(() => environment(true), /Unsupported/);
    let passed = 1;
    {
        const e=environment(), raw=await e.snapshot();
        e.ptr(0x140020).writeU32(3);
        const reply=await e.trial({generation:raw.generation,revision:raw.commandRevision,
            id:'18',incarnation:1,sequence:1,action:'move',destination:[10,0,0]});
        assert.equal(reply.rejected,true);assert.match(reply.error,/Unsupported current infantry stance/);
        assert.equal(e.submitted.length,0);passed++;
    }
    for (const variation of ['valid', 'unproven', 'manual_member', 'manual_leader', 'unrelated_manual',
        'group_changed', 'hold_member', 'direct_leader', 'new_match', 'transfer']) {
        const e=environment(), head=e.ptr(0x110000), squad=e.ptr(0x500000), vector=e.ptr(0x510000);
        const leader=e.ptr(0x600000), leaderBrain=e.ptr(0x610000), other=e.ptr(0x620000), otherBrain=e.ptr(0x630000);
        for (const [actor,brain,id,node] of [[leader,leaderBrain,19,e.ptr(0x110200)],[other,otherBrain,20,e.ptr(0x110300)]]) {
            actor.writeByteArray(new Uint8Array(e.actor.readByteArray(0x800)));
            brain.writeByteArray(new Uint8Array(e.brain.readByteArray(0x300)));
            actor.add(0x78c).writePointer(brain); actor.add(0x776).writeU16(id); brain.add(0x20).writePointer(actor);
            node.writePointer(head); node.add(8).writePointer(id===19?e.ptr(0x110300):head);
            node.add(16).writeU16(id); node.add(20).writePointer(actor);
        }
        e.ptr(0x110100).add(8).writePointer(e.ptr(0x110200)); e.world.add(0x34).writeU32(3);
        e.brain.add(0x8c).writePointer(squad); leaderBrain.add(0x8c).writePointer(squad);
        squad.add(0x58).writePointer(vector); squad.add(0x5c).writePointer(vector.add(8));
        squad.add(0x70).writePointer(leader); vector.writePointer(e.actor); vector.add(4).writePointer(leader);
        leaderBrain.add(0x210).writeU32(0x1000);
        const before=await e.snapshot();
        const request={id:'18',incarnation:1,generation:before.generation,revision:0,sequence:1,
            action:'move',destination:[100,0,0],requireEnrolled:true,unitRevision:0,
            followLeader:{id:'19',incarnation:1,revision:0}};
        if(variation!=='unproven') assert.equal((await e.trial(request)).status,'serialized');
        e.brain.add(0x210).writeU32(0x2000); leaderBrain.add(0x210).writeU32(0x2000);
        if(variation==='group_changed') { vector.add(8).writePointer(other); squad.add(0x5c).writePointer(vector.add(12)); }
        if(variation==='hold_member') e.brain.add(0x210).writeU32(0x1000);
        if(variation==='direct_leader') leaderBrain.add(0x214).writeU32(1);
        if(variation==='transfer') leader.add(0x774).writeU8(3);
        if(variation==='new_match') e.ptr('0xfbb000').writeU32(0);
        if(['manual_member','manual_leader','unrelated_manual'].includes(variation)) {
            const command=e.ptr(0x790000),addressed=e.ptr(0x791000);
            command.add(4).writeU8(1); command.add(0x10).writePointer(addressed);
            command.add(0x14).writePointer(addressed.add(4));
            addressed.writePointer(variation==='manual_member'?e.actor:variation==='manual_leader'?leader:other);
            e.hooks.get(0xaaa1a0).onEnter.call({context:{ecx:command},returnAddress:e.ptr(1)});
        }
        const after=await e.snapshot(), member=after.units.find(u=>u.id==='18');
        const expected=['valid','unrelated_manual'].includes(variation);
        assert.equal(member.controllerGroup,expected,variation);
        assert.equal(member.enrolled,expected,variation);
        if(expected) {
            assert.equal(member.revision,0,'native grouping does not simulate manual reclamation');
            const repeated=await e.trial({...request,revision:after.commandRevision,sequence:2});
            assert.equal(repeated.status,'serialized','verified group mode allows the next paired leg');
        }
        passed++;
    }
    {
        const e=environment(), squad=e.ptr(0x500000), vector=e.ptr(0x510000), head=e.ptr(0x110000);
        const actorBytes=e.actor.readByteArray(0x800), brainBytes=e.brain.readByteArray(0x300);
        const members=[];
        const sharedDefinition=e.ptr(0xa00000),sharedProjectile=e.ptr(0xa01000);
        for(const [definition,type,name] of [[sharedDefinition,'0xdf5fc0','garand'],[sharedProjectile,'0xdf61d0','garand_clip']]) {
            definition.writePointer(e.ptr(type));definition.add(0x10).writeByteArray(Buffer.from(name));
            definition.add(0x20).writeU32(name.length);definition.add(0x24).writeU32(15);
        }
        squad.add(0x58).writePointer(vector);squad.add(0x5c).writePointer(vector.add(12*4));
        e.world.add(0x34).writeU32(12);head.add(4).writePointer(e.ptr(0x520000));
        for(let i=0;i<12;i++) {
            const actor=e.ptr(0x600000+i*0x1000), brain=e.ptr(0x700000+i*0x1000), node=e.ptr(0x520000+i*0x100);
            actor.writeByteArray(new Uint8Array(actorBytes));brain.writeByteArray(new Uint8Array(brainBytes));
            actor.add(0x776).writeU16(18+i);actor.add(0x78c).writePointer(brain);
            brain.add(0x20).writePointer(actor);brain.add(0x8c).writePointer(squad);
            node.writePointer(head);node.add(8).writePointer(i===11?head:node.add(0x100));
            node.add(16).writeU16(18+i);node.add(20).writePointer(actor);
            vector.add(i*4).writePointer(actor);members.push(actor);
            const wr=e.ptr(0x900000+i*0x1000),weapon=wr.add(0x100),ammo=wr.add(0x200),item=wr.add(0x300),slots=wr.add(0x400);
            actor.add(0x794).writePointer(wr);wr.writePointer(e.ptr('0xdf50d8'));wr.add(0x3c).writePointer(actor);
            wr.add(0x30).writeS32(-1);wr.add(0x20).writePointer(slots);wr.add(0x24).writePointer(slots.add(4));slots.writePointer(weapon);
            weapon.writePointer(e.ptr('0xdf51f0'));weapon.add(0x54).writePointer(actor);weapon.add(0x58).writePointer(sharedDefinition);
            weapon.add(0x64).writePointer(ammo);weapon.add(0xdc).writePointer(item);ammo.writePointer(e.ptr('0xdf525c'));ammo.add(4).writePointer(weapon);
            item.writePointer(e.ptr('0xdf31b8'));item.add(0x2c).writeU32(8);item.add(0x28).writePointer(sharedProjectile);
        }
        e.reads.clear();
        const first=await e.snapshot();
        assert.equal(first.fault,null);assert.equal(first.units.length,12);
        assert.equal(e.reads.get(vector.value),1,'shared squad vector read once per inspection');
        assert(first.units.every(u=>u.squadMembers.length===12));
        assert(first.units.every(u=>u.ammunition.weaponModel==='garand' && u.ammunition.projectileModel==='garand_clip'));
        assert.equal(e.reads.get(sharedDefinition.add(0x20).value),1,'shared weapon name decoded once per snapshot');
        assert.equal(e.reads.get(sharedProjectile.add(0x20).value),1,'shared loaded projectile name decoded once per snapshot');
        const fullReads=[...e.reads.values()].reduce((a,b)=>a+b,0);
        e.reads.clear();
        const order=await e.trial({id:'18',incarnation:1,generation:first.generation,
            revision:0,sequence:1,action:'stance',stance:1,requireEnrolled:true,unitRevision:0});
        assert.equal(order.status,'serialized');
        const commandReads=[...e.reads.values()].reduce((a,b)=>a+b,0);
        assert(commandReads < fullReads*.75,'target preflight reduces fixture memory reads by at least 25%');
        assert(!e.reads.has(members[1].add(0x798).value),'unrelated chassis omitted from targeted preflight');
        const unchanged=await e.snapshot();
        assert(unchanged.units.every(u=>u.enrolled && u.revision===0),'target preflight preserves other enrollment');
        sharedProjectile.add(0x10).writeByteArray(Buffer.from('other_round'));sharedProjectile.add(0x20).writeU32(11);
        assert((await e.snapshot()).units.every(u=>u.ammunition.projectileModel==='other_round'),'no stale name cache across snapshots');
        squad.add(0x70).writePointer(members[11]);members[11].add(0x44).writeFloat(-1000);
        const follow={id:'18',incarnation:1,generation:first.generation,revision:0,sequence:2,
            action:'move',destination:[100,0,0],requireEnrolled:true,unitRevision:0,
            followLeader:{id:'29',incarnation:1,revision:0}};
        const paired=await e.trial(follow);
        assert.equal(paired.status,'serialized');
        assert.deepEqual(e.submitted[1].actorIds,[18,29],'exactly the moving member and its leader; no full-squad vector');
        assert.deepEqual(e.submitted[1].primary,[100,0,0],'member destination preserved');
        assert.equal(paired.followingLeader.id,'29');
        for (const variation of ['incarnation','revision','direct_control','different_leader','wrong_action']) {
            const options={...follow,sequence:++follow.sequence,followLeader:{...follow.followLeader}};
            if(variation==='incarnation')options.followLeader.incarnation=2;
            if(variation==='revision')options.followLeader.revision=1;
            if(variation==='direct_control')members[11].add(0x78c).readPointer().add(0x214).writeU32(1);
            if(variation==='different_leader')squad.add(0x70).writePointer(members[10]);
            if(variation==='wrong_action'){options.action='stance';options.stance=1;}
            assert.equal((await e.trial(options)).rejected,true,variation);
            members[11].add(0x78c).readPointer().add(0x214).writeU32(0);
            squad.add(0x70).writePointer(members[11]);
        }
        members[11].add(0x774).writeU8(9);
        const second=await e.snapshot();
        assert.equal(second.units.length,11);
        assert(second.units.every(u=>u.squadMembers.length===11),'ownership refreshed on next inspection');
        squad.add(0x5c).writePointer(vector.add(129*4));
        assert.match((await e.snapshot()).error,/Invalid infantry squad/);
        assert.equal(e.submitted.length,2);passed++;
    }
    // Emission is mocked: prove ownership/revision behavior, not native UI acceptance.
    for (const type of [4, 5]) {
        const e = environment(); await e.snapshot();
        const command = e.ptr(0x190000), vector = e.ptr(0x1a0000);
        command.add(0x10).writePointer(vector); command.add(0x14).writePointer(vector.add(4));
        vector.writePointer(e.actor); command.add(4).writeU8(1);
        const invocation = {context: {ecx: command}, returnAddress: e.ptr(0xa89af4)};
        e.hooks.get(0xaaa1a0).onEnter.call(invocation);
        const suspended = await e.snapshot();
        assert.equal(suspended.units[0].enrolled, false);
        command.add(4).writeU8(type); command.add(0x26).writeU8(0);
        command.add(0xc).writeU16(0x40);
        e.hooks.get(0xaaa1a0).onEnter.call(invocation);
        const resumed = await e.snapshot(), event = resumed.events.find(x => x.kind === 'player_command');
        assert.equal(resumed.units[0].enrolled, type === 5);
        assert.equal(resumed.units[0].revision, suspended.units[0].revision + (type === 5 ? 1 : 0));
        assert.equal(event.flags, 0x40); assert.equal(event.caller, e.ptr(0xa89af4).toString());
        assert.deepEqual(Array.from(event.previouslySuspendedIds), type === 5 ? ['18'] : []);
        assert.equal(e.submitted.length, 0); passed++;
    }
    for (const scope of ['single','empty','foreign_member','changed']) {
        const e=environment(),squad=e.ptr(0x790000),members=e.ptr(0x791000),foreign=e.ptr(0x792000);
        e.ptr(0x13008c).writePointer(squad);squad.add(0x70).writePointer(e.actor);
        squad.add(0x58).writePointer(members);squad.add(0x5c).writePointer(members.add(scope==='empty'?0:scope==='foreign_member'?8:4));
        members.writePointer(e.actor);members.add(4).writePointer(foreign);foreign.add(0x774).writeU8(4);
        const raw=await e.snapshot();assert.equal(raw.units[0].squadLeader,true);
        assert.equal(raw.units[0].individualOrder,['single','changed'].includes(scope));
        if(scope==='changed')squad.add(0x5c).writePointer(members.add(8));
        const reply=await e.trial({generation:raw.generation,revision:0,sequence:1,id:'18',incarnation:1,action:'move',destination:[10,0,0]});
        assert.equal(reply.status==='serialized',scope==='single');
        assert.equal(e.submitted.length,scope==='single'?1:0);passed++;
    }
    for(const mode of [0,1,2,3,4,5]) {
        const e=environment(),raw=await e.snapshot(),unit=raw.units[0];e.ptr(0x790000).writeU8(mode);
        const reply=await e.trial({generation:raw.generation,revision:0,sequence:1,id:unit.id,
            incarnation:unit.incarnation,action:'path_query',destination:unit.position});
        if(mode>=4)assert.ok(reply.error);
        else {assert.equal(reply.status,'queried');assert.equal(reply.reachesRequestedPoint,mode===0);assert.equal(reply.vectorReleased,true);}
        assert.equal(e.pathLifecycle.filter(x=>x==='release').length,mode===1?0:1);
        assert.equal(e.submitted.length,0);passed++;
    }
    for (const variation of ['stance', 'move', 'stale_match', 'stale_incarnation', 'ownership',
                             'inactive', 'manual', 'direct', 'duplicate', 'reuse', 'stopped',
                             'sensor_query', 'sensor_tracked_hidden', 'sensor_known_hidden', 'sensor_known_visible', 'sensor_overflow', 'purchase_success', 'purchase_denied',
                             'purchase_assault','purchase_anti_tank','purchase_badtemplate','purchase_bad_name','purchase_bad_id',
                             'purchase_foreign', 'purchase_no_team', 'purchase_query_unavailable', 'foreign_command',
                             'weapon_query', 'weapon_owner', 'weapon_ammo_owner', 'weapon_unsupported',
                             'weapon_count', 'weapon_empty', 'weapon_index', 'weapon_vector',
                             'completed_match', 'unknown_manager', 'dead_health', 'disabled_health',
                             'barricade_query', 'barricade_denied', 'barricade_type',
                             'grenade_smoke','grenade_fragmentation','grenade_anti_tank','grenade_bad_kind','grenade_bad_type',
                             'barricade_no_match', 'barricade_no_filter', 'barricade_duplicate', 'barricade_count',
                             'barricade_build', 'barricade_build_denied', 'barricade_build_many',
                             'barricade_build_far', 'barricade_build_entity', 'barricade_build_completed', 'cover_query',
                             'barricade_build_vertical', 'barricade_build_diagonal', 'barricade_build_zero', 'barricade_build_nonfinite', 'direction_wrong_action',
                             'barricade_held_shared', 'barricade_held_separate', 'player_emission_disabled']) {
        const e = environment(), initial = await e.snapshot();
        const options = {id: '18', incarnation: 1, generation: initial.generation, revision: 0, sequence: 1, stance: 2};
        if (variation === 'move') { options.action = 'move'; delete options.stance; options.destination = [600, 0, 0]; }
        if (variation === 'player_emission_disabled') options.asPlayerCommand = true;
        if (variation === 'direction_wrong_action') options.buildDirection = [0, 1];
        if (variation === 'cover_query') { options.action = 'cover_query'; e.ptr(0x370002).writeU8(1); }
        if (variation.startsWith('barricade_') || variation.startsWith('grenade_')) {
            options.action = 'barricade_query';
            e.ptr('0xfe84b0').writePointer(e.ptr(0x380000));
            e.ptr(0x380000).writePointer(e.ptr(variation === 'barricade_type' ? 1 : '0xe1b2a8'));
            e.ptr(0x3802fc).writeU8(37); e.ptr(0x370000).writeU8(variation === 'barricade_denied' ? 0 : 1);
            if(variation.startsWith('grenade_')) {
                options.action='grenade_query';
                options.grenadeKind=variation==='grenade_fragmentation'?'fragmentation':variation==='grenade_anti_tank'?'anti_tank':'smoke';
                const kinds={smoke:[0xfe7ef4,0xe1b12c,25],fragmentation:[0xfe7eec,0xe1af18,23],anti_tank:[0xfe7ef0,0xe1afbc,24]};
                const [address,vtable,id]=kinds[options.grenadeKind];
                e.ptr(address).writePointer(e.ptr(0x380000));e.ptr(0x380000).writePointer(e.ptr(variation==='grenade_bad_type'?1:vtable));
                e.ptr(0x3802fc).writeU8(id);
                if(variation==='grenade_bad_kind')options.grenadeKind='__proto__';
            }
            e.ptr(0x370001).writeU8(variation === 'barricade_no_match' ? 0 : 1);
            e.ptr(0x3802a0).writePointer(e.ptr(0x400000));
            e.ptr(0x3802a4).writePointer(e.ptr(variation === 'barricade_no_filter' ? 0x400000 : 0x400044));
            e.ptr(0x150014).writePointer(e.ptr(0x390000));
            e.ptr(0x390068).writePointer(e.ptr(0x3a0000)); e.ptr(0x3a0000).writePointer(e.ptr('0xdf3e1c'));
            e.ptr(0x3a000c).writePointer(e.ptr(0x3b0000));
            e.ptr(0x3a0010).writePointer(e.ptr(variation === 'barricade_duplicate' ? 0x3b0008 : 0x3b0004));
            e.ptr(0x3b0000).writePointer(e.ptr(0x3c0000)); e.ptr(0x3b0004).writePointer(e.ptr(0x3c0000));
            e.ptr(0x3c0000).writePointer(e.ptr('0xdf31b8')); e.ptr(0x3c0020).writePointer(e.ptr(0x3d0000));
            e.ptr(0x3c0024).writeU32(variation === 'barricade_count' ? 10001 : 2);
            e.ptr(0x3c002c).writeU32(8); // Loaded ammunition is not the stack count.
            e.ptr(0x39005c).writePointer(e.ptr(0x450000)); e.ptr(0x390060).writePointer(e.ptr(0x450008));
            e.ptr(0x450000).writePointer(e.ptr(0x460000)); e.ptr(0x450004).writePointer(e.ptr(0x470000));
            e.ptr(0x460000).writePointer(e.ptr('0xdf37e4')); e.ptr(0x470000).writePointer(e.ptr('0xdf383c'));
            e.ptr(0x460008).writeByteArray(Buffer.from('hand_left')); e.ptr(0x470008).writeByteArray(Buffer.from('hand_right'));
            if (variation === 'barricade_held_shared') e.ptr(0x4702a0).writePointer(e.ptr(0x3c0000));
            if (variation === 'barricade_held_separate') {
                e.ptr(0x4702a0).writePointer(e.ptr(0x480000)); e.ptr(0x480000).writePointer(e.ptr('0xdf31b8'));
                e.ptr(0x480020).writePointer(e.ptr(0x3d0000)); e.ptr(0x480024).writeU32(1);
                e.ptr(0x3c0024).writeU32(0);
            }
            if (variation.startsWith('barricade_build')) {
                options.action = 'barricade'; options.destination = [100, 0, 0];
                e.ptr(0x3c0024).writeU32(variation === 'barricade_build_many' ? 2 : 1);
                e.ptr(0x3805a8).writeByteArray(Buffer.from('sandbag3'));
                e.ptr(0x3805b8).writeU32(8); e.ptr(0x3805bc).writeU32(15);
                if (variation === 'barricade_build_denied') e.ptr(0x370000).writeU8(0);
                if (variation === 'barricade_build_far') options.destination[0] = 151;
                if (variation === 'barricade_build_entity') e.ptr(0x3805b8).writeU32(7);
                if (variation === 'barricade_build_completed') e.ptr(0x22000c).writeU32(3);
                if (variation === 'barricade_build_vertical') options.buildDirection = [0, 7];
                if (variation === 'barricade_build_diagonal') options.buildDirection = [3, 4];
                if (variation === 'barricade_build_zero') options.buildDirection = [0, 0];
                if (variation === 'barricade_build_nonfinite') options.buildDirection = [Infinity, 1];
            }
        }
        if (variation.startsWith('weapon_')) {
            options.action = 'weapon_query';
            const weaponry = e.ptr(0x300000), weapon = e.ptr(0x310000), ammo = e.ptr(0x320000);
            const item = e.ptr(0x330000), vector = e.ptr(0x340000);
            e.actor.add(0x794).writePointer(weaponry); weaponry.writePointer(e.ptr('0xdf50d8'));
            weaponry.add(0x3c).writePointer(e.actor); weaponry.add(0x30).writeS32(-1);
            weaponry.add(0x20).writePointer(vector);
            weaponry.add(0x24).writePointer(vector.add(variation === 'weapon_empty' ? 0 : 4));
            vector.writePointer(weapon); weapon.writePointer(e.ptr('0xdf51f0'));
            weapon.add(0x54).writePointer(variation === 'weapon_owner' ? e.ptr(0) : e.actor);
            weapon.add(0x64).writePointer(ammo); ammo.writePointer(e.ptr(variation === 'weapon_unsupported' ? 1 : '0xdf525c'));
            ammo.add(4).writePointer(variation === 'weapon_ammo_owner' ? e.ptr(0) : weapon);
            ammo.add(0x18).writeU16(0x12); ammo.add(0x14).writeU32(2000);
            weapon.add(0xdc).writePointer(item); item.writePointer(e.ptr('0xdf31b8'));
            item.add(0x2c).writeU32(variation === 'weapon_count' ? 10001 : 8);
            if (variation === 'weapon_index') weaponry.add(0x30).writeS32(0);
            if (variation === 'weapon_vector') weaponry.add(0x24).writePointer(vector.add(33 * 4));
        }
        if (variation.startsWith('sensor_')) {
            options.action = 'sensor_query';
            const sensor = e.ptr(0x1b0000), record = e.ptr(0x1c0000), vector = e.ptr(0x1d0000);
            e.actor.add(0x790).writePointer(sensor); sensor.writePointer(e.ptr('0xdf7c04'));
            sensor.add(0x1c).writePointer(e.actor); sensor.add(0x28).writePointer(vector);
            sensor.add(0x2c).writePointer(vector.add(variation === 'sensor_overflow' ? 4097 * 4 : 4));
            vector.writePointer(record); record.writeU32(0x10000000);
            record.add(8).writePointer(e.ptr(0xdeadbeef)); // deliberately not a live registry actor
            if (variation.startsWith('sensor_known_')) record.add(8).writePointer(e.actor);
            if (variation === 'sensor_known_visible') { record.writeU32(0x30000000); record.add(4).writeU32(0x40); }
            record.add(0x10).writeFloat(123); record.add(0x44).writeU32(900);
            record.add(0x40).writeU32(700); sensor.add(0xb0).writeU32(800);
            if (variation === 'sensor_tracked_hidden') sensor.add(0x74).writePointer(record);
        }
        if (variation.startsWith('purchase_')) {
            options.action = variation === 'purchase_query_unavailable' ? 'purchase_query' : 'purchase';
            if (variation !== 'purchase_no_team') {
                e.ptr('0xfed0c4').writePointer(e.ptr(0x220000));
                e.ptr(0x220068).writePointer(e.ptr(0x240000));
                e.ptr(0x22006c).writePointer(e.ptr(0x240004));
                e.ptr(0x240000).writePointer(e.ptr(0x230000)); e.ptr(0x230004).writeU8(2);
                e.ptr(0x23004c).writeU8(97); e.ptr(0x23005c).writeU32(1); e.ptr(0x230060).writeU32(15);
            }
            e.ptr('0xf3c930').writePointer(e.ptr(0x250000)); e.ptr(0x250000).writePointer(e.ptr('0xe31eb0'));
            e.ptr(0x250004).writePointer(e.ptr(0x250100)); e.ptr(0x250008).writePointer(e.ptr(0x250104));
            e.ptr(0x250100).writePointer(e.ptr(0x260000)); e.ptr(0x260000).writePointer(e.ptr('0xe31eb8'));
            e.ptr(0x260008).writeByteArray(Buffer.from('riflemans(usa)\0')); e.ptr(0x260388).writeU16(854);
            if(['purchase_assault','purchase_anti_tank'].includes(variation)) {
                options.purchaseTemplate=variation==='purchase_assault'?'assault':'anti_tank';
                e.ptr(0x260008).writeByteArray(Buffer.from(variation==='purchase_assault'?'smgs2(usa)\0':'riflemans_bar(usa)\0'));
                e.ptr(0x260388).writeU16(variation==='purchase_assault'?879:855);
            }
            if(variation==='purchase_badtemplate')options.purchaseTemplate='__proto__';
            if(variation==='purchase_bad_name')e.ptr(0x260008).writeU8(0);
            if(variation==='purchase_bad_id')e.ptr(0x260388).writeU16(999);
            e.ptr(0x270000).writePointer(e.ptr(0x260000));
            e.ptr(0x270004).writeU8(variation === 'purchase_foreign' ? 3 : 2);
            e.ptr(0x280000).writeU8(['purchase_denied', 'purchase_query_unavailable'].includes(variation) ? 0 : 1);
        }
        if (variation === 'stale_match') options.generation++;
        if (variation === 'stale_incarnation') options.incarnation++;
        if (variation === 'ownership') e.actor.add(0x774).writeU8(3);
        if (variation === 'inactive') e.actor.add(0x1c).writeU32(0x200);
        if (variation === 'dead_health' || variation === 'disabled_health') {
            e.ptr(0x15000c).writePointer(e.ptr(0x360000));
            e.ptr(0x3600f8).writeU8(variation === 'dead_health' ? 1 : 4);
            const after = await e.snapshot();
            assert.equal(after.units[0].nativeDeadPredicate, variation === 'dead_health');
            assert.equal(after.units[0].eligible, false);
            assert.equal(after.units[0].alive, null);
            const deaths = after.events.filter(event => event.kind === 'owned_death');
            assert.equal(deaths.length, variation === 'dead_health' ? 1 : 0);
            if (deaths.length) {
                assert.equal(deaths[0].id, '18');
                assert.equal(deaths[0].incarnation, initial.units[0].incarnation);
                assert.deepEqual(deaths[0].position, after.units[0].position);
            }
            assert.equal((await e.snapshot()).events.filter(event => event.kind === 'owned_death').length, 0);
        }
        if (variation === 'completed_match') e.ptr(0x22000c).writeU32(3);
        if (variation === 'unknown_manager') e.ptr(0x220000).writeU32(1);
        if (variation === 'manual' || variation === 'foreign_command') {
            const command = e.ptr(0x190000), vector = e.ptr(0x1a0000);
            const addressed = variation === 'manual' ? e.actor : e.ptr(0x2a0000);
            if (variation === 'foreign_command') addressed.add(0x774).writeU8(3);
            command.add(4).writeU8(1); command.add(0x10).writePointer(vector);
            command.add(0x14).writePointer(vector.add(4)); vector.writePointer(addressed);
            e.hooks.get(0xaaa1a0).onEnter.call({context: {ecx: command}});
        }
        if (variation === 'direct') e.brain.add(0x214).writeU32(1);
        if (variation === 'reuse') e.hooks.get(0x9dacb0).onEnter([e.actor, e.ptr(0)]);
        if (variation === 'stopped') {
            e.api.stop(); assert.throws(() => e.api.trialstance(options), /unavailable/); passed++; continue;
        }
        if (variation === 'duplicate') assert.equal((await e.trial(options)).status, 'serialized');
        const result = await e.trial(options);
        if (variation === 'foreign_command') {
            const after = await e.snapshot();
            assert.equal(after.ignoredUnownedCommands, 1);
            assert.equal(after.commandRevision, 0);
            assert.equal(after.units[0].enrolled, true);
        }
        if (variation === 'cover_query') {
            assert.equal(result.status, 'queried'); assert.equal(e.submitted.length, 0);
            assert.ok(result.candidates.length > 0);
            for (const candidate of result.candidates) {
                assert.equal(candidate.nativeSourceEntityId, 765); assert.equal(candidate.protection, null);
                assert.equal(candidate.sourceIdentity.incarnation, 1);
                assert.equal(candidate.nativeAssessment.componentsRaw.length, 10);
                assert.equal(candidate.nativeAssessment.scoringEnabled, false);
                assert.equal(candidate.firingAccess, null); assert.equal(candidate.reachability, null);
            }
        } else if (['barricade_build', 'barricade_build_vertical', 'barricade_build_diagonal'].includes(variation)) {
            assert.equal(result.status, 'serialized'); assert.equal(result.completed, false);
            assert.equal(e.submitted.length, 1); assert.equal(e.submitted[0].type, 0x101);
            assert.equal(e.submitted[0].flags, 0x18);
            assert.deepEqual(e.submitted[0].primary, [100, 0, 0]);
            const direction = variation === 'barricade_build_vertical' ? [0, 1] :
                variation === 'barricade_build_diagonal' ? [.6, .8] : [1, 0];
            assert.deepEqual(Array.from(result.buildDirection), direction);
            direction.forEach((v, i) => assert.ok(Math.abs(e.submitted[0].secondary[i] - e.submitted[0].primary[i] - v) < .00002));
            assert.equal(e.submitted[0].secondary[2], 0);
        } else if (variation.startsWith('barricade_held_')) {
            assert.equal(result.status, 'queried'); assert.equal(e.submitted.length, 0);
            assert.equal(result.itemCount, variation === 'barricade_held_shared' ? 2 : 0);
            assert.equal(result.heldItemCount, variation === 'barricade_held_shared' ? 2 : 1);
            assert.equal(result.totalItemCount, variation === 'barricade_held_shared' ? 2 : 1);
        } else if (['grenade_smoke','grenade_fragmentation','grenade_anti_tank'].includes(variation)) {
            assert.equal(result.status,'queried');assert.equal(result.totalItemCount,2);
            assert.equal(result.nativeActorInventoryAllowed,true);assert.equal(result.throwSupported,false);
            assert.equal(result.grenadeKind,options.grenadeKind);assert.equal(e.submitted.length,0);
        } else if (['barricade_query', 'barricade_denied', 'barricade_no_match'].includes(variation)) {
            assert.equal(result.status, 'queried'); assert.equal(e.submitted.length, 0);
            assert.equal(result.nativeActorInventoryAllowed, variation !== 'barricade_denied');
            assert.equal(result.placementValid, null); assert.equal(result.itemCount, variation === 'barricade_no_match' ? 0 : 2);
            assert.equal(result.constructionSupported, false);
        } else if (['weapon_query', 'weapon_empty', 'weapon_unsupported'].includes(variation)) {
            assert.equal(result.status, 'queried'); assert.equal(e.submitted.length, 0);
            assert.equal(result.readyToFire, null);
            assert.equal(result.equipped, variation !== 'weapon_empty');
            if (variation === 'weapon_query') {
                assert.equal(result.ammoCount, 8); assert.equal(result.loadingSerialized, true);
                assert.equal(result.reloadRequestedSerialized, true); assert.equal(result.recoveryUntilTicks, 2000);
                e.reads.clear();
                assert.equal((await e.trial({...options,sequence:2,action:'stance',stance:2})).status,'serialized');
                assert.equal(e.reads.has(0x310000),false,'command preflight avoids unrelated weapon observation');
                assert.equal((await e.snapshot()).units[0].ammunition.ammoCount,8,'scheduled observation retains ammunition');
            } else if (variation === 'weapon_unsupported') assert.equal(result.supportedAmmo, false);
        } else if (['purchase_success','purchase_assault','purchase_anti_tank'].includes(variation)) {
            assert.equal(result.status, 'submitted_unconfirmed'); assert.equal(result.completed, false);
            assert.equal(e.submitted.length, 1); assert.equal(e.submitted[0].purchase, true);
        } else if (variation === 'purchase_query_unavailable') {
            assert.equal(result.status, 'queried'); assert.equal(result.available, false);
            assert.equal(e.submitted.length, 0);
        } else if (['sensor_query', 'sensor_tracked_hidden', 'sensor_known_hidden', 'sensor_known_visible'].includes(variation)) {
            assert.equal(result.status, 'queried'); assert.equal(e.submitted.length, 0);
            if (variation.startsWith('sensor_known_')) assert.equal(result.records[0].identity.id, '18');
            else assert.equal(result.records[0].identity, null);
            assert.equal(result.records[0].visible, variation === 'sensor_known_hidden' ? false : null);
            assert.equal(result.records[0].nativeVisualResult, variation === 'sensor_known_visible');
            assert.equal(result.records[0].nativeVisualLatch, variation === 'sensor_known_visible');
            assert.equal(result.records[0].nativeDeadPredicate, null);
            assert.equal(result.records[0].currentTargetRecord, variation === 'sensor_tracked_hidden');
            assert.equal(result.records[0].recordedPosition[0], 123);
            assert.equal(result.records[0].positionUpdateTicks, 900);
            assert.equal(result.records[0].visualTransitionTicks, 700);
            assert.equal(result.visualUpdateTicks, 800);
            if (variation === 'sensor_known_visible') {
                e.api.capabilities().contacts=true;
                e.reads.clear();
                const snapshot=await e.snapshot(), report=snapshot.perception[0];
                assert(report);assert.equal(report.records.length,0);
                assert.equal(snapshot.perceptionEncoding,'tuple-v1');
                assert(!e.reads.has(0x1c0010),'routine perception does not decode owned sensor positions');
            }
        } else if (variation === 'stance' || variation === 'move' || variation === 'foreign_command') {
            assert.equal(result.status, 'serialized'); assert.equal(e.submitted.length, 1);
            if (variation === 'move') {
                assert.equal(e.submitted[0].type, 0x101);
                assert.equal(e.submitted[0].flags, 0x18);
                assert.deepEqual(e.submitted[0].primary, [600, 0, 0]);
                assert.deepEqual(e.submitted[0].secondary, [600, 0, 0]);
            } else assert.equal(e.submitted[0].stance, 2);
        } else {
            assert.ok(result.error, variation);
            assert.equal(e.submitted.length, variation === 'duplicate' ? 1 : 0, variation);
            if (variation === 'manual') assert.equal(result.observedEvents.filter(x => x.kind === 'player_command').length, 1);
        }
        passed++;
    }
    for (const variation of ['missing', 'same_address_reuse', 'replacement', 'invalid_id', 'unrelated_registration']) {
        const e = environment(), raw = await e.snapshot(); e.ptr(0x370002).writeU8(1);
        const options = {id: '18', incarnation: 1, generation: raw.generation, revision: 0, sequence: 1, action: 'cover_query'};
        const first = await e.trial(options);
        assert.equal(first.candidates[0].sourceIdentity.incarnation, 1);
        if (variation === 'missing') e.ptr(0x490004).writePointer(e.ptr(0x490000));
        if (variation === 'same_address_reuse') e.hooks.get(0x9dc350).onEnter([e.ptr(0x4b0000), e.ptr(0)]);
        if (variation === 'replacement') {
            e.ptr(0x4a0014).writePointer(e.ptr(0x4c0000)); e.ptr(0x4c0054).writeU16(765); e.ptr(0x4c0018).writeU8(1);
        }
        if (variation === 'invalid_id') e.ptr(0x4b0054).writeU16(766);
        if (variation === 'unrelated_registration') e.hooks.get(0x9dc350).onEnter([e.actor, e.ptr(0)]);
        const second = await e.trial({...options, sequence: 2});
        if (variation === 'same_address_reuse') {
            assert.equal(second.observedEvents.filter(x => x.kind === 'cover_source_invalidated').length, 1);
            assert.equal(second.observedEvents[0].destroyed, null);
        }
        if (variation === 'invalid_id') assert.match(second.error, /identity mismatch/);
        else if (variation === 'missing') assert.equal(second.candidates[0].sourceIdentity, null);
        else assert.equal(second.candidates[0].sourceIdentity.incarnation, variation === 'unrelated_registration' ? 1 : 2);
        assert.equal(e.submitted.length, 0); passed++;
    }
    for (const variation of ['owned', 'foreign', 'other_caller', 'removed', 'null_result']) {
        const e = environment(); await e.snapshot();
        const hook = e.hooks.get(0x794120), frame = e.ptr(0x410000), instruction = e.ptr(0x420000);
        const entity = e.ptr(0x440000);
        frame.add(0x10).writePointer(e.actor); frame.sub(4).writePointer(instruction);
        frame.add(0x14).writePointer(e.ptr(0xdeadbeef)); // Original argument has been reused.
        instruction.writePointer(e.ptr('0xe1a1dc'));
        instruction.add(8).writeByteArray(Buffer.from('sandbag3'));
        instruction.add(24).writeU32(8); instruction.add(28).writeU32(15);
        frame.sub(0x10).writeFloat(100); frame.sub(0xc).writeFloat(200); frame.sub(8).writeFloat(3);
        entity.add(0x54).writeU32(765);
        if (variation === 'foreign') e.actor.add(0x774).writeU8(3);
        const invocation = {returnAddress: e.ptr(variation === 'other_caller' ? 1 : '0xa9cc7d'), context: {ebp: frame}};
        hook.onEnter.call(invocation);
        if (variation === 'removed') e.hooks.get(0x9dacb0).onEnter([e.actor, e.ptr(0)]);
        hook.onLeave.call(invocation, variation === 'null_result' ? e.ptr(0) : entity);
        const after = await e.snapshot(), created = after.events.filter(x => x.kind === 'install_entity_created');
        assert.equal(created.length, variation === 'owned' ? 1 : 0, variation);
        if (created.length) {
            assert.equal(created[0].id, '18'); assert.equal(created[0].createdEntityId, 765);
            assert.equal(created[0].requestedEntity, 'sandbag3'); assert.equal(created[0].usableDefense, null);
            assert.deepEqual(Array.from(created[0].preparedPosition), [100, 200, 3]);
        }
        passed++;
    }
    for (const variation of ['owned', 'foreign', 'other_caller', 'removed', 'null_result']) {
        const e = environment(); await e.snapshot();
        const hook = e.hooks.get(0x85cc30);
        if (variation === 'foreign') e.actor.add(0x774).writeU8(3);
        const invocation = {returnAddress: e.ptr(variation === 'other_caller' ? 1 : '0x84de9f')};
        hook.onEnter.call(invocation, [e.actor]);
        if (variation === 'removed') e.hooks.get(0x9dacb0).onEnter([e.actor, e.ptr(0)]);
        hook.onLeave.call(invocation, e.ptr(variation === 'null_result' ? 0 : 0x350000));
        const after = await e.snapshot(), bullets = after.events.filter(x => x.kind === 'bullet_created');
        assert.equal(bullets.length, variation === 'owned' ? 1 : 0, variation);
        if (bullets.length) {
            assert.equal(bullets[0].id, '18'); assert.equal(bullets[0].incarnation, 1);
            assert.equal(bullets[0].simulationTicks, 1000);
        }
        passed++;
    }
    for (const variation of ['foreign_tail', 'owned_overflow']) {
        const e = environment(), head = e.ptr(0x110000);
        e.world.add(0x34).writeU32(1025);
        let previous = e.ptr(0x110100);
        for (let i = 1; i <= 1024; i++) {
            const node = e.ptr(0x2000000 + i * 0x20), actor = e.ptr(0x4000000 + i * 0x1000);
            const brain = actor.add(0x800), id = 100 + i;
            previous.add(8).writePointer(node); node.writePointer(head); node.add(8).writePointer(head);
            node.add(16).writeU16(id); node.add(20).writePointer(actor);
            actor.add(0x776).writeU16(id);
            actor.add(0x774).writeU8(variation === 'foreign_tail' && i === 1024 ? 3 : 2);
            actor.add(0x78c).writePointer(brain); brain.writePointer(e.ptr('0xdfbed0'));
            brain.add(0x20).writePointer(actor); actor.add(0x798).writePointer(e.ptr(0x140000));
            actor.add(0x788).writePointer(e.ptr(0x170000)); actor.add(0x32c).writePointer(e.ptr(0x150000));
            actor.add(0x320).writePointer(e.ptr(0x160000)); actor.add(0x780).writeU32(0x100);
            previous = node;
        }
        const snapshot = await e.snapshot();
        if (variation === 'foreign_tail') assert.equal(snapshot.units.length, 1024);
        else assert.match(snapshot.error, /Infantry limit/);
        passed++;
    }
    {
        const e = environment();
        e.ptr(0x15000c).writePointer(e.ptr(0x360000));
        e.ptr(0x3600f8).writeU8(1);
        const initial = await e.snapshot();
        assert.equal(initial.units[0].nativeDeadPredicate, true);
        assert.equal(initial.events.filter(event => event.kind === 'owned_death').length, 0);
        // Never count an already observed corpse again within its incarnation,
        // even if the native predicate temporarily clears.
        e.ptr(0x3600f8).writeU8(0); await e.snapshot();
        e.ptr(0x3600f8).writeU8(1);
        assert.equal((await e.snapshot()).events.filter(event => event.kind === 'owned_death').length, 0);
        passed++;
    }
    {
        const e = environment();
        e.actor.add(0x1c).writeU32(0x200);
        await e.snapshot();
        e.ptr(0x15000c).writePointer(e.ptr(0x360000));
        e.ptr(0x3600f8).writeU8(1);
        assert.equal((await e.snapshot()).events.filter(event => event.kind === 'owned_death').length, 0);
        passed++;
    }
    for (const duplicate of [false, true]) {
        const e = environment();
        e.ptr(0x220068).writePointer(e.ptr(0x240000));
        e.ptr(0x22006c).writePointer(e.ptr(0x240008));
        for (let i = 0; i < 2; i++) {
            const player = e.ptr(0x230000 + i * 0x100);
            e.ptr(0x240000 + i * 4).writePointer(player);
            player.add(4).writeU8(duplicate ? 2 : 2 + i * 2);
            player.add(0x4c).writeU8(97 + i);
            player.add(0x5c).writeU32(1); player.add(0x60).writeU32(15);
        }
        const snapshot = await e.snapshot();
        if (duplicate) assert.match(snapshot.error, /Ambiguous match player/);
        else {
            assert.equal(snapshot.team, 'a');
            assert.equal(snapshot.playerTeams['2'], 'a');
            assert.equal(snapshot.playerTeams['4'], 'b');
            assert.equal(snapshot.playerTeams['3'], undefined);
        }
        passed++;
    }
    {
        const e = environment(), initial = await e.snapshot();
        assert.equal(initial.playing, true); assert.equal(initial.paused, false);
        assert.equal(initial.capabilities.simulationClock, true);
        assert.throws(() => e.api.submit({action: 'move'}), /validation gates/);
        assert.equal(e.submitted.length, 0);
        e.ptr('0xfbaffc').writeU8(1);
        assert.equal((await e.snapshot()).paused, true);
        passed++;
    }
    {
        const e = environment(), initial = await e.snapshot();
        // Fixture-only capability promotion; RPC callers receive serialized
        // values and cannot mutate the production bridge's capability object.
        const caps = e.api.capabilities();
        for (const key of ['identityLifecycle', 'simulationClock', 'death', 'commandAuthority', 'synchronization', 'stance']) caps[key] = true;
        const options = {action: 'stance', stance: 1, id: '18', incarnation: 1,
            generation: initial.generation, revision: 0, unitRevision: 0,
            sequence: 1, requireEnrolled: true, submitBeforeTicks: 1000};
        const expired = e.api.submit(options); e.pump();
        assert.equal((await expired).rejected, true); assert.equal(e.submitted.length, 0);
        const accepted = e.api.submit({...options, sequence: 2, submitBeforeTicks: 1100}); e.pump();
        assert.equal((await accepted).status, 'serialized'); assert.equal(e.submitted.length, 1);
        passed++;
    }
    for (const variation of ['valid', 'stale_generation', 'wrong_source', 'slot_changed', 'missing', 'reused']) {
        const e = environment(), initial = await e.snapshot();
        e.ptr(0x370002).writeU8(1);
        const cover = e.ptr(0x480000);
        e.ptr('0xfe7ed0').writePointer(cover); cover.writePointer(e.ptr('0xe1a620'));
        cover.add(0x2fc).writeU8(5);
        const identity = {id: '18', incarnation: 1, generation: initial.generation, revision: 0};
        const query = await e.trial({...identity, sequence: 1, action: 'cover_query'});
        const source = {...query.candidates[0].sourceIdentity}, destination = [0, 0, 0];
        if (variation === 'stale_generation') source.generation = 'old match';
        if (variation === 'wrong_source') source.entityId++;
        if (variation === 'slot_changed') destination[0] = 10;
        if (variation === 'missing') e.ptr(0x490004).writePointer(e.ptr(0x490000));
        if (variation === 'reused') e.hooks.get(0x9dc350).onEnter([e.ptr(0x4b0000), e.ptr(0)]);
        const reply = await e.trial({...identity, sequence: 2, action: 'cover', destination, coverSource: source});
        if (variation === 'valid') {
            assert.equal(reply.status, 'serialized');
            assert.equal(e.submitted[0].flags, 0x38);
        } else assert.equal(reply.rejected, true, variation);
        assert.equal(e.submitted.length, variation === 'valid' ? 1 : 0);
        passed++;
    }
    for (const hasEvents of [false, true]) {
        const e = environment();
        await e.snapshot();
        if (hasEvents) e.hooks.get(0x8e8c80).onEnter.call({context: {ecx: e.brain}}, [e.ptr(0)]);
        e.advance(5001);
        const snapshot = await e.snapshot();
        if (hasEvents) {
            assert.match(snapshot.fault, /continuity lost/);
            assert.throws(() => e.api.trialstance({}), /Bridge unavailable/);
        } else assert.equal(snapshot.fault, null);
        assert.equal(e.submitted.length, 0);
        passed++;
    }
    for (const variation of ['enemy', 'ally', 'neutral', 'unknown_value', 'missing', 'malformed', 'outside',
                             'perceived_local', 'actual_owner_mode', 'inactive_subject',
                             'vehicle_visible','vehicle_hidden','vehicle_owned']) {
        const e = environment(), initial = await e.snapshot(), head = e.ptr(0x110000);
        const node = e.ptr(0x510000), actor = e.ptr(0x520000), brain = e.ptr(0x530000);
        e.world.add(0x34).writeU32(2); e.ptr(0x110108).writePointer(node);
        node.writePointer(head); node.add(8).writePointer(head);
        node.add(16).writeU16(19); node.add(20).writePointer(actor);
        const vehicle=variation.startsWith('vehicle_');
        actor.add(0x776).writeU16(19); actor.add(0x774).writeU8(variation === 'outside' ? 17 : variation==='vehicle_owned' ? 2 : 4);
        actor.add(0x78c).writePointer(brain); brain.writePointer(e.ptr('0xdfbed0'));
        if(vehicle) {brain.writePointer(e.ptr('0xe00344'));actor.add(0x44).writeFloat(NaN);}
        brain.add(0x20).writePointer(actor); actor.add(0x798).writePointer(e.ptr(0x140000));
        actor.add(0x788).writePointer(e.ptr(0x170000)); actor.add(0x32c).writePointer(e.ptr(0x150000));
        actor.add(0x320).writePointer(e.ptr(0x160000)); actor.add(0x780).writeU32(0x100);
        const sensor = e.ptr(0x570000), record = e.ptr(0x580000), vector = e.ptr(0x590000);
        e.actor.add(0x790).writePointer(sensor); sensor.writePointer(e.ptr('0xdf7c04'));
        sensor.add(0x1c).writePointer(e.actor); sensor.add(0x28).writePointer(vector);
        sensor.add(0x2c).writePointer(vector.add(4)); vector.writePointer(record);
        record.add(8).writePointer(actor); record.writeU32(0x30000000); record.add(4).writeU32(0x40);
        if(vehicle) {sensor.add(0xb0).writeU32(900);record.add(0x44).writeU32(900);}
        if(variation==='vehicle_hidden') {record.writeU32(0);record.add(4).writeU32(0);}
        if (['perceived_local', 'actual_owner_mode'].includes(variation)) actor.add(0x778).writeU8(2);
        if (variation === 'actual_owner_mode') record.add(4).writeU32(0x60);
        if (variation === 'inactive_subject') actor.add(0x780).writeU32(0);
        const value = vehicle || ['enemy', 'perceived_local', 'actual_owner_mode', 'inactive_subject'].includes(variation) ? 1 :
            variation === 'ally' ? 2 : variation === 'unknown_value' ? 9 : 0;
        if (variation !== 'missing') {
            e.ptr('0xfe37e0').writePointer(e.ptr(0x5a0000));
            e.ptr('0xfe37e4').writePointer(e.ptr(0x5a0064));
            e.ptr('0xfe37e8').writeU32(variation === 'malformed' ? 0 : 5);
            e.ptr(0x5a0058).writeU32(value); // row subject 4, column observer 2
            e.ptr(0x5a0038).writeU32(2); // reverse entry deliberately differs
        }
        e.reads.clear();
        const reply = await e.trial({id: '18', incarnation: 1, generation: initial.generation,
            revision: 0, sequence: 1, action: 'sensor_query'});
        if (variation === 'malformed') assert.match(reply.error, /Invalid native relation table/);
        else {
            const contact = reply.records[0];
            assert.equal(contact.nativeOwnerRelation, variation==='vehicle_owned' ? 2 : ['missing', 'outside'].includes(variation) ? null : value);
            assert.equal(contact.enemy, ['enemy', 'actual_owner_mode','vehicle_visible','vehicle_hidden'].includes(variation) ? true :
                ['ally', 'perceived_local','vehicle_owned'].includes(variation) ? false : null);
            if (variation === 'perceived_local') assert.equal(contact.nativeSensorRelation, 2);
            if (variation === 'inactive_subject') assert.equal(contact.nativeSensorRelation, null);
            assert.equal(contact.visible, vehicle ? variation!=='vehicle_hidden' : null);
            assert.equal(contact.identity.kind,vehicle?'vehicle':'infantry');
            e.api.capabilities().contacts=true;
            const snapshot=await e.snapshot(),report=snapshot.perception[0];
            const fields=['identity','visible','enemy','nativeDeadPredicate','nativeOwnerRelation',
                'visualObservedPosition','visualObservedAtTicks','positionUpdateTicks'];
            assert.equal(report.records.length,variation==='vehicle_owned'?0:1);
            if(report.records.length)fields.forEach((key,i)=>assert.deepEqual(report.records[0][i],contact[key]));
            if(vehicle) {
                assert.equal(snapshot.units.length,1,'vehicles never become controlled infantry');
                assert(!e.reads.has(actor.add(0x44).value),'vehicle world transform is never read');
                e.ptr('0xfe7eb0').writePointer(e.ptr(0x5c0000));e.ptr(0x5c0000).writePointer(e.ptr('0xe1ad00'));
                e.ptr(0x5c02fc).writeU8(30);
                const query=await e.trial({id:'18',incarnation:1,generation:initial.generation,
                    revision:0,sequence:2,action:'attack_query',targetId:'19'});
                assert.equal(query.targets.length,0,'no unsupported infantry attack on a vehicle');
                if(variation==='vehicle_visible') {
                    actor.add(0x54).writeU16(1234);actor.add(0x18).writeU8(2);
                    const wr=e.ptr(0x610000),weapon=e.ptr(0x611000),ammo=e.ptr(0x612000),definition=e.ptr(0x613000),item=e.ptr(0x614000),slots=e.ptr(0x615000);
                    e.actor.add(0x794).writePointer(wr);wr.writePointer(e.ptr('0xdf50d8'));wr.add(0x3c).writePointer(e.actor);
                    wr.add(0x30).writeS32(-1);wr.add(0x20).writePointer(slots);wr.add(0x24).writePointer(slots.add(4));slots.writePointer(weapon);
                    weapon.writePointer(e.ptr('0xdf51f0'));weapon.add(0x54).writePointer(e.actor);weapon.add(0x58).writePointer(definition);
                    weapon.add(0x64).writePointer(ammo);weapon.add(0xdc).writePointer(item);ammo.writePointer(e.ptr('0xdf525c'));ammo.add(4).writePointer(weapon);
                    item.writePointer(e.ptr('0xdf31b8'));item.add(0x2c).writeU32(1);definition.writePointer(e.ptr('0xdf5fc0'));
                    definition.add(0x10).writeByteArray(Buffer.from('bazooka'));definition.add(0x20).writeU32(7);definition.add(0x24).writeU32(15);
                    const options={id:'18',incarnation:1,generation:initial.generation,revision:0,sequence:3,action:'attack_query',targetId:'19'};
                    const ready=await e.trial(options);assert.equal(ready.targets.length,1);
                    const target={...ready.targets[0].identity,generation:initial.generation,entityId:1234};
                    item.add(0x2c).writeU32(0);
                    assert.equal((await e.trial({...options,sequence:4,action:'attack',target})).rejected,true);
                    item.add(0x2c).writeU32(1);ammo.add(0x18).writeU16(0x20);
                    assert.equal((await e.trial({...options,sequence:5,action:'attack',target})).rejected,true);
                    ammo.add(0x18).writeU16(0);definition.add(0x10).writeByteArray(Buffer.from('garand '));
                    assert.equal((await e.trial({...options,sequence:6,action:'attack',target})).rejected,true);
                    definition.add(0x10).writeByteArray(Buffer.from('bazooka'));
                    assert.equal((await e.trial({...options,sequence:7,action:'attack',target})).status,'serialized');
                    definition.add(0x10).writeByteArray(Buffer.from('garand_grenade'));
                    definition.add(0x20).writeU32(14);
                    const projectile=e.ptr(0x616000),name=e.ptr(0x617000);
                    item.add(0x28).writePointer(projectile);projectile.writePointer(e.ptr('0xdf61d0'));
                    name.writeByteArray(Buffer.from('garand_heat_ammo'));projectile.add(0x10).writePointer(name);
                    projectile.add(0x20).writeU32(16);projectile.add(0x24).writeU32(16);
                    assert.equal((await e.trial({...options,sequence:8})).targets.length,1);
                    assert.equal((await e.trial({...options,sequence:9,action:'attack',target})).status,'serialized');
                    name.writeByteArray(Buffer.from('em_mk3_ammo'));projectile.add(0x20).writeU32(11);
                    assert.equal((await e.trial({...options,sequence:10,action:'attack',target})).rejected,true,'fragmentation is not HEAT');
                    name.writeByteArray(Buffer.from('garand_heat_ammo'));projectile.add(0x20).writeU32(16);
                    projectile.writePointer(e.ptr(0));
                    assert.equal((await e.trial({...options,sequence:11,action:'attack',target})).rejected,true,'unknown filling type is not HEAT');
                    projectile.writePointer(e.ptr('0xdf61d0'));ammo.add(0x18).writeU16(0x20);
                    assert.equal((await e.trial({...options,sequence:12,action:'attack',target})).rejected,true,'do not interrupt HEAT reload');
                    brain.writePointer(e.ptr('0xdfbed0'));
                    const changed=(await e.snapshot()).perception[0].records[0][0];
                    assert.equal(changed.kind,'infantry');assert.equal(changed.incarnation,2);
                }
            }
        }
        assert.equal(e.submitted.length, variation==='vehicle_visible'?2:0);
        passed++;
    }
    for (const variation of ['fresh', 'future', 'stale', 'at_limit', 'position_refresh', 'mixed', 'no_position', 'no_pass', 'hidden_refresh']) {
        const e = environment(), initial = await e.snapshot();
        const sensor = e.ptr(0x570000), record = e.ptr(0x580000), vector = e.ptr(0x590000);
        e.actor.add(0x790).writePointer(sensor); sensor.writePointer(e.ptr('0xdf7c04'));
        sensor.add(0x1c).writePointer(e.actor); sensor.add(0x28).writePointer(vector);
        sensor.add(0x2c).writePointer(vector.add(4)); vector.writePointer(record);
        record.add(8).writePointer(e.actor); record.writeU32(0x30000000); record.add(4).writeU32(0x40);
        record.add(0x10).writeFloat(123);
        sensor.add(0xb0).writeU32(800); record.add(0x44).writeU32(800);
        if (variation === 'future') { sensor.add(0xb0).writeU32(1100); record.add(0x44).writeU32(1100); }
        if (variation === 'stale') e.ptr('0xfbb000').writeU32(2801);
        if (variation === 'at_limit') e.ptr('0xfbb000').writeU32(2800);
        if (variation === 'position_refresh') record.add(0x44).writeU32(900);
        if (variation === 'mixed') record.add(4).writeU32(0);
        if (variation === 'no_position') record.writeU32(0x20000000);
        if (variation === 'no_pass') { sensor.add(0xb0).writeU32(0); record.add(0x44).writeU32(0); }
        if (variation === 'hidden_refresh') {
            record.writeU32(0x10000000); record.add(4).writeU32(0); record.add(0x44).writeU32(900);
        }
        const reply = await e.trial({id: '18', incarnation: 1, generation: initial.generation,
            revision: 0, sequence: 1, action: 'sensor_query'});
        const contact = reply.records[0], visible = ['fresh', 'at_limit'].includes(variation);
        assert.equal(contact.visible, visible ? true : variation === 'hidden_refresh' ? false : null, variation);
        assert.equal(contact.visualObservedAtTicks, visible ? 800 : null);
        assert.equal(contact.nativeDeadPredicate, visible ? false : null);
        if (visible) assert.equal(contact.visualObservedPosition[0], 123);
        else assert.equal(contact.visualObservedPosition, null);
        assert.equal(e.submitted.length, 0);
        passed++;
    }
    for (const dense of [false, true]) {
        const e = environment(), brains = [e.brain], head = e.ptr(0x110000);
        const populate = sensor => {
            if (!dense) return;
            const vector = e.ptr(0x7000000), record = e.ptr(0x7100000);
            for (let n = 0; n < 256; n++) vector.add(n * 4).writePointer(record);
            sensor.add(0x28).writePointer(vector); sensor.add(0x2c).writePointer(vector.add(1024));
        };
        const sensor = e.ptr(0x570000);
        e.actor.add(0x790).writePointer(sensor); sensor.writePointer(e.ptr('0xdf7c04'));
        sensor.add(0x1c).writePointer(e.actor);
        populate(sensor);
        let previous = e.ptr(0x110100);
        e.world.add(0x34).writeU32(80);
        for (let i = 1; i < 80; i++) {
            const node = e.ptr(0x2000000 + i * 0x20), actor = e.ptr(0x4000000 + i * 0x1000);
            const brain = actor.add(0x800), sensor = actor.add(0xc00), id = 100 + i;
            previous.add(8).writePointer(node); node.writePointer(head); node.add(8).writePointer(head);
            node.add(16).writeU16(id); node.add(20).writePointer(actor);
            actor.add(0x776).writeU16(id); actor.add(0x774).writeU8(2);
            actor.add(0x78c).writePointer(brain); brain.writePointer(e.ptr('0xdfbed0'));
            brain.add(0x20).writePointer(actor); actor.add(0x798).writePointer(e.ptr(0x140000));
            actor.add(0x788).writePointer(e.ptr(0x170000)); actor.add(0x32c).writePointer(e.ptr(0x150000));
            actor.add(0x320).writePointer(e.ptr(0x160000)); actor.add(0x780).writeU32(0x100);
            actor.add(0x790).writePointer(sensor); sensor.writePointer(e.ptr('0xdf7c04'));
            sensor.add(0x1c).writePointer(actor); populate(sensor); brains.push(brain); previous = node;
        }
        assert.equal((await e.snapshot()).perception.length, 0);
        e.api.capabilities().contacts = true; // fixture only
        const visited = new Set();
        for (const expected of [10, 20, 30, 40, 50, 60, 70, 80]) {
            const snapshot = await e.snapshot();
            assert.equal(snapshot.perception.length, dense ? Math.min(expected, 16) : expected);
            snapshot.perception.forEach(report => visited.add(report.observerIdentity.id));
        }
        assert.equal(visited.size, 80);
        brains.forEach(brain => brain.add(0x210).writeU32(0x1000));
        assert.equal((await e.snapshot()).perception.length, 0);
        assert.equal(e.submitted.length, 0);
        passed++;
    }
    for (const variation of ['ready', 'ready_alt', 'preparing', 'empty', 'recovery', 'ammo_blocked', 'reload_boundary',
                             'reload_partial', 'context_off', 'placement_missing', 'unsupported', 'owner',
                             'loading', 'unloading', 'pending_overflow']) {
        const e = environment(), initial = await e.snapshot();
        const wr = e.ptr(0x600000), weapon = e.ptr(0x601000), ammo = e.ptr(0x602000);
        const item = e.ptr(0x603000), definition = e.ptr(0x604000), placement = e.ptr(0x605000);
        const context = e.ptr(0x606000), shooter = e.ptr(0x607000), vector = e.ptr(0x608000);
        e.actor.add(0x794).writePointer(wr); wr.writePointer(e.ptr('0xdf50d8'));
        wr.add(0x3c).writePointer(e.actor); wr.add(0x30).writeS32(-1);
        wr.add(0x20).writePointer(vector); wr.add(0x24).writePointer(vector.add(4)); vector.writePointer(weapon);
        weapon.writePointer(e.ptr('0xdf51f0')); weapon.add(0x54).writePointer(e.actor);
        for (const [offset, component, vtable] of [[0x58, definition, '0xdf5fc0'], [0x60, placement, '0xdf59f4'],
                [0x64, ammo, '0xdf525c'], [0x68, shooter, '0xdf57b4'], [0x6c, context, '0xdf54a4'],
                [0xdc, item, '0xdf31b8']]) {
            weapon.add(offset).writePointer(component); component.writePointer(e.ptr(vtable));
        }
        ammo.add(4).writePointer(weapon); shooter.add(4).writePointer(weapon);
        placement.add(8).writePointer(variation === 'owner' ? e.ptr(0) : weapon);
        context.add(0x1a8).writePointer(weapon); context.add(0x6a0).writeU8(variation === 'context_off' ? 0 : 1);
        placement.add(0x10).writePointer(item); placement.add(0x18).writePointer(variation === 'placement_missing' ? e.ptr(0) : item);
        definition.add(0x314).writeU32(8);
        definition.add(0x10).writeByteArray(Buffer.from('thompson'));
        definition.add(0x20).writeU32(8); definition.add(0x24).writeU32(15);
        placement.add(0xc).writeU32(variation === 'preparing' ? 5 : variation === 'ready_alt' ? 4 : 3);
        item.add(0x2c).writeU32(variation === 'empty' ? 0 : variation === 'reload_partial' ? 7 : 8);
        ammo.add(0x14).writeU32(variation === 'recovery' ? 2000 : 0);
        ammo.add(0x18).writeU16(variation === 'ammo_blocked' ? 0x24 : variation.startsWith('reload_') ? 0x10 : 0);
        if (['loading', 'pending_overflow'].includes(variation)) {
            ammo.add(0x18).writeU16(0x30); ammo.add(0xc).writeU32(variation === 'loading' ? 8 : 10001);
        }
        if (variation === 'unloading') ammo.add(0x18).writeU16(4);
        if (variation === 'unsupported') context.writePointer(e.ptr(1));
        if (['ready', 'empty', 'loading', 'unsupported'].includes(variation)) {
            e.api.capabilities().weaponReadiness = false;
            const ammunition = (await e.snapshot()).units[0].ammunition;
            assert.equal(ammunition.simulationTicks, 1000);
            assert.equal(ammunition.weaponModel, 'thompson');
            assert.equal(ammunition.ammoCount, variation === 'empty' ? 0 : 8);
            assert.equal(ammunition.nativeLoading, variation === 'loading');
            assert.equal(ammunition.nativeFirePredicate, undefined);
            assert.equal(ammunition.fireState, undefined);
            e.api.capabilities().weaponReadiness = true;
            const observed = (await e.snapshot()).units[0].ammunition.fireState;
            assert.equal(observed && observed.readinessCandidate, variation === 'unsupported' ? null : variation === 'ready');
            e.api.capabilities().weaponReadiness = false;
        }
        const reply = await e.trial({id: '18', incarnation: 1, generation: initial.generation,
            revision: initial.commandRevision, sequence: 1, action: 'weapon_query'});
        if (variation === 'owner') assert.match(reply.error, /Fire component owner mismatch/);
        else if (variation === 'pending_overflow') assert.match(reply.error, /pending ammunition/);
        else {
            assert.equal(reply.status, 'queried', variation);
            assert.equal(reply.weaponModel, 'thompson');
            assert.equal(reply.nativeFirePredicate, variation === 'unsupported' ? null :
                ['ready', 'ready_alt', 'preparing', 'reload_partial'].includes(variation), variation);
            assert.equal(reply.fireState && reply.fireState.readinessCandidate, variation === 'unsupported' ? null :
                ['ready', 'ready_alt', 'reload_partial'].includes(variation), variation);
            assert.equal(reply.readyToFire, e.api.capabilities().weaponReadiness && reply.fireState &&
                reply.fireState.readinessCandidate ? true : null);
            assert.equal(reply.nativeLoading, ['loading', 'ammo_blocked'].includes(variation));
            assert.equal(reply.nativeUnloading, ['unloading', 'ammo_blocked'].includes(variation));
            assert.equal(reply.pendingRounds, variation === 'loading' ? 8 : variation === 'ammo_blocked' ? 0 : null);
        }
        if (variation === 'ready' && e.hooks.has(0x84d0a0)) {
            for (const mode of ['allowed', 'refused', 'mismatch']) {
                ammo.add(0x18).writeU16(mode === 'allowed' ? 0 : 0x20);
                // Distinct state ensures each synthetic sample passes throttling.
                placement.add(4).writeU32(mode === 'allowed' ? 1 : mode === 'refused' ? 2 : 3);
                const call = {context: {ecx: shooter}};
                e.hooks.get(0x84d0a0).onEnter.call(call);
                e.hooks.get(0x84d0a0).onLeave.call(call, e.ptr(mode === 'refused' ? 0 : 1));
                const events = (await e.snapshot()).events.filter(x => x.kind === 'friendly_fire_predicate');
                assert.equal(events.length, 1);
                assert.equal(events[0].matchesMirror, mode !== 'mismatch');
                passed++;
            }
        }
        assert.equal(e.submitted.length, 0); passed++;
    }
    for (const variation of ['shared', 'different_radius', 'different_point', 'negative']) {
        const e = environment(), vector = e.ptr(0x700000), point = e.ptr(0x701000), engine = e.ptr(0x702000);
        e.ptr('0xf396fc').writePointer(vector); e.ptr('0xf39700').writePointer(vector.add(4));
        vector.writePointer(point); point.writePointer(e.ptr('0xdf1c64'));
        point.add(0x10).writePointer(e.actor); point.add(0x79c).writePointer(engine);
        engine.writePointer(e.ptr('0xe3093c')); engine.add(4).writePointer(point);
        engine.add(0x12c).writeS32(variation === 'negative' ? -1 : 360000);
        engine.add(0x138).writeS32(variation === 'different_radius' ? 160000 : 360000);
        engine.add(0x130).writePointer(point);
        engine.add(0x13c).writePointer(variation === 'different_point' ? e.ptr(0) : point);
        const reply = await e.snapshot();
        if (variation === 'negative') assert.match(reply.error, /Invalid capture radius/);
        else assert.equal(reply.objectives[0].captureRadius, variation === 'shared' ? 600 : null);
        assert.equal(e.submitted.length, 0); passed++;
    }
    for (const destination of [[300, 0, 0], [601, 0, 0], [NaN, 0, 0]]) {
        const e = environment(), initial = await e.snapshot();
        const reply = await e.trial({id: '18', incarnation: 1, generation: initial.generation,
            revision: initial.commandRevision, sequence: 1, action: 'cover_query', destination});
        if (destination[0] === 300) {
            assert.equal(reply.status, 'queried'); assert.deepEqual(Array.from(reply.center), destination);
            assert.ok(reply.candidates.length <= 5);
            reply.candidates.forEach(c => {
                assert.equal(c.protection, null); assert.equal(c.firingAccess, null);
                assert.equal(c.reachability, null);
            });
        } else assert.equal(reply.rejected, true);
        assert.equal(e.submitted.length, 0); passed++;
    }
    for (const variation of ['visible', 'hidden', 'stale', 'allied', 'dead', 'invalid_entity', 'action_type']) {
        const e = environment(), initial = await e.snapshot(), head = e.ptr(0x110000);
        const node = e.ptr(0x710000), target = e.ptr(0x711000), brain = e.ptr(0x712000);
        e.world.add(0x34).writeU32(2); e.ptr(0x110100).add(8).writePointer(node);
        node.writePointer(head); node.add(8).writePointer(head); node.add(16).writeU16(19); node.add(20).writePointer(target);
        target.add(0x776).writeU16(19); target.add(0x774).writeU8(4); target.add(0x18).writeU8(6);
        target.add(0x54).writeU16(variation === 'invalid_entity' ? 0xffff : 1234);
        target.add(0x44).writeFloat(99999); target.add(0x780).writeU32(0x100);
        target.add(0x78c).writePointer(brain); brain.writePointer(e.ptr('0xdfbed0')); brain.add(0x20).writePointer(target);
        target.add(0x798).writePointer(e.ptr(0x140000)); target.add(0x788).writePointer(e.ptr(0x170000));
        target.add(0x320).writePointer(e.ptr(0x160000)); target.add(0x32c).writePointer(e.ptr(0x713000));
        e.ptr(0x71300c).writePointer(e.ptr(0x714000)); e.ptr(0x7140f8).writeU8(variation === 'dead' ? 1 : 0);
        const sensor = e.ptr(0x715000), record = e.ptr(0x716000), vector = e.ptr(0x717000), matrix = e.ptr(0x718000);
        e.actor.add(0x790).writePointer(sensor); sensor.writePointer(e.ptr('0xdf7c04')); sensor.add(0x1c).writePointer(e.actor);
        sensor.add(0x28).writePointer(vector); sensor.add(0x2c).writePointer(vector.add(4)); vector.writePointer(record);
        sensor.add(0xb0).writeU32(800); record.add(8).writePointer(target); record.add(0x44).writeU32(800);
        record.writeU32(variation === 'hidden' ? 0x10000000 : 0x30000000);
        record.add(4).writeU32(variation === 'hidden' ? 0x20 : 0x60); record.add(0x10).writeFloat(123);
        e.ptr('0xfe37e0').writePointer(matrix); e.ptr('0xfe37e4').writePointer(matrix.add(100));
        e.ptr('0xfe37e8').writeU32(5); matrix.add(22 * 4).writeU32(variation === 'allied' ? 2 : 1);
        const attack = e.ptr(0x719000); e.ptr('0xfe7eb0').writePointer(attack);
        attack.writePointer(e.ptr('0xe1ad00')); attack.add(0x2fc).writeU8(variation === 'action_type' ? 4 : 30);
        if (variation === 'stale') e.ptr('0xfbb000').writeU32(2801);
        const reply = await e.trial({id: '18', incarnation: 1, generation: initial.generation,
            revision: 0, sequence: 1, action: 'attack_query'});
        if (variation === 'action_type') assert.match(reply.error, /Unsupported native attack/);
        else {
            assert.equal(reply.status, 'queried', variation);
            assert.equal(reply.targets.length, variation === 'visible' ? 1 : 0, variation);
            if (reply.targets.length) {
                assert.equal(reply.targets[0].identity.id, '19'); assert.equal(reply.targets[0].entityId, 1234);
                assert.equal(reply.targets[0].observedPosition[0], 123);
            }
        }
        assert.equal(e.submitted.length, 0);
        if (variation !== 'action_type') {
            const options = {id: '18', incarnation: 1, generation: initial.generation, revision: 0,
                sequence: 2, action: 'attack', requireEnrolled: true, unitRevision: 0,
                submitBeforeTicks: 1500,
                target: {generation: initial.generation, id: '19', incarnation: 1, owner: '4', entityId: 1234}};
            let attackReply;
            if (variation === 'visible') {
                assert.throws(() => e.api.submit(options), /validation gates/);
                Object.assign(e.api.capabilities(), {identityLifecycle: true, simulationClock: true,
                    death: true, commandAuthority: true, synchronization: true, attack: true});
                assert.throws(() => e.api.submit(options), /incomplete native submission/);
                e.api.capabilities().contacts = true;
                const pending = e.api.submit(options); e.pump(); attackReply = await pending;
            } else attackReply = await e.trial(options);
            if (variation === 'visible') {
                assert.equal(attackReply.status, 'serialized'); assert.equal(attackReply.completed, false);
                const packet = e.submitted[0];
                assert.equal(packet.type, 0x101); assert.equal(packet.flags, 0x18); assert.equal(packet.targetType, 2);
                assert.equal(packet.entity, target.toString()); assert.equal(packet.primary[0], 123);
                assert.deepEqual(packet.primary, packet.secondary);
                assert.equal(packet.targetNameLength, 0); assert.equal(packet.targetNameCapacity, 15);
                let sequence = 3;
                for (const change of [{generation: 'old'}, {incarnation: 2}, {owner: '2'}, {entityId: 999}]) {
                    const rejected = await e.trial({...options, sequence: sequence++, target: {...options.target, ...change}});
                    assert.equal(rejected.rejected, true);
                }
                e.ptr(0x7140f8).writeU8(1);
                assert.equal((await e.trial({...options, sequence})).rejected, true);
                assert.equal(e.submitted.length, 1);
            } else {
                assert.equal(attackReply.rejected, true, variation); assert.equal(e.submitted.length, 0);
            }
        }
        passed++;
    }
    for (const variation of ['resume', 'wrong_caller', 'wrong_context', 'timeout']) {
        const e = environment(), initial = await e.snapshot();
        const options = {id: '18', incarnation: 1, generation: initial.generation,
            revision: 0, sequence: 1, action: 'stance', stance: 2};
        const pending = e.api.trialstance(options);
        e.ptr('0xfbaffc').writeU32(256); // Native gate uses the whole DWORD.
        if (variation === 'wrong_caller' || variation === 'wrong_context') {
            let resolved = false; pending.then(() => { resolved = true; });
            e.hooks.get(0x715b60).onEnter.call({returnAddress: e.ptr(variation === 'wrong_caller' ? 0 : 0x665556),
                context: {ecx: e.ptr(variation === 'wrong_context' ? 0 : 0xfbafdc)}});
            await Promise.resolve(); assert.equal(resolved, false);
        }
        if (variation === 'timeout') e.advance(2001);
        e.pump();
        const result = await pending;
        if (variation === 'timeout') assert.match(result.error, /timeout/);
        else { assert.equal(result.rejected, true); assert.match(result.error, /paused/); }
        const paused = await e.snapshot();
        assert.equal(paused.paused, true); assert.equal(paused.simulationTicks, initial.simulationTicks);
        assert.equal(paused.generation, initial.generation);
        e.ptr('0xfbaffc').writeU32(0); e.pump();
        assert.equal(e.submitted.length, 0); // Consumed requests never replay after resume.
        assert.equal((await e.snapshot()).paused, false);
        assert.equal((await e.trial({...options, sequence: 2})).status, 'serialized');
        assert.equal(e.submitted.length, 1);
        passed++;
    }
    for (const variation of ['transfer_back', 'same_owner', 'untracked']) {
        const e = environment(), initial = await e.snapshot();
        const options = {id: '18', incarnation: initial.units[0].incarnation, generation: initial.generation,
            revision: 0, sequence: 1, action: 'stance', stance: 2};
        const pending = e.api.trialstance(options);
        const actor = variation === 'untracked' ? e.ptr(0x720000) : e.actor;
        actor.add(0x776).writeU16(18); actor.add(0x774).writeU8(2);
        const target = variation === 'same_owner' ? 2 : 4;
        e.hooks.get(0x830f90).onEnter.call({context: {ecx: actor}}, [e.ptr(target)]);
        actor.add(0x774).writeU8(target);
        if (variation === 'transfer_back') {
            e.hooks.get(0x830f90).onEnter.call({context: {ecx: actor}}, [e.ptr(2)]);
            actor.add(0x774).writeU8(2);
        }
        e.pump();
        const reply = await pending, after = await e.snapshot();
        if (variation === 'transfer_back') {
            assert.equal(reply.rejected, true); assert.equal(e.submitted.length, 0);
            assert.ok(after.units[0].incarnation > initial.units[0].incarnation);
            assert.equal(reply.observedEvents.filter(event => event.kind === 'ownership_change').length, 1);
        } else {
            assert.equal(reply.status, 'serialized'); assert.equal(e.submitted.length, 1);
            assert.equal(after.units[0].incarnation, initial.units[0].incarnation);
        }
        passed++;
    }
    if (environment().hooks.has(0x845050)) {
        for (const variation of ['owned', 'enemy', 'reused']) {
            const e = environment(); await e.snapshot();
            const weapon = e.ptr(0x730000), ammo = e.ptr(0x731000), item = e.ptr(0x732000), definition = e.ptr(0x733000);
            weapon.writePointer(e.ptr('0xdf51f0')); weapon.add(0x54).writePointer(e.actor);
            weapon.add(0x64).writePointer(ammo); weapon.add(0x58).writePointer(definition); weapon.add(0xdc).writePointer(item);
            ammo.writePointer(e.ptr('0xdf525c')); ammo.add(4).writePointer(weapon);
            item.writePointer(e.ptr('0xdf31b8')); definition.writePointer(e.ptr('0xdf5fc0')); definition.add(0x314).writeU32(8);
            if (variation === 'enemy') e.actor.add(0x774).writeU8(4);
            const start = {context: {ecx: ammo}}, end = {context: {ecx: ammo}};
            e.hooks.get(0x845050).onEnter.call(start);
            ammo.add(0x14).writeU32(5000); e.hooks.get(0x845050).onLeave.call(start);
            ammo.add(0x18).writeU16(0x20); ammo.add(0xc).writeU32(8);
            e.ptr('0xfbb000').writeU32(5000);
            if (variation === 'reused') e.hooks.get(0x9dacb0).onEnter([e.actor, e.ptr(0)]);
            e.hooks.get(0x844650).onEnter.call({context: {ecx: ammo}});
            e.hooks.get(0x8454c0).onEnter.call(end);
            item.add(0x2c).writeU32(8); ammo.add(0xc).writeU32(0); ammo.add(0x18).writeU16(0);
            e.hooks.get(0x8454c0).onLeave.call(end);
            const recorded = (await e.snapshot()).events;
            const events = recorded.filter(x => x.kind === 'friendly_reload_end');
            assert.equal(events.length, variation === 'owned' ? 1 : 0);
            if (events.length) {
                assert.equal(events[0].cycle, 1); assert.equal(events[0].ammoBefore, 0);
                assert.equal(events[0].ammoCount, 8); assert.equal(events[0].pendingBefore, 8);
                assert.equal(events[0].startedAtTicks, 1000); assert.equal(events[0].nativeLoading, false);
                const progress = recorded.find(x => x.kind === 'friendly_reload_progress');
                assert.equal(progress.nativeLoading, true); assert.equal(progress.pendingRounds, 8);
            }
            assert.equal(e.submitted.length, 0); passed++;
        }
    }
    if (environment().hooks.has(0x851330)) {
        for (const variation of ['valid', 'unsupported', 'reused', 'replaced_aimer']) {
            const e = environment(); await e.snapshot();
            const weapon = e.ptr(0x740000), ammo = e.ptr(0x741000), item = e.ptr(0x742000);
            const definition = e.ptr(0x743000), placement = e.ptr(0x744000), vtable = e.ptr(0x745000);
            const shooter = e.ptr(0x746000);
            weapon.writePointer(e.ptr('0xdf51f0')); weapon.add(0x54).writePointer(e.actor);
            weapon.add(0x64).writePointer(ammo); weapon.add(0x58).writePointer(definition);
            weapon.add(0xdc).writePointer(item); weapon.add(0x60).writePointer(placement);
            weapon.add(0x68).writePointer(shooter); shooter.writePointer(e.ptr('0xdf57b4'));
            shooter.add(4).writePointer(weapon); shooter.add(8).writeU32(12);
            shooter.add(0xc).writeU8(1); shooter.add(0x10).writeU32(2);
            ammo.writePointer(e.ptr('0xdf525c')); ammo.add(4).writePointer(weapon);
            item.writePointer(e.ptr('0xdf31b8')); item.add(0x2c).writeU32(8);
            definition.writePointer(e.ptr('0xdf5fc0')); definition.add(0x314).writeU32(8);
            placement.writePointer(vtable); placement.add(8).writePointer(weapon);
            placement.add(0x54).writeU8(1); placement.add(4).writeU32(2000);
            placement.add(0xc).writeU32(3);
            vtable.add(0x10).writePointer(e.ptr(variation === 'unsupported' ? 0 : 0x855400));
            const invocation = {context: {ecx: placement}, returnAddress: e.ptr(0x843abc)};
            e.hooks.get(0x851330).onEnter.call(invocation);
            if (variation === 'reused') e.hooks.get(0x9dacb0).onEnter([e.actor, e.ptr(0)]);
            if (variation === 'replaced_aimer') weapon.add(0x60).writePointer(e.ptr(0x747000));
            e.hooks.get(0x851330).onLeave.call(invocation, e.ptr(5));
            const recorded = (await e.snapshot()).events.filter(x => x.kind === 'friendly_placement_result');
            assert.equal(recorded.length, variation === 'valid' ? 1 : 0);
            if (recorded.length) {
                assert.equal(recorded[0].resultRaw, 5); assert.equal(recorded[0].waitRaw, 1);
                assert.equal(recorded[0].placementDeadlineTicks, 2000); assert.equal(recorded[0].caller, '0x843abc');
                assert.equal(recorded[0].stateBeforeRaw, 3); assert.equal(recorded[0].shooterShotsRaw, 12);
                assert.equal(recorded[0].shooterActiveRaw, 1); assert.equal(recorded[0].shooterBurstRemainingRaw, 2);
                placement.writePointer(e.ptr('0xdf59f4'));
                for (const cycle of ['shot', 'no_shot', 'replaced_aimer', 'reused']) {
                    const call = {context: {ecx: shooter}};
                    weapon.add(0x60).writePointer(placement);
                    e.hooks.get(0x84d8a0).onEnter.call(call);
                    if (cycle === 'shot') { shooter.add(8).writeU32(13); item.add(0x2c).writeU32(7); }
                    if (cycle === 'reused') e.hooks.get(0x9dacb0).onEnter([e.actor, e.ptr(0)]);
                    if (cycle === 'replaced_aimer') weapon.add(0x60).writePointer(e.ptr(0x747000));
                    e.hooks.get(0x84d8a0).onLeave.call(call);
                    const cycles = (await e.snapshot()).events.filter(x => x.kind === 'friendly_shooter_cycle');
                    assert.equal(cycles.length, ['reused', 'replaced_aimer'].includes(cycle) ? 0 : 1);
                    if (cycles.length) {
                        assert.equal(cycles[0].shotCounterAdvanced, cycle === 'shot');
                        assert.equal(cycles[0].before.placementStateRaw, 3);
                        assert.equal(cycles[0].after.ammoCount, 7);
                    }
                    passed++;
                }
            }
            assert.equal(e.submitted.length, 0); passed++;
        }
    }
    for (const mode of [0, 1, 2, 3, 4]) {
        const e = environment(), raw = await e.snapshot(); e.ptr(0x370003).writeU8(mode);
        if (mode === 1) {
            const sensor = e.ptr(0x790000), vector = e.ptr(0x791000);
            e.actor.add(0x790).writePointer(sensor); sensor.writePointer(e.ptr('0xdf7c04'));
            sensor.add(0x1c).writePointer(e.actor); sensor.add(0x34).writePointer(vector);
            sensor.add(0x38).writePointer(vector.add(12));
            [0x402, 0x412, 0].forEach((flags, i) => {
                const record = e.ptr(0x792000 + i * 0x100); vector.add(i * 4).writePointer(record);
                record.add(4).writeU32(flags); record.add(8).writePointer(e.ptr(0x793000));
            });
        }
        if (mode === 4) e.ptr(0x22000c).writeU32(3);
        const result = await e.trial({id: '18', incarnation: 1, generation: raw.generation,
            revision: 0, sequence: 1, action: 'cover_scored_query', destination: [10, 0, 0]});
        if (mode === 4) {
            assert.equal(result.rejected, true); assert.deepEqual(e.coverLifecycle, []);
            assert.equal(e.submitted.length, 0); passed++; continue;
        }
        assert.deepEqual(e.coverLifecycle, ['construct', 'query', 'destroy']);
        assert.equal(e.submitted.length, 0);
        if (mode < 2) {
            assert.equal(result.status, 'queried'); assert.equal(result.candidateCount, mode);
            assert.equal(result.ranking, 'native-weighted-score-descending');
            assert.equal(result.observerIdentity.id, '18'); assert.equal(result.weightsRaw[0], 10);
            if (mode) {
                assert.equal(result.inputRecordCountRaw, 1); assert.equal(result.hasTargetRecordRaw, false);
                assert.equal(result.candidates[0].nativeAssessment.componentsRaw[9], 5);
                assert.equal(result.candidates[0].nativeAssessment.weightedScore, 5);
                assert.equal(result.candidates[0].sourceIdentity.entityId, 765);
                assert.equal(result.candidates[0].reachability, null);
            }
        } else assert.ok(result.error);
        passed++;
    }
    if (environment().hooks.has(0x8a75a0)) {
        for (const variation of ['valid', 'targeted', 'nonfinite', 'foreign', 'reused', 'oversized']) {
            const e = environment(); await e.snapshot();
            const request = e.ptr(0x750000), candidates = e.ptr(0x751000);
            request.add(0x1c).writePointer(e.actor);
            request.writePointer(candidates); request.add(4).writePointer(candidates.add(128));
            request.add(0x68).writeFloat(10); candidates.add(0x4c).writeU32(0xffffffe1);
            candidates.add(0x7c).writeFloat(7.5);
            if (variation === 'targeted' || variation === 'nonfinite') {
                const target = e.ptr(0x752000);
                request.add(0x4c).writePointer(target);
                target.add(0x10).writeFloat(variation === 'nonfinite' ? NaN : 90);
                target.add(0x14).writeFloat(80); target.add(0x18).writeFloat(70);
                candidates.add(0x10).writeFloat(30); candidates.add(0x14).writeFloat(40);
            }
            if (variation === 'foreign') e.actor.add(0x774).writeU8(9);
            const invocation = {context: {ecx: request}, returnAddress: e.ptr(0x8a7000)};
            e.hooks.get(0x8a75a0).onEnter.call(invocation);
            if (variation === 'reused') e.hooks.get(0x9dacb0).onEnter([e.actor, e.ptr(0)]);
            if (variation === 'oversized') request.add(4).writePointer(candidates.add(4097 * 128));
            e.hooks.get(0x8a75a0).onLeave.call(invocation);
            const snapshot = await e.snapshot();
            const records = snapshot.events.filter(x => x.kind === 'friendly_cover_assessment');
            assert.equal(records.length, ['valid', 'targeted'].includes(variation) ? 1 : 0);
            if (records.length) {
                assert.equal(records[0].candidateCount, 1); assert.equal(records[0].weightsRaw[0], 10);
                assert.equal(records[0].candidates[0].flagsRaw, 1);
                assert.equal(records[0].candidates[0].componentsRaw[9], 7.5);
                assert.equal(records[0].actor, undefined);
                assert.equal(records[0].observerPosition.length, 3);
                assert.deepEqual(records[0].targetRecordedPosition && Array.from(records[0].targetRecordedPosition),
                    variation === 'targeted' ? [90, 80, 70] : null);
                assert.deepEqual(Array.from(records[0].candidates[0].position), variation === 'targeted' ? [30, 40] : [0, 0]);
            }
            if (variation === 'nonfinite') assert.match(snapshot.fault, /spatial context/);
            if (variation === 'oversized') assert.match(snapshot.fault, /assessment vector/);
            assert.equal(e.submitted.length, 0); passed++;
        }
    }
    {
        const e = environment(), sensor=e.ptr(0x1b0000), vector=e.ptr(0x1f0000);
        e.actor.add(0x790).writePointer(sensor); sensor.writePointer(e.ptr('0xdf7c04'));
        sensor.add(0x1c).writePointer(e.actor); sensor.add(0x28).writePointer(vector);
        sensor.add(0x2c).writePointer(vector.add(300*4));
        for(let i=0;i<300;i++) {
            const record=e.ptr(0x1c0000+i*0x80);
            vector.add(i*4).writePointer(record);record.add(8).writePointer(e.actor);
        }
        e.api.capabilities().contacts=true;
        const first=(await e.snapshot()).perception[0], second=(await e.snapshot()).perception[0];
        assert.equal(first.totalRecords,300);assert.equal(first.records.length,0);
        assert.equal(first.nextSampleOffset,256);assert.equal(second.nextSampleOffset,212);
        assert.equal(second.records.length,0);assert.equal(e.submitted.length,0);
        for(let i=0;i<299;i++) e.ptr(0x1c0000+i*0x80).add(8).writePointer(e.ptr(0xdeadbeef));
        const targeted=await e.trial({id:'18',incarnation:1,generation:(await e.snapshot()).generation,
            revision:0,sequence:1,action:'sensor_query',targetId:'18'});
        assert.equal(targeted.records.length,1,'targeted preflight finds a later-page record');
        assert.equal(targeted.records[0].identity.id,'18');
        passed++;
    }
    for (const timer of [true,false]) {
        const e=environment(), baseline=await e.snapshot();
        const request={id:'18',incarnation:1,generation:baseline.generation,
            revision:0,sequence:1,action:'stance',stance:1};
        const pending=e.api.trialstance(request);
        if(timer)e.advance(2001);else e.elapse(2001);
        e.pump();const reply=await pending;
        assert.equal(reply.rejected,true);assert.equal(reply.unexecuted,true);
        assert.equal(e.submitted.length,0,'expired command never executes on late callback');
        const next=await e.trial({...request,sequence:2});
        assert.equal(next.status,'serialized');assert.equal(e.submitted.length,1);
        passed++;
    }
    console.log(JSON.stringify({passed, nativeBehavior: 'mocked'}));
})().catch(error => { console.error(error); process.exitCode = 1; });
