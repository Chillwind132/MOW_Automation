'use strict';
// Standalone bridge. No lobby host dependency and no native property patches.
// Until serialization/completion gates pass, the live adapter is observation-only.
const gameModule = Process.getModuleByName('mowas_2.exe');
if (Process.arch !== 'ia32' || !gameModule.base.equals(ptr('0x400000')))
    throw Error('Unsupported executable architecture/base');
const sites = {
    '0x7105a0': '558bec8b4508894108894d08b928affb',
    '0x715c60': '558bec83ec24568bf1e892803f00b968',
    '0x715b60': '53568bf1578b7e0c85ff750432dbeb07',
    '0x9dacb0': '558bec83ec48535657688c82e000e80d',
    '0x830f90': '558bec8a450883ec0c56518bd48bf188',
    '0x8e8c80': '558bec8b5508568bf18b8e100200008b',
    '0xaaa1a0': '8b412885c074313b05a07efe0074103b',
    '0x7154b0': 'a100b0fb00c3cccccccccccccccccccc',
    '0x9c91a0': '558bec8b45088a0d649ef30088085dc3',
    '0xaa9b20': '558bec51833d3878fc0000538bd9895d',
    '0xaaa330': '558bec83ec2453568b7508578bf95689',
    '0xaaa6f0': '558bec83ec1c8b45085383c010575089',
    '0xaa9e30': '558bec53568bf18b4d086a018a5e04e8',
    '0x908a20': '558bec568b750885f67434f7461c000a',
    '0x8a65f0': '558bec81ec10010000f30f1005a417f3',
    '0x8aa390': 'c7412400000000a188c6fb00894110a1',
    '0xba7c00': '558bec83ec0c5657e8037601008b4058',
    '0xbbf230': '558bec566a006894f8f6006868f8f600',
    '0xbbf290': '558bec566a006894f8f6006868f8f600',
    '0xb57e90': '558bec83ec28535657894dfce80fd6bb',
    '0x85cc30': '558bec56578bf1e8246e17008b4d',
    '0xaa3e20': '558bec83ec24538bd956578b7d08',
    '0x644480': '558bec83ec08578b7d08894df88b',
    '0x794120': 'e85b02000085c07406f640180175',
    '0xa9ca60': '558bec81ec0c01000056578b7d10',
    '0xa9cc78': 'e8a374cfff8d8df4feffff8bf0',
    '0x9dc350': '558bec83ec4c53565768dc82e000',
    '0x9c9560': '558bec8b4508568bf18a108b450c',
    '0x9c9381': 'b9e037fe00e8d50100008be55dc3',
    '0x88daf0': '558bec81ec80000000a14c2dfd00',
    '0x88ec83': 'e82868e8ff5f5e8983b00000005b',
    '0x8433f0': '83795800741e8b416cf680a00600000174128b4160837810007409837818007403b001c332c0c3',
    '0x844470': '558bec83ec08568bf1e862fcffff84c0',
    '0x844650': '558bec83ec0c578bf90fb74718a80174',
    '0x8454c0': '558bec83ec30b8cfff0000568bf16621',
    '0x845050': '558bec83ec1856578bf9c745e8250000',
    '0x851330': '558bec83ec38578bf9897de48b4f08e8',
    '0x8a75a0': '558bec81ecb801000053568bf1c78548',
    '0x8a68a0': '558bec568bf16a008d4e0cc706000000',
    '0x8a6a50': '558beca13833fd0081ecb0000000a33c',
    '0x513b80': '568bf1c746547419d8008b0e85c97425',
    '0x8c44d0': '558bec568bf1578b7d088bcf8a878007',
    '0x8c3c40': '558bec83ec348b55105356578b028bf9',
    '0x8b2740': '558bec8b450c8b4d083d555555157734',
    '0x84d0a0': '568bf18b4e048b4160837810007428e80c63ffff84c0741f8b46048b4864e8bd6effff84c075108b4e04e82163ffff84c07404b0015ec332c05ec3'
};
for (const [address, expected] of Object.entries(sites)) {
    const actual = Array.from(new Uint8Array(ptr(address).readByteArray(expected.length / 2)))
        .map(b => b.toString(16).padStart(2, '0')).join('');
    if (actual !== expected) throw Error('Unsupported/already instrumented code at ' + address);
}
const caps = {enumeration: true, ownership: true, identityLifecycle: false,
    simulationClock: true, commandAuthority: false, synchronization: false,
    stance: false, move: false, cover: false, attack: false, build: false,
    contacts: false, pathQuery: false, weaponReadiness: true, ammoLoading: true, shotEvents: true, death: false, objectives: false};
const MAX_OWNED_UNITS = 1024;
let ticks = 0, generation = 0, lastWorld = '', lastTime = -1;
// A fresh attachment must reject intents from an earlier, unloaded bridge even
// if the world and actor IDs happen to be the same.
const attachment = Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
const matchToken = () => attachment + ':' + generation;
let incarnations = new Map(), actors = new Map(), events = [], eventSequence = 0;
let actorKinds = new Map();
const coverSources = new Map();
const perceptionCache = new Map();
const sensorSampleOffsets = new Map();
const followedGroups = new Map();
let perceptionCursor = 0;
let enrollment = new Map();
let pending = null, stopped = false, fault = null, lastPoll = Date.now();
const hooks = [];
const pathDescriptor = new NativeFunction(ptr('0x8c44d0'), 'pointer', ['pointer','pointer'],
    {abi:'thiscall', exceptions:'propagate'});
const pathQuery = new NativeFunction(ptr('0x8c3c40'), 'uint8', ['pointer','pointer','pointer','pointer'],
    {abi:'thiscall', exceptions:'propagate'});
const pathRelease = new NativeFunction(ptr('0x8b2740'), 'void', ['pointer','uint'],
    {abi:'mscdecl', exceptions:'propagate'});
class Rejected extends Error {}
let issuing = false, diagnosticSequence = 0, commandRevision = 0;
let ignoredUnownedCommands = 0;
let installationCalls = 0;
const serialize = new NativeFunction(ptr('0xaa9b20'), 'void', ['pointer', 'pointer'],
    {abi: 'thiscall', exceptions: 'propagate'});
const coverQuery = new NativeFunction(ptr('0x8a65f0'), 'uint8', ['pointer', 'pointer', 'pointer', 'uint8'],
    {abi: 'mscdecl', exceptions: 'propagate'});
const coverInit = new NativeFunction(ptr('0x8aa390'), 'void', ['pointer'],
    {abi: 'thiscall', exceptions: 'propagate'});
const coverRequestInit = new NativeFunction(ptr('0x8a68a0'), 'pointer', ['pointer', 'pointer', 'pointer', 'float'],
    {abi: 'thiscall', exceptions: 'propagate'});
const coverRequestQuery = new NativeFunction(ptr('0x8a6a50'), 'uint8', ['pointer'],
    {abi: 'thiscall', exceptions: 'propagate'});
const coverRequestDestroy = new NativeFunction(ptr('0x513b80'), 'void', ['pointer'],
    {abi: 'thiscall', exceptions: 'propagate'});
const purchaseEntry = new NativeFunction(ptr('0xbbf230'), 'pointer', ['pointer', 'pointer'],
    {abi: 'mscdecl', exceptions: 'propagate'});
const purchaseAvailable = new NativeFunction(ptr('0xbbf290'), 'uint8', ['pointer', 'uint8', 'pointer'],
    {abi: 'mscdecl', exceptions: 'propagate'});
const purchaseNative = new NativeFunction(ptr('0xba7c00'), 'void', ['pointer'],
    {abi: 'stdcall', exceptions: 'propagate'}); // native ret 4 owns argument cleanup
const customActionAvailable = new NativeFunction(ptr('0xaa3e20'), 'uint8', ['pointer', 'pointer'],
    {abi: 'thiscall', exceptions: 'propagate'});
const matchesItemFilter = new NativeFunction(ptr('0x644480'), 'uint8', ['pointer', 'pointer'],
    {abi: 'thiscall', exceptions: 'propagate'});
function eligible(actor) {
    const flags = actor.add(0x1c).readU32(), status = actor.add(0x780).readU32();
    const health = actor.add(0x32c).readPointer().add(0xc).readPointer();
    return !(flags & 0xa00) && !!(status & 0x100) &&
        (health.isNull() || !(health.add(0xf8).readU8() & 5)) &&
        actor.add(0x320).readPointer().add(0x54).readU32() !== 2;
}
function coverInputCount(actor) {
    // Mirror only 8a8a80's input filter, not a visibility/enemy classification.
    const sensor = actor.add(0x790).readPointer();
    if (sensor.isNull() || !sensor.readPointer().equals(ptr('0xdf7c04'))) return null;
    if (!sensor.add(0x1c).readPointer().equals(actor)) throw Error('Cover sensor owner mismatch');
    const begin = sensor.add(0x34).readPointer(), end = sensor.add(0x38).readPointer();
    const bytes = end.sub(begin).toInt32();
    if (bytes < 0 || bytes % 4 || bytes > 256 * 4) throw Error('Cover sensor input budget exceeded');
    let count = 0;
    for (let i = 0; i < bytes; i += 4) {
        const record = begin.add(i).readPointer();
        if (record.isNull()) throw Error('Invalid cover sensor record');
        const flags = record.add(4).readU32();
        if ((flags & 0x402) && !(flags & 0x10) && !record.add(8).readPointer().isNull()) count++;
    }
    return count;
}
function rifleFireState(weapon, count, flags, recovery) {
    const definition = weapon.add(0x58).readPointer(), placement = weapon.add(0x60).readPointer();
    const context = weapon.add(0x6c).readPointer(), shooter = weapon.add(0x68).readPointer();
    if (definition.isNull() || !definition.readPointer().equals(ptr('0xdf5fc0')) ||
        placement.isNull() || !placement.readPointer().equals(ptr('0xdf59f4')) ||
        context.isNull() || !context.readPointer().equals(ptr('0xdf54a4')) ||
        shooter.isNull() || !shooter.readPointer().equals(ptr('0xdf57b4'))) return null;
    if (!placement.add(8).readPointer().equals(weapon) ||
        !context.add(0x1a8).readPointer().equals(weapon) ||
        !shooter.add(4).readPointer().equals(weapon)) throw Error('Fire component owner mismatch');
    const clip = definition.add(0x314).readU32();
    if (clip > 10000) throw Error('Invalid native clip size');
    const available = count > 0 && ((clip ? count % clip : count) !== 0 || !(flags & 0x10));
    const nativeFirePredicate = !(flags & 0x24) && recovery === 0 && available &&
        !!(context.add(0x6a0).readU8() & 1) &&
        !placement.add(0x10).readPointer().isNull() && !placement.add(0x18).readPointer().isNull();
    const placementStateRaw = placement.add(0xc).readU32();
    return {nativeFirePredicate, placementStateRaw, waitRaw: placement.add(0x54).readU8(),
        placementDeadlineTicks: placement.add(4).readU32(),
        readinessCandidate: nativeFirePredicate && [3, 4].includes(placementStateRaw)};
}
function inventoryFilterCounts(actor, filter) {
    const tagsBound = tags => {
        const bytes = tags.add(0x22c).readPointer().sub(tags.add(0x228).readPointer()).toInt32();
        if (bytes < 0 || bytes % 0x44 || bytes > 128 * 0x44) throw Error('Invalid item tags');
        return bytes;
    };
    if (!tagsBound(filter)) throw Error('Inventory action filter missing');
    const holder = actor.add(0x32c).readPointer().add(0x14).readPointer();
    if (holder.isNull()) throw Error('Inventory holder missing');
    const inventory = holder.add(0x68).readPointer();
    if (inventory.isNull() || !inventory.readPointer().equals(ptr('0xdf3e1c')))
        throw Error('Unsupported inventory type');
    const first = inventory.add(0xc).readPointer(), last = inventory.add(0x10).readPointer();
    const bytes = last.sub(first).toInt32();
    if (bytes < 0 || bytes % 4 || bytes > 256 * 4) throw Error('Inventory exceeds bound');
    let itemCount = 0;
    const seen = new Set();
    const kitCount = item => {
        if (!item.readPointer().equals(ptr('0xdf31b8'))) throw Error('Invalid inventory item type');
        const stuff = item.add(0x20).readPointer();
        if (stuff.isNull()) return 0;
        const tags = stuff.add(0x804);
        tagsBound(tags);
        const count = matchesItemFilter(tags, filter) ? item.add(0x24).readU32() : 0;
        if (count > 10000) throw Error('Invalid kit count');
        return count;
    };
    for (let offset = 0; offset < bytes; offset += 4) {
        const item = first.add(offset).readPointer();
        if (item.isNull() || seen.has(item.toString()) || !item.readPointer().equals(ptr('0xdf31b8')))
            throw Error('Invalid inventory item');
        seen.add(item.toString());
        itemCount += kitCount(item);
        if (itemCount > 10000) throw Error('Invalid kit count');
    }
    const boxes = holder.add(0x5c).readPointer();
    const boxBytes = holder.add(0x60).readPointer().sub(boxes).toInt32();
    if (boxBytes < 0 || boxBytes % 4 || boxBytes > 16 * 4) throw Error('Invalid inventory boxes');
    let heldItemCount = 0, totalItemCount = itemCount;
    const hands = new Set(), heldItems = new Set();
    for (let offset = 0; offset < boxBytes; offset += 4) {
        const box = boxes.add(offset).readPointer(), type = box.readPointer();
        const name = type.equals(ptr('0xdf37e4')) ? 'hand_left' : type.equals(ptr('0xdf383c')) ? 'hand_right' : null;
        if (!name) continue;
        if (hands.has(name) || box.add(8).readUtf8String(name.length) !== name) throw Error('Invalid hand box');
        hands.add(name);
        // Native hand-box virtual getter 81cbd0 returns this item pointer.
        const item = box.add(0x2a0).readPointer();
        if (item.isNull() || heldItems.has(item.toString())) continue;
        heldItems.add(item.toString());
        const count = kitCount(item);
        heldItemCount += count;
        if (!seen.has(item.toString())) totalItemCount += count;
    }
    if (hands.size !== 2 || totalItemCount > 10000) throw Error('Incomplete held-item accounting');
    return {itemCount, heldItemCount, totalItemCount};
}
function stuffModel(definition, expectedType, cache = null) {
    if (definition.isNull()) return null;
    const key = expectedType + ':' + definition.toString();
    if (cache?.has(key)) return cache.get(key);
    const model = definition.readPointer().equals(ptr(expectedType)) ? stringAt(definition.add(0x10)) || null : null;
    if (cache) cache.set(key, model);
    return model;
}
function weaponObservation(actor, row, baseline, ammoOnly = false, modelCache = null) {
    const weaponry = actor.add(0x794).readPointer();
    if (weaponry.isNull() || !weaponry.readPointer().equals(ptr('0xdf50d8'))) {
        if (ammoOnly) return null;
        throw Error('Unsupported weaponry owner/type');
    }
    if (!weaponry.add(0x3c).readPointer().equals(actor)) throw Error('Unsupported weaponry owner/type');
    const vector = offset => {
        const first = weaponry.add(offset).readPointer(), last = weaponry.add(offset + 4).readPointer();
        const bytes = last.sub(first).toInt32();
        if (bytes < 0 || bytes % 4 || bytes > 32 * 4) throw Error('Invalid weapon vector');
        return {first, count: bytes / 4};
    };
    const slots = vector(0x14), index = weaponry.add(0x30).readS32();
    let weapon = ptr(0);
    if (index >= 0) {
        if (index >= slots.count) throw Error('Invalid current weapon index');
        const slot = slots.first.add(index * 4).readPointer();
        if (!slot.isNull()) weapon = slot.add(0x1a8).readPointer();
    }
    if (weapon.isNull()) {
        const fallback = vector(0x20);
        if (fallback.count) weapon = fallback.first.readPointer();
    }
    if (weapon.isNull()) return ammoOnly ? null : {status: 'queried', equipped: false, readyToFire: null};
    if (!weapon.readPointer().equals(ptr('0xdf51f0'))) {
        if (ammoOnly) return null;
        throw Error('Unsupported weapon owner/type');
    }
    if (!weapon.add(0x54).readPointer().equals(actor)) throw Error('Unsupported weapon owner/type');
    const definition = weapon.add(0x58).readPointer();
    const weaponModel = stuffModel(definition, '0xdf5fc0', modelCache);
    const ammo = weapon.add(0x64).readPointer();
    if (ammo.isNull() || !ammo.readPointer().equals(ptr('0xdf525c')))
        return ammoOnly ? null : {status: 'queried', equipped: true, supportedAmmo: false, readyToFire: null};
    if (!ammo.add(4).readPointer().equals(weapon)) throw Error('Ammo owner mismatch');
    const item = weapon.add(0xdc).readPointer();
    if (!item.isNull() && !item.readPointer().equals(ptr('0xdf31b8'))) {
        if (ammoOnly) return null;
        throw Error('Unsupported weapon inventory item');
    }
    const count = item.isNull() ? 0 : item.add(0x2c).readU32();
    if (count > 10000) throw Error('Invalid ammunition count');
    // 843e50 reads the currently loaded filling from inventory item +28;
    // 818530 writes that pointer and its round count together during filling.
    // eStuffBullet (863aa0) shares the mapped base entity-name string at +10.
    const projectile = item.isNull() ? ptr(0) : item.add(0x28).readPointer();
    const projectileModel = stuffModel(projectile, '0xdf61d0', modelCache);
    const flags = ammo.add(0x18).readU16();
    const recovery = ammo.add(0x14).readU32();
    // Runtime loading (20) differs from save-state loading (2) and the
    // reload-request latch (10), which is also set after individual shots.
    const pendingRounds = flags & 0x20 ? ammo.add(0xc).readU32() : null;
    if (pendingRounds !== null && pendingRounds > 10000) throw Error('Invalid pending ammunition count');
    if (ammoOnly) return {simulationTicks: baseline.simulationTicks, weaponModel, projectileModel, ammoCount: count, nativeLoading: !!(flags & 0x20),
        ...(caps.weaponReadiness ? {fireState: rifleFireState(weapon, count, flags, recovery)} : {})};
    // Positive readiness evidence only. Other preparation states can also fire;
    // a false candidate must remain unknown rather than mean unable to fire.
    const fireState = rifleFireState(weapon, count, flags, recovery);
    const nativeFirePredicate = fireState ? fireState.nativeFirePredicate : null;
    return {status: 'queried', equipped: true, supportedAmmo: true, weaponModel, projectileModel,
        simulationTicks: baseline.simulationTicks, ammoCount: count, ammoFlagsRaw: flags,
        projectileEvents: baseline.events.filter(e => e.kind === 'bullet_created' &&
            e.id === row.id && e.incarnation === row.incarnation),
        loadingSerialized: !!(flags & 2), reloadRequestedSerialized: !!(flags & 0x10),
        nativeLoading: !!(flags & 0x20), nativeUnloading: !!(flags & 4), pendingRounds,
        recoveryUntilTicks: recovery, nativeFirePredicate, fireState,
        readyToFire: caps.weaponReadiness && fireState && fireState.readinessCandidate ? true : null,
        interpretation: 'Conservative positive native readiness; other states, hit accuracy and future firing remain unproven'};
}
function trial(options) {
    if (options.asPlayerCommand) throw new Rejected('Player-emission diagnostic disabled after native command-stream failure');
    // Refresh the complete registry/ownership and the addressed unit's detailed
    // eligibility, modes and revision. Scheduled observations read all units.
    const baseline = inspect(false, false, options.followLeader ? [options.id, options.followLeader.id] : options.id ?? null);
    try {
        if (baseline.paused) throw new Rejected('Game paused');
        return {...trialObserved(options, baseline), observedEvents: baseline.events};
    } catch (error) {
        error.observedEvents = baseline.events;
        throw error;
    }
}
function pathObservation(actor, row, destination, baseline) {
    const descriptor = Memory.alloc(16), task = Memory.alloc(24), output = Memory.alloc(36), origin = Memory.alloc(8);
    descriptor.writeByteArray(new Uint8Array(16)); task.writeByteArray(new Uint8Array(24));
    output.writeByteArray(new Uint8Array(36));
    pathDescriptor(descriptor, actor);
    if (!descriptor.readPointer().equals(actor)) throw Error('Path descriptor ownership mismatch');
    // Exact native Task::ePoint layout observed at 8e14ba and its clone 8a98e0.
    task.writePointer(ptr('0xdf8728')); task.add(4).writeU8(1); task.add(8).writeFloat(100000);
    task.add(0xc).writeFloat(destination[0]); task.add(0x10).writeFloat(destination[1]); task.add(0x14).writeU8(1);
    origin.writeFloat(row.position[0]); origin.add(4).writeFloat(row.position[1]);
    const started = Date.now();
    let released = false, result;
    try {
        const nativeResult = pathQuery(task, descriptor, output, origin);
        const first = output.readPointer(), last = output.add(4).readPointer(), capacity = output.add(8).readPointer();
        const bytes = last.sub(first).toInt32(), allocated = capacity.sub(first).toInt32();
        if (bytes < 0 || bytes % 12 || bytes > 4096 * 12 || allocated < bytes || allocated % 12 || allocated > 16384 * 12)
            throw Error('Invalid native path output vector');
        const flags = [output.add(0x20).readU8(),output.add(0x21).readU8()], cost = output.add(0xc).readFloat();
        if (![0,1].includes(nativeResult) || flags.some(value => value > 1) || nativeResult !== flags[0] || !Number.isFinite(cost))
            throw Error('Unsupported native path result');
        const point = pointer => [pointer.readFloat(),pointer.add(4).readFloat()];
        const endpoint = bytes ? point(first) : null, startpoint = bytes ? point(last.sub(12)) : null;
        if ([...(endpoint || []),...(startpoint || [])].some(value => !Number.isFinite(value)))
            throw Error('Invalid native path endpoint');
        result = {status:'queried',generation:baseline.generation,simulationTicks:baseline.simulationTicks,
            observerIdentity:{id:row.id,incarnation:row.incarnation,owner:row.owner},
            origin:row.position.slice(0,2),destination:destination.slice(0,2),
            nativeSucceeded:nativeResult === 1,partial:flags[1] === 1,endpoint,startpoint,cost,pointCount:bytes / 12,
            reachesRequestedPoint:nativeResult === 1 && flags[1] === 0 && endpoint !== null &&
                Math.hypot(endpoint[0]-destination[0],endpoint[1]-destination[1]) <= 3 &&
                Math.hypot(startpoint[0]-row.position[0],startpoint[1]-row.position[1]) <= 3,
            elapsedMs:Date.now()-started,interpretation:'Native local path result; obstacle/failure semantics under validation'};
    } finally {
        const first = output.readPointer(), allocated = output.add(8).readPointer().sub(first).toInt32();
        if (!first.isNull()) {
            if (allocated <= 0 || allocated % 12 || allocated > 16384 * 12) throw Error('Cannot safely release malformed path vector');
            pathRelease(first,allocated / 12);
        }
        released = true;
    }
    return {...result,vectorReleased:released};
}
function trialObserved(options, baseline) {
    if (fault || options.generation !== matchToken() || options.revision !== commandRevision)
        throw new Rejected('Stale match/manual-command revision');
    if (options.submitBeforeTicks !== undefined &&
        (!Number.isFinite(options.submitBeforeTicks) || baseline.simulationTicks >= options.submitBeforeTicks))
        throw new Rejected('Submission deadline expired');
    if (!Number.isInteger(options.sequence) || options.sequence <= diagnosticSequence)
        throw new Rejected('Duplicate diagnostic intent');
    diagnosticSequence = options.sequence;
    const action = options.action || 'stance';
    const purchasing = action === 'purchase_query' || action === 'purchase';
    const row = baseline.units.find(u => u.id === options.id && u.incarnation === options.incarnation);
    if (!purchasing && (!row || !row.eligible || (row.squadLeader && row.individualOrder !== true && action !== 'sensor_query') || row.controlLockRaw))
        throw new Rejected('Diagnostic requires eligible owned nonleader infantry without direct control');
    if (purchasing && !baseline.team) throw new Rejected('Purchase requires an active local playing team');
    if (['stance','move','cover','attack','barricade'].includes(action) && ![0,1,2].includes(row.stance))
        throw new Rejected('Unsupported current infantry stance; unit temporarily unavailable');
    if (options.requireEnrolled && (!row || !row.enrolled || options.unitRevision !== row.revision))
        throw new Rejected('Unit reclaimed or revision cancelled');
    let followingLeader = null;
    if (options.followLeader !== undefined) {
        const expected = options.followLeader;
        followingLeader = baseline.units.find(u => u.id === expected?.id && u.incarnation === expected?.incarnation);
        if (action !== 'move' || options.requireEnrolled !== true || row.squadLeader || !followingLeader ||
            expected.revision !== 0 || followingLeader.revision !== 0 || !followingLeader.eligible ||
            !followingLeader.squadLeader || followingLeader.individualOrder || followingLeader.controlLockRaw ||
            followingLeader.coverState !== 0 ||
            (![0, 0x1000].includes(followingLeader.movementBits) && !followingLeader.controllerGroup) ||
            ![0, 1, 2].includes(followingLeader.stance) || followingLeader.id === row.id ||
            !row.squadMembers.includes(followingLeader.id) || !followingLeader.squadMembers.includes(row.id))
            throw new Rejected('Leader follow authority or squad scope changed');
        const memberActor = actors.get(Number(row.id)), leaderActor = actors.get(Number(followingLeader.id));
        const squad = memberActor.add(0x78c).readPointer().add(0x8c).readPointer();
        if (squad.isNull() || !squad.equals(leaderActor.add(0x78c).readPointer().add(0x8c).readPointer()) ||
            !squad.add(0x70).readPointer().equals(leaderActor))
            throw new Rejected('Leader follow native squad changed');
    }
    if (!['stance', 'move', 'path_query', 'cover', 'cover_query', 'cover_scored_query', 'sensor_query', 'attack_query', 'attack', 'weapon_query', 'grenade_query', 'barricade_query', 'barricade', 'purchase_query', 'purchase', 'mode'].includes(action)) throw new Rejected('Unsupported diagnostic action');
    if (typeof humanOpponentTrial !== 'undefined' && humanOpponentTrial === true &&
        ['cover', 'cover_query', 'cover_scored_query'].includes(action))
        throw new Rejected('Native cover is withheld pending human-client synchronization validation');
    if (['stance', 'move', 'path_query', 'cover', 'cover_scored_query', 'attack', 'barricade', 'purchase', 'mode'].includes(action)) {
        const manager = ptr('0xfed0c4').readPointer();
        if (manager.isNull() || !manager.readPointer().equals(ptr('0xe317f0')) ||
            manager.add(0xc).readU32() !== 1)
            throw new Rejected('Diagnostic action requires an active supported match');
    }
    if (action === 'mode' && ![0, 1].includes(options.mode)) throw new Rejected('Unsupported movement mode');
    if (action === 'stance' && ![0, 1, 2].includes(options.stance)) throw new Rejected('Invalid stance');
    let buildDirection = null;
    if (options.buildDirection !== undefined && action !== 'barricade')
        throw new Rejected('Build direction requires a barricade action');
    if (action === 'barricade') {
        const direction = options.buildDirection === undefined ? [1, 0] : options.buildDirection;
        if (!Array.isArray(direction) || direction.length !== 2 || !direction.every(Number.isFinite))
            throw new Rejected('Invalid build direction');
        const length = Math.hypot(...direction);
        if (!Number.isFinite(length) || length < 1e-6) throw new Rejected('Invalid build direction');
        buildDirection = direction.map(value => value / length);
    }
    if ((['move', 'path_query', 'barricade'].includes(action) || (['cover', 'cover_query', 'cover_scored_query'].includes(action) && options.destination !== undefined)) &&
        (!Array.isArray(options.destination) || options.destination.length !== 3 ||
        !options.destination.every(Number.isFinite) ||
        Math.hypot(...options.destination.map((v, i) => v - row.position[i])) > (action === 'barricade' ? 150 : 600.001)))
        throw new Rejected('Diagnostic destination exceeds distance bound');
    const actor = actors.get(Number(options.id));
    let attackTarget = null;
    if (!purchasing && (!actor || actor.add(0x774).readU8() !== Number(baseline.owner) || !eligible(actor)))
        throw new Rejected('Ownership/eligibility changed');
    if (action === 'path_query') return pathObservation(actor, row, options.destination, baseline);
    if (action === 'barricade_query' || action === 'barricade') {
        const barricade = ptr('0xfe84b0').readPointer();
        if (barricade.isNull() || !barricade.readPointer().equals(ptr('0xe1b2a8')) ||
            barricade.add(0x2fc).readU8() !== 37) throw Error('Unsupported barricade action');
        const {itemCount, heldItemCount, totalItemCount} = inventoryFilterCounts(actor, barricade.add(0x78));
        const query = {status: 'queried', actionId: 37,
            nativeActorInventoryAllowed: customActionAvailable(barricade, actor) !== 0,
            placementValid: null, itemCount, heldItemCount, totalItemCount,
            constructionSupported: false, installationCalls,
            installationEvents: baseline.events.filter(e => e.kind === 'install_entity_created' &&
                e.id === row.id && e.incarnation === row.incarnation),
            interpretation: 'Native actor/inventory gate only; placement, consumption and replication unverified'};
        if (action === 'barricade_query') return query;
        if (!query.nativeActorInventoryAllowed || totalItemCount !== 1)
            throw new Rejected('Construction trial requires native availability and exactly one kit');
        if (stringAt(barricade.add(0x5a8)) !== 'sandbag3')
            throw new Rejected('Unsupported barricade entity');
    }
    if (action === 'weapon_query') return weaponObservation(actor, row, baseline);
    if (action === 'grenade_query') {
        const kinds = {fragmentation: ['0xfe7eec','0xe1af18',23], smoke: ['0xfe7ef4','0xe1b12c',25],
                       anti_tank: ['0xfe7ef0','0xe1afbc',24]};
        if (typeof options.grenadeKind !== 'string' || !Object.prototype.hasOwnProperty.call(kinds,options.grenadeKind))
            throw new Rejected('Unsupported grenade kind');
        const [address,vtable,actionId] = kinds[options.grenadeKind], nativeAction = ptr(address).readPointer();
        if (nativeAction.isNull() || !nativeAction.readPointer().equals(ptr(vtable)) || nativeAction.add(0x2fc).readU8() !== actionId)
            throw Error('Unsupported native grenade action');
        return {status:'queried',grenadeKind:options.grenadeKind,actionId,
            ...inventoryFilterCounts(actor,nativeAction.add(0x78)),
            nativeActorInventoryAllowed:customActionAvailable(nativeAction,actor)!==0,
            throwSupported:false,interpretation:'Inventory availability only; trajectory, consumption and effects unverified'};
    }
    if (action === 'purchase_query' || action === 'purchase') {
        // Robz smgs(usa) is an armored rifle squad, despite its name.
        // smgs2(usa) supplies the Thompson soldier verified in the mod breed.
        // The two-man bazookers team makes its launcher the group-only leader.
        // riflemans_bar puts the launcher on an individually ordered member.
        const templates = {rifle: [854, 'riflemans(usa)'], assault: [879, 'smgs2(usa)'],
                           anti_tank: [855, 'riflemans_bar(usa)']};
        if (typeof humanOpponentTrial !== 'undefined' && humanOpponentTrial === true) {
            // Explicit current-session German infantry trial. Template IDs/names
            // were read from this native catalog; purchase availability remains native.
            templates.rifle = [994, 'grenadiers_44(ger)'];
            templates.assault = [1034, 'smgs2_40(ger)'];
            templates.anti_tank = [1042, 'bazooker3(ger)'];
        }
        const selected = options.purchaseTemplate ?? 'rifle';
        if (typeof selected !== 'string' || !Object.prototype.hasOwnProperty.call(templates, selected))
            throw new Rejected('Unsupported infantry purchase template');
        const [templateId, templateName] = templates[selected];
        const catalog = ptr('0xf3c930').readPointer();
        if (!catalog.readPointer().equals(ptr('0xe31eb0'))) throw Error('Unsupported purchase catalog');
        const begin = catalog.add(4).readPointer(), end = catalog.add(8).readPointer();
        const bytes = end.sub(begin).toInt32();
        if (bytes < 0 || bytes % 4 || bytes > 4096 * 4) throw Error('Invalid purchase catalog');
        let template = null;
        for (let n = 0; n < bytes; n += 4) {
            const candidate = begin.add(n).readPointer();
            if (!candidate.readPointer().equals(ptr('0xe31eb8'))) throw Error('Unknown purchase template');
            if (candidate.add(0x388).readU16() !== templateId) continue;
            if (candidate.add(8).readUtf8String(templateName.length) !== templateName ||
                candidate.add(8 + templateName.length).readU8() !== 0)
                throw Error('Infantry template identity mismatch');
            if (template !== null) throw Error('Duplicate purchase template ID');
            template = candidate;
        }
        if (template === null) throw new Rejected('Validated infantry template unavailable');
        const entry = purchaseEntry(template, ptr(0));
        if (!entry.isNull() && (!entry.readPointer().equals(template) ||
            entry.add(4).readU8() !== Number(baseline.owner))) throw Error('Purchase owner/template mismatch');
        const available = !entry.isNull() && purchaseAvailable(template, 1, ptr(0)) !== 0;
        const result = {status: 'queried', templateId, templateName,
            owner: baseline.owner, available,
            entryFlags: entry.isNull() ? null : [5, 6, 7].map(o => entry.add(o).readU8()),
            templateValuesRaw: [0x29c, 0x2a0, 0x2a4].map(o => template.add(o).readFloat())};
        if (action === 'purchase') {
            if (!available) throw new Rejected('Native purchase checks refused infantry');
            purchaseNative(template.add(4));
            result.status = 'submitted_unconfirmed';
            result.completed = false; // only observed new units can establish completion
        }
        return result;
    }
    if (action === 'sensor_query') return sensorObservation(actor, row, baseline, null, 0, options.targetId ?? null);
    if (action === 'attack_query' || action === 'attack') {
        const attack = ptr('0xfe7eb0').readPointer();
        if (attack.isNull() || !attack.readPointer().equals(ptr('0xe1ad00')) || attack.add(0x2fc).readU8() !== 30)
            throw Error('Unsupported native attack action');
        const observation = sensorObservation(actor, row, baseline, null, 0,
            options.target?.id ?? options.targetId ?? null), targets = [], seen = new Set();
        const ammunition = weaponObservation(actor, row, baseline, true);
        const bazooka = ammunition?.weaponModel === 'bazooka';
        const heatLauncher = bazooka || (ammunition?.weaponModel === 'garand_grenade' &&
            ammunition.projectileModel === 'garand_heat_ammo');
        const antiArmor = heatLauncher && ammunition.ammoCount > 0 && ammunition.nativeLoading === false;
        for (const record of observation.records) {
            if (record.visible !== true || record.enemy !== true || record.nativeDeadPredicate !== false ||
                !(record.identity.kind === 'vehicle' ? antiArmor : record.identity.kind === 'infantry' && !heatLauncher)) continue;
            const identity = record.identity, target = actors.get(Number(identity.id));
            if (!target || identity.owner === baseline.owner ||
                incarnations.get(Number(identity.id)) !== identity.incarnation ||
                String(target.add(0x774).readU8()) !== identity.owner || seen.has(identity.id)) continue;
            const entityId = target.add(0x54).readU16();
            if (entityId === 0xffff || !(target.add(0x18).readU8() & 2)) continue;
            seen.add(identity.id);
            targets.push({identity, entityId, observedPosition: record.visualObservedPosition,
                observedAtTicks: record.visualObservedAtTicks});
            if (targets.length === 32) break;
        }
        if (action === 'attack_query') return {status: 'queried', generation: baseline.generation, simulationTicks: baseline.simulationTicks,
            observerIdentity: observation.observerIdentity, targets,
            interpretation: 'Visible enemy target preflight only; no attack submitted'};
        const expected = options.target;
        if (!expected || expected.generation !== baseline.generation ||
            typeof expected.id !== 'string' || !Number.isInteger(expected.incarnation) ||
            !Number.isInteger(expected.entityId) || typeof expected.owner !== 'string')
            throw new Rejected('Invalid attack target identity');
        attackTarget = targets.find(t => t.identity.id === expected.id &&
            t.identity.incarnation === expected.incarnation && t.identity.owner === expected.owner &&
            t.entityId === expected.entityId);
        if (!attackTarget) throw new Rejected('Attack target no longer a visible living enemy');
    }
    if (action === 'cover_scored_query') {
        const request = Memory.alloc(0x90), point = Memory.alloc(12), started = Date.now();
        const inputRecords = coverInputCount(actor);
        const center = options.destination || row.position;
        center.forEach((v, i) => point.add(i * 4).writeFloat(v));
        request.writeByteArray(new Uint8Array(0x90));
        // Native constructor owns its vector; the matching destructor frees
        // that vector, never this Frida-allocated request storage.
        coverRequestInit(request, actor, point, 60.);
        let result;
        try {
            const weights = Array.from({length: 8}, (_, i) => request.add(0x68 + i * 4).readFloat());
            if (!weights.every(Number.isFinite)) throw Error('Invalid native cover weights');
            const found = coverRequestQuery(request) !== 0;
            const begin = request.readPointer(), end = request.add(4).readPointer();
            const capacity = request.add(8).readPointer();
            const bytes = end.sub(begin).toInt32(), allocated = capacity.sub(begin).toInt32();
            if (bytes < 0 || bytes % 128 || bytes > 4096 * 128 || allocated < bytes || allocated % 128)
                throw Error('Invalid scored cover vector');
            if (found !== (bytes > 0)) throw Error('Inconsistent scored cover result');
            const candidates = [];
            for (let i = 0; i < Math.min(bytes / 128, 8); i++) {
                const candidate = begin.add(i * 128);
                const position = [candidate.add(0x10).readFloat(), candidate.add(0x14).readFloat()];
                const components = Array.from({length: 10}, (_, j) => candidate.add(0x58 + j * 4).readFloat());
                if (![...position, ...components].every(Number.isFinite)) throw Error('Invalid scored cover data');
                const sourceId = candidate.add(0x18).readU16();
                // 0x8a75a0 writes the weighted total at +0x7c. The default
                // request calls 0x8a9670 with comparator 0x8a8a60 (descending).
                // This is a native preference, not a calibrated protection value.
                if (i && components[9] > candidates[i - 1].nativeAssessment.weightedScore)
                    throw Error('Native cover ranking is not descending');
                candidates.push({found: true, position, sourceIdentity: sourceId === 0xffff ? null : coverSourceIdentity(sourceId),
                    nativeAssessment: {typeRaw: candidate.readU32(), flagsRaw: candidate.add(0x4c).readU32() & 0x1f,
                        componentsRaw: components, weightedScore: components[9]},
                    protection: null, firingAccess: null, reachability: null});
            }
            result = {status: 'queried', generation: baseline.generation, simulationTicks: baseline.simulationTicks,
                observerIdentity: {id: row.id, incarnation: row.incarnation, owner: row.owner},
                center, radius: 60, weightsRaw: weights, candidateCount: bytes / 128, candidates,
                inputRecordCountRaw: inputRecords, hasTargetRecordRaw: !request.add(0x4c).readPointer().isNull(),
                elapsedMs: Date.now() - started, ranking: 'native-weighted-score-descending',
                interpretation: 'Native default-weight ranking; protection, firing access and reachability unverified'};
        } finally {
            coverRequestDestroy(request);
            if (![0, 4, 8].every(offset => request.add(offset).readPointer().isNull()))
                throw Error('Native cover request vector not cleared by destructor');
        }
        return {...result, requestVectorReleased: true};
    }
    if (action === 'cover_query') {
        const result = [], output = Memory.alloc(128), point = Memory.alloc(12), start = Date.now();
        const center = options.destination || row.position;
        for (const [dx, dy] of [[0, 0], [30, 0], [-30, 0], [0, 30], [0, -30]]) {
            if (Date.now() - start > 10) break;
            output.writeByteArray(new Uint8Array(128)); coverInit(output);
            point.writeFloat(center[0] + dx); point.add(4).writeFloat(center[1] + dy);
            point.add(8).writeFloat(center[2]);
            const found = coverQuery(output, actor, point, 0) !== 0;
            // Native 8aa1e0 copies the source entity's uint16 ID here.
            const sourceId = found ? output.add(0x18).readU16() : 0xffff;
            const position = found ? [output.add(16).readFloat(), output.add(20).readFloat()] : null;
            if (position && !position.every(Number.isFinite)) throw Error('Invalid native cover position');
            // 8a65f0 clears assessment weights before choosing by distance.
            // 8aa390 initializes only the low five bits of the flag word.
            // Default components must not be treated as suitability scores.
            const assessment = found ? {
                scoringEnabled: false,
                typeRaw: output.readU32(), flagsRaw: output.add(0x4c).readU32() & 0x1f,
                componentsRaw: Array.from({length: 10}, (_, i) => output.add(0x58 + i * 4).readFloat())
            } : null;
            if (assessment && !assessment.componentsRaw.every(Number.isFinite))
                throw Error('Invalid native cover assessment');
            result.push({offset: [dx, dy], found,
                position, nativeAssessment: assessment,
                nativeSourceEntityId: sourceId === 0xffff ? null : sourceId,
                sourceIdentity: sourceId === 0xffff ? null : coverSourceIdentity(sourceId),
                protection: null, firingAccess: null, reachability: null});
        }
        return {status: 'queried', center, candidates: result, elapsedMs: Date.now() - start};
    }
    if (action === 'cover') {
        const expected = options.coverSource;
        if (expected && (!options.destination || expected.generation !== matchToken() ||
            !Number.isInteger(expected.entityId) || expected.entityId < 0 || expected.entityId >= 0xffff ||
            !Number.isInteger(expected.incarnation) || expected.incarnation < 1))
            throw new Rejected('Invalid selected cover identity');
        const output = Memory.alloc(128), point = Memory.alloc(12);
        output.writeByteArray(new Uint8Array(128)); coverInit(output);
        (options.destination || row.position).forEach((v, i) => point.add(i * 4).writeFloat(v));
        if (!coverQuery(output, actor, point, 0)) throw new Rejected('No native cover near unit');
        if (expected) {
            const source = coverSourceIdentity(output.add(0x18).readU16());
            if (!source || source.generation !== expected.generation || source.entityId !== expected.entityId ||
                source.incarnation !== expected.incarnation)
                throw new Rejected('Selected cover source changed');
            if (Math.hypot(output.add(16).readFloat() - options.destination[0],
                output.add(20).readFloat() - options.destination[1]) > 1.)
                throw new Rejected('Selected cover slot changed');
        }
        options.destination = [output.add(16).readFloat(), output.add(20).readFloat(), row.position[2]];
        if (!options.destination.every(Number.isFinite)) throw Error('Invalid cover coordinates');
    }
    if (ptr('0xfc7838').readU32() !== 0) throw new Rejected('Native serialization gate closed');
    const command = Memory.alloc(0xbc), vectorBytes = followingLeader ? 8 : 4, vector = Memory.alloc(vectorBytes);
    // This is the native stack command's serialized subset. aa9b20/aaa330 copy
    // the actor ID and value synchronously; neither owns/frees this input buffer.
    command.writeByteArray(new Uint8Array(0xbc));
    command.writePointer(ptr('0xd90718'));
    command.add(4).writeU16(0x103);
    command.add(8).writePointer(ptr('0xf3b068'));
    command.add(0xc).writeU16(1);
    vector.writePointer(actor);
    if (followingLeader) vector.add(4).writePointer(actors.get(Number(followingLeader.id)));
    command.add(0x10).writePointer(vector);
    command.add(0x14).writePointer(vector.add(vectorBytes));
    command.add(0x18).writePointer(vector.add(vectorBytes));
    command.add(0x1c).writeS32(action === 'stance' ? options.stance : -1);
    command.add(0x20).writeS32(-1);
    command.add(0x24).writeU16(0xffff);
    command.add(0x27).writeU8(Number(baseline.owner));
    if (action === 'mode') {
        command.add(4).writeU16(0x105);
        command.add(0xc).writeU16(0x40);
        command.add(0x26).writeU8(options.mode);
    }
    if (action === 'attack') {
        // 7f4000 synchronously writes the type-2 target's entity ID and values.
        // The receiver registers its own entity reference in 7f3f10. This input
        // is never registered as a native object or passed to a destructor.
        command.add(4).writeU16(0x101); command.add(0xc).writeU16(0x18);
        command.add(0x28).writePointer(ptr('0xfe7eb0').readPointer());
        command.add(0x2c).writeU32(2);
        attackTarget.observedPosition.forEach((v, i) => {
            command.add(0x30 + i * 4).writeFloat(v); command.add(0x3c + i * 4).writeFloat(v);
        });
        command.add(0x4c).writePointer(actors.get(Number(attackTarget.identity.id)));
        command.add(0x94).writeU32(15); // empty target-name string, inline capacity
    }
    if (['move', 'cover', 'barricade'].includes(action)) {
        const move = ptr(action === 'barricade' ? '0xfe84b0' : action === 'cover' ? '0xfe7ed0' : '0xfe7eac').readPointer();
        if (!move.readPointer().equals(ptr(action === 'barricade' ? '0xe1b2a8' : action === 'cover' ? '0xe1a620' : '0xe1a3a0')) ||
            move.add(0x2fc).readU8() !== (action === 'barricade' ? 37 : action === 'cover' ? 5 : 3))
            throw Error('Unsupported native spatial action');
        command.add(4).writeU16(0x101);
        command.add(0xc).writeU16(0x18);
        command.add(0x1c).writeS32(-1);
        command.add(0x28).writePointer(move);
        command.add(0x2c).writeU32(1);
        options.destination.forEach((v, i) => command.add(0x30 + i * 4).writeFloat(v));
        options.destination.forEach((v, i) => command.add(0x3c + i * 4).writeFloat(v));
        // A short, nonzero line avoids the native equal-endpoint fallback to
        // the actor position. Exactly one available kit bounds this trial.
        if (action === 'barricade') buildDirection.forEach((v, i) =>
            command.add(0x3c + i * 4).writeFloat(options.destination[i] + v));
        if (action === 'cover') {
            command.add(0xc).writeU16(0x38);
            options.destination.forEach((v, i) => {
                command.add(0x98 + i * 4).writeFloat(v + (i === 2 ? 100 : 0));
                command.add(0xa4 + i * 4).writeFloat(v - (i === 2 ? 100 : 0));
            });
        }
    }
    issuing = true;
    try {
        serialize(ptr('0xf3b068'), command);
    }
    finally { issuing = false; }
    if (followingLeader) {
        const proof = {generation: matchToken(), confirmed: false, until: baseline.simulationTicks + 2000,
            members: [row, followingLeader].map(unit => ({id: Number(unit.id), incarnation: unit.incarnation,
                revision: unit.revision, address: actors.get(Number(unit.id)).toString()}))};
        for (const unit of proof.members) followedGroups.set(unit.id, proof);
    }
    return {status: 'serialized', sequence: options.sequence, baseline: row,
        completed: false, commandRevision, destination: options.destination || null, target: attackTarget, buildDirection,
        followingLeader};
}
function sensorObservation(actor, row, baseline, registryIndex=null, sampleOffset=0, targetId=null) {
    if (targetId !== null && (typeof targetId !== 'string' || !targetId)) throw new Rejected('Invalid sensor target identity');
    const sensor = actor.add(0x790).readPointer(), records = [], started = Date.now();
    const relations = new Map();
    const byAddress = registryIndex || new Map();
    if (!registryIndex)
        for (const [id, candidate] of actors) byAddress.set(candidate.toString(), {id, candidate});
    if (sensor.isNull() || !sensor.readPointer().equals(ptr('0xdf7c04')) ||
        !sensor.add(0x1c).readPointer().equals(actor)) throw Error('Unsupported infantry sensor');
    const visualUpdateTicks = sensor.add(0xb0).readU32();
    const visualAge = baseline.simulationTicks - visualUpdateTicks;
    const currentTarget = sensor.add(0x74).readPointer();
    const buckets = [];
    let totalRecords = 0;
    for (const offset of [0x28, 0x34, 0x40, 0x4c]) {
        const begin = sensor.add(offset).readPointer(), end = sensor.add(offset + 4).readPointer();
        const bytes = end.sub(begin).toInt32();
        if (bytes < 0 || bytes % 4 || totalRecords + bytes / 4 > 4096)
            throw Error('Sensor observation budget exceeded');
        buckets.push({offset, begin, bytes, start: totalRecords});
        totalRecords += bytes / 4;
    }
    const first = sampleOffset % Math.max(1, totalRecords);
    const count = Math.min(256, totalRecords);
    for (const {offset, begin, bytes, start} of buckets) {
        for (let n = 0; n < bytes; n += 4) {
            // Rotate a bounded sample. Omitted records convey no visibility,
            // and retained observations keep their original native timestamp.
            if (targetId === null && (start + n / 4 - first + totalRecords) % totalRecords >= count) continue;
            const record = begin.add(n).readPointer(), subject = record.add(8).readPointer();
            // Resolve only registry-validated infantry. Never dereference a
            // possibly stale subject or read its current world transform.
            let identity = null;
            const known = byAddress.get(subject.toString());
            // Complete owned infantry state is already in this snapshot. Avoid
            // decoding it repeatedly through every observer's sensor as well.
            // Explicit diagnostic/attack queries still inspect their records.
            if (registryIndex && known && known.candidate.add(0x774).readU8() === Number(baseline.owner)) continue;
            // Attack preflight can locate its already selected target beyond the
            // current observation page, without decoding unrelated records.
            if (targetId !== null && (!known || String(known.id) !== targetId || records.length >= 256)) continue;
            if (known) {
                const {id, candidate} = known;
                const recordOwner = String(candidate.add(0x774).readU8());
                identity = {id: String(id), incarnation: incarnations.get(id),
                    owner: recordOwner, team: baseline.playerTeams?.[recordOwner] ?? null,
                    kind: actorKinds.get(id)};
            }
            // Copy the validated fixed-size record once. Decoding local bytes
            // avoids a native memory crossing for each scalar field.
            const data = new DataView(record.readByteArray(0x48));
            const flags = data.getUint32(0, true), position = [0x10, 0x14, 0x18].map(o => data.getFloat32(o, true));
            if (!position.every(Number.isFinite)) throw Error('Invalid sensor position');
            const relationFlags = data.getUint32(4, true);
            let relation = null;
            if (identity) {
                if (!relations.has(identity.owner))
                    relations.set(identity.owner, ownerRelation(Number(baseline.owner), Number(identity.owner)));
                relation = relations.get(identity.owner);
            }
            // Match 88d630 -> 9c9330: the record chooses perceived versus
            // actual ownership. Do not bypass perceived local ownership.
            const sensorRelation = !known || !(known.candidate.add(0x780).readU32() & 0x100) ? null :
                (!(relationFlags & 0x20) && known.candidate.add(0x778).readU8() === Number(baseline.owner)
                    ? 2 : relation);
            const visualResult = !!(flags & 0x20000000), visualLatch = !!(relationFlags & 0x40);
            const positionTicks = data.getUint32(0x44, true);
            let visible = null;
            if (known && visualUpdateTicks > 0 && visualAge >= 0 && visualAge <= 2000) {
                if (!visualResult && !visualLatch) visible = false;
                else if (visualResult && visualLatch && (flags & 0x10000000) && positionTicks === visualUpdateTicks)
                    visible = true;
            }
            if (visible === true && known.observedDead === undefined) known.observedDead = nativeDead(known.candidate);
            records.push({bucket: offset, identity, flags, relationFlags,
                nativeOwnerRelation: relation, nativeSensorRelation: sensorRelation,
                nativeVisualResult: visualResult,
                nativeVisualLatch: visualLatch,
                nativeDeadPredicate: visible === true ? known.observedDead : null,
                currentTargetRecord: currentTarget.equals(record),
                recordedPosition: flags & 0x10000000 ? position : null,
                positionUpdateTicks: positionTicks,
                visualTransitionTicks: data.getUint32(0x40, true),
                visualObservedPosition: visible === true ? position : null,
                visualObservedAtTicks: visible === true ? visualUpdateTicks : null,
                visible, enemy: sensorRelation === 1 ? true : sensorRelation === 2 ? false : null,
                confirmedDead: null});
        }
    }
    return {status: 'queried', generation: baseline.generation,
        simulationTicks: baseline.simulationTicks, observerPosition: row.position,
        observerIdentity: {id: row.id, incarnation: row.incarnation, owner: row.owner},
        visualUpdateTicks,
        records, nextSampleOffset: (first + count) % Math.max(1, totalRecords),
        totalRecords, elapsedMs: Date.now() - started,
        interpretation: 'Visibility requires a recent completed native pass; unmatched position updates remain raw'};
}
function event(kind, detail) {
    if (events.length >= 2048) { fault = 'Event overflow; observation continuity lost'; return; }
    events.push({key: ++eventSequence, kind, ...detail});
}
function clearMatch(world) {
    generation++; lastWorld = world; actors.clear(); actorKinds.clear(); incarnations.clear(); enrollment.clear(); events = [];
    coverSources.clear();
    followedGroups.clear();
    perceptionCache.clear(); sensorSampleOffsets.clear(); perceptionCursor = 0;
    ignoredUnownedCommands = 0; installationCalls = 0;
}
function coverSourceIdentity(id) {
    // Bounded equivalent of native entity-ID lookup 9dc2b0. Never dereference
    // a previously saved source pointer before resolving the current registry.
    const head = ptr('0xfe3ff4').readPointer();
    if (head.isNull()) throw Error('Entity registry unavailable');
    let node = head.add(4).readPointer(), entity = ptr(0), steps = 0;
    const seen = new Set();
    while (!node.equals(head)) {
        if (node.isNull() || seen.has(node.toString()) || ++steps > 64)
            throw Error('Invalid entity registry path');
        seen.add(node.toString());
        if (node.add(13).readU8()) break;
        const key = node.add(16).readU16();
        if (key === id) { entity = node.add(20).readPointer(); break; }
        node = node.add(id < key ? 0 : 8).readPointer();
    }
    let source = coverSources.get(id);
    if (entity.isNull()) {
        if (source && source.address !== null) { source.address = null; source.incarnation++; }
        return null;
    }
    if (entity.add(0x54).readU16() !== id || !(entity.add(0x18).readU8() & 1))
        throw Error('Cover source registry identity mismatch');
    if (!source) {
        // Urban matches discover many different walls over time. Preserve
        // tracked incarnations; saturation makes new candidates unavailable,
        // never aliases an old source or stops unrelated unit control.
        if (coverSources.size >= 4096) return null;
        source = {address: entity.toString(), incarnation: 1}; coverSources.set(id, source);
    } else if (source.address !== entity.toString()) {
        if (source.address !== null) source.incarnation++;
        source.address = entity.toString();
    }
    return {generation: matchToken(), entityId: id, incarnation: source.incarnation};
}
function stringAt(address) {
    const size = address.add(16).readU32(), capacity = address.add(20).readU32();
    if (size > capacity || size > 128) throw Error('Invalid native string');
    if (!size) return '';
    return (capacity > 15 ? address.readPointer() : address).readUtf8String(size);
}
function mapObjectives(owner) {
    const manager = ptr('0xfed0c4').readPointer();
    let team = null;
    const playerTeams = {};
    if (!manager.isNull()) {
        const begin = manager.add(0x68).readPointer(), end = manager.add(0x6c).readPointer();
        const length = end.sub(begin).toInt32();
        if (length < 0 || length % 4 || length > 64 * 4) throw Error('Invalid match player vector');
        for (let offset = 0; offset < length; offset += 4) {
            const player = begin.add(offset).readPointer();
            const id = player.add(4).readU8();
            if (Object.hasOwn(playerTeams, String(id))) throw Error('Ambiguous match player');
            playerTeams[String(id)] = stringAt(player.add(0x4c));
            if (id === owner) team = playerTeams[String(id)];
        }
    }
    const begin = ptr('0xf396fc').readPointer(), end = ptr('0xf39700').readPointer();
    const length = end.sub(begin).toInt32(), objectives = [];
    if (length < 0 || length % 4 || length > 128 * 4) throw Error('Invalid map point vector');
    for (let offset = 0; offset < length; offset += 4) {
        const component = begin.add(offset).readPointer();
        if (!component.readPointer().equals(ptr('0xdf1c64'))) throw Error('Unknown map point component');
        const engine = component.add(0x79c).readPointer();
        // Exact CaptureEngine subtype; spawn points have no capture engine.
        if (engine.isNull() || !engine.readPointer().equals(ptr('0xe3093c'))) continue;
        if (!engine.add(4).readPointer().equals(component)) throw Error('Map point backpointer mismatch');
        const actor = component.add(0x10).readPointer();
        if (actor.add(0x1c).readU32() & 0x200) continue;
        const position = [0x44, 0x48, 0x4c].map(o => actor.add(o).readFloat());
        if (!position.every(Number.isFinite)) throw Error('Invalid objective position');
        // bca5c0 uses per-team squared 3D radii and excludes the exact boundary.
        // Expose only the common zone; differing team zones remain unknown.
        const radiusSquared = engine.add(0x12c).readS32(), otherRadius = engine.add(0x138).readS32();
        if (radiusSquared < 0 || otherRadius < 0) throw Error('Invalid capture radius');
        const captureRadius = radiusSquared > 0 && radiusSquared === otherRadius &&
            engine.add(0x130).readPointer().equals(component) &&
            engine.add(0x13c).readPointer().equals(component) ? Math.sqrt(radiusSquared) : null;
        objectives.push({key: stringAt(component.add(0x88)), position,
            occupant: stringAt(engine.add(0x40)), captureRadius, reachable: null});
    }
    const managerStateRaw = !manager.isNull() && manager.readPointer().equals(ptr('0xe317f0')) ?
        manager.add(0xc).readU32() : null;
    const playing = managerStateRaw === 1;
    return {team, playerTeams, objectives, playing, managerStateRaw};
}
function nativeDead(actor) {
    // Native property "dead": factory 0x7d1c30 -> vtable 0xdefd5c,
    // predicate 0x7cf8b0. Eligibility also checks bit 4, which is distinct.
    const health = actor.add(0x32c).readPointer().add(0xc).readPointer();
    return !health.isNull() && !!(health.add(0xf8).readU8() & 1);
}
function ownerRelation(observer, subject) {
    // Native 9c9560, called by sensor relation check 9c9330 with ECX fe37e0.
    // The table is a flat vector plus row stride, not a fixed 18x18 array.
    if (observer === subject) return 2;
    if (![observer, subject].every(id => Number.isInteger(id) && id >= 0 && id < 18)) return null;
    const table = ptr('0xfe37e0'), begin = table.readPointer(), end = table.add(4).readPointer();
    const bytes = end.sub(begin).toInt32(), stride = table.add(8).readU32();
    if (bytes === 0 && stride === 0) return null;
    if (bytes < 0 || bytes > 18 * 18 * 4 || bytes % 4 || stride < 1 || stride > 18 ||
        bytes % (stride * 4) || (bytes && begin.isNull())) throw Error('Invalid native relation table');
    if (observer >= stride || subject >= bytes / (stride * 4)) return null;
    return begin.add((stride * subject + observer) * 4).readU32();
}
function controllerFollowGroup(id, squad, owner, simTicks) {
    const proof = followedGroups.get(id);
    if (!proof) return false;
    let valid = proof.generation === matchToken() && !squad.isNull();
    const begin = valid ? squad.add(0x58).readPointer() : ptr(0);
    valid = valid && squad.add(0x5c).readPointer().sub(begin).toInt32() === 8;
    if (valid) {
        const members = [begin.readPointer(), begin.add(4).readPointer()];
        valid = proof.members.every(expected => {
            // Resolve from the current native group, never dereference a saved
            // actor address. Both participants must retain their exact identity
            // and command revision; a takeover of either ends this exception.
            const actor = members.find(p => !p.isNull() && p.toString() === expected.address &&
                p.add(0x776).readU16() === expected.id);
            const state = enrollment.get(expected.id);
            if (!actor || actor.add(0x774).readU8() !== owner || !state ||
                incarnations.get(expected.id) !== expected.incarnation || state.revision !== expected.revision)
                return false;
            const brain = actor.add(0x78c).readPointer();
            return !brain.isNull() && brain.readPointer().equals(ptr('0xdfbed0')) &&
                brain.add(0x20).readPointer().equals(actor) && brain.add(0x8c).readPointer().equals(squad) &&
                (brain.add(0x210).readU32() & 0x3000) === 0x2000 && (brain.add(0x214).readU32() & 0x3f) === 0;
        });
    }
    if (valid) proof.confirmed = true;
    else if (proof.confirmed || simTicks > proof.until) {
        for (const unit of proof.members)
            if (followedGroups.get(unit.id) === proof) followedGroups.delete(unit.id);
    }
    return valid;
}
function inspect(includePerception = false, includeAmmunition = true, onlyUnit = null) {
    const observationStarted = Date.now();
    const world = ptr('0xfe17d4').readPointer();
    const simTicks = ptr('0xfbb000').readU32();
    if (world.toString() !== lastWorld || simTicks < lastTime) clearMatch(world.toString());
    lastTime = simTicks;
    const owner = ptr('0xf39e64').readU8();
    const rows = [], current = new Map(), currentKinds = new Map(), squads = new Map(), owned = new Set();
    const singleActorSquads = new Map();
    // Definitions are shared by many soldiers. Cache only within this locked
    // inspection; a new snapshot and every command query read fresh identities.
    const modelCache = new Map();
    if (!world.isNull()) {
        if (!world.readPointer().equals(ptr('0xe05fe8'))) throw Error('Unsupported world object');
        const head = world.add(0x30).readPointer(), count = world.add(0x34).readU32();
        if (count > 4096 || head.isNull()) throw Error('Actor registry exceeds bound');
        const stack = [head.add(4).readPointer()], seen = new Set();
        while (stack.length) {
            const node = stack.pop();
            if (node.equals(head)) continue;
            if (node.isNull() || seen.has(node.toString()) || seen.size >= count)
                throw Error('Invalid actor registry');
            seen.add(node.toString());
            if (node.add(13).readU8() !== 0) throw Error('Unexpected registry sentinel');
            stack.push(node.readPointer(), node.add(8).readPointer());
            const actor = node.add(20).readPointer(), id = node.add(16).readU16();
            if (actor.isNull() || actor.add(0x776).readU16() !== id)
                throw Error('Actor registry identity mismatch');
            const brain = actor.add(0x78c).readPointer();
            if (brain.isNull()) continue;
            const brainType = brain.readPointer();
            const human = brainType.equals(ptr('0xdfbed0'));
            // eVehicleBrain shares the mapped eBrain owner binding. Keep its
            // identity for native sensor observations, never for unit control.
            if (!human && !brainType.equals(ptr('0xe00344'))) continue;
            if (!brain.add(0x20).readPointer().equals(actor)) throw Error('Brain owner mismatch');
            const previous = actors.get(id);
            if (!previous || !previous.equals(actor) || actorKinds.get(id) !== (human ? 'infantry' : 'vehicle'))
                incarnations.set(id, (incarnations.get(id) || 0) + 1);
            current.set(id, actor);
            currentKinds.set(id, human ? 'infantry' : 'vehicle');
            const unitOwner = actor.add(0x774).readU8();
            // Retain foreign identity for perception validation, without reading
            // an unseen actor's transform or requiring its chassis subtype.
            if (unitOwner !== owner || !human) continue;
            owned.add(id);
            if (owned.size > MAX_OWNED_UNITS) throw Error('Infantry limit exceeded');
            // Registry identity and ownership are still refreshed for everyone.
            // Only the addressed unit needs detailed command preflight; the next
            // scheduled snapshot observes the rest of the army in full.
            if (onlyUnit !== null && !(Array.isArray(onlyUnit) ? onlyUnit.includes(String(id)) : String(id) === onlyUnit)) continue;
            const position = [0x44, 0x48, 0x4c].map(o => actor.add(o).readFloat());
            if (!position.every(Number.isFinite)) throw Error('Invalid actor position');
            const chassis = actor.add(0x798).readPointer();
            if (chassis.isNull() || !chassis.readPointer().equals(ptr('0xdf6990')))
                throw Error('Unsupported infantry chassis');
            const cover = actor.add(0x788).readPointer();
            if (cover.isNull() || !cover.readPointer().equals(ptr('0xdf8380')))
                throw Error('Unsupported infantry cover component');
            if (rows.length >= MAX_OWNED_UNITS) throw Error('Infantry limit exceeded');
            const squad = brain.add(0x8c).readPointer();
            // Shared only within this locked inspection: membership/ownership is
            // read afresh on the next command or snapshot, never cached across ticks.
            const squadKey = squad.toString();
            let squadMembers = squads.get(squadKey) || [];
            if (!squad.isNull() && !squads.has(squadKey)) {
                const begin = squad.add(0x58).readPointer(), end = squad.add(0x5c).readPointer();
                const bytes = end.sub(begin).toInt32();
                if (bytes < 0 || bytes % 4 || bytes > 128 * 4) throw Error('Invalid infantry squad');
                if (bytes === 4) singleActorSquads.set(squadKey, begin.readPointer().toString());
                for (let offset = 0; offset < bytes; offset += 4) {
                    const soldier = begin.add(offset).readPointer();
                    if (soldier.add(0x774).readU8() === owner) squadMembers.push(String(soldier.add(0x776).readU16()));
                }
                squads.set(squadKey, squadMembers);
            }
            const dead = nativeDead(actor), isEligible = eligible(actor);
            let member = enrollment.get(id);
            if (!member || member.incarnation !== incarnations.get(id)) {
                member = {incarnation: incarnations.get(id), revision: 0, deathObserved: dead,
                    observedEligible: isEligible,
                    enrolled: isEligible && (brain.add(0x210).readU32() & 0x3000) === 0 &&
                        (brain.add(0x214).readU32() & 0x3f) === 0};
                enrollment.set(id, member);
            }
            if (dead && !member.deathObserved) {
                member.deathObserved = true;
                if (member.observedEligible) event('owned_death', {id: String(id), incarnation: member.incarnation,
                    position, simulationTicks: simTicks});
            }
            member.observedEligible ||= isEligible;
            const controllerGroup = controllerFollowGroup(id, squad, owner, simTicks);
            if (member.enrolled && (!isEligible || ((brain.add(0x210).readU32() & 0x3000) !== 0 && !controllerGroup) ||
                (brain.add(0x214).readU32() & 0x3f) !== 0)) {
                member.enrolled = false; member.revision++;
            }
            rows.push({id: String(id), incarnation: incarnations.get(id), owner: String(unitOwner),
                enrolled: member.enrolled, revision: member.revision,
                controllerGroup,
                squadMembers,
                entityId: actor.add(0x54).readU16(), position,
                eligible: isEligible, squadLeader: !squad.isNull() && squad.add(0x70).readPointer().equals(actor),
                individualOrder: squad.isNull() || !squad.add(0x70).readPointer().equals(actor) ||
                    singleActorSquads.get(squadKey) === actor.toString(),
                coverState: cover.add(0x1c).readU32(),
                movementBits: brain.add(0x210).readU32() & 0x3000,
                controlLockRaw: brain.add(0x214).readU32() & 0x3f,
                nativeDeadPredicate: dead,
                stance: chassis.add(0x20).readU32(), alive: null,
                health: null, suppression: null, readiness: null,
                ammunition: includeAmmunition && caps.ammoLoading && isEligible && member.enrolled
                    ? weaponObservation(actor, null, {simulationTicks: simTicks}, true, modelCache) : null});
        }
        if (seen.size !== count) throw Error('Actor registry count mismatch');
    }
    actors = current;
    actorKinds = currentKinds;
    for (const id of enrollment.keys()) if (!owned.has(id)) {
        enrollment.delete(id); incarnations.set(id, (incarnations.get(id) || 0) + 1);
    }
    for (const id of followedGroups.keys()) if (!owned.has(id)) followedGroups.delete(id);
    const map = world.isNull() ? {team: null, playerTeams: {}, objectives: [], playing: false} : mapObjectives(owner);
    const selectedOwnedIds = [];
    const control = ptr('0xfe6384').readPointer();
    if (!control.isNull()) {
        if (!control.readPointer().equals(ptr('0xe12468'))) throw Error('Unknown game control');
        const selection = control.add(0x58).readPointer();
        if (!selection.readPointer().equals(ptr('0xe125b8'))) throw Error('Unknown selection');
        const begin = selection.add(4).readPointer(), end = selection.add(8).readPointer();
        const bytes = end.sub(begin).toInt32();
        if (bytes < 0 || bytes % 8 || bytes > MAX_OWNED_UNITS * 8) throw Error('Invalid selection');
        for (let offset = 0; offset < bytes; offset += 8) {
            const actor = begin.add(offset).readPointer();
            if (!actor.isNull() && actor.add(0x774).readU8() === owner)
                selectedOwnedIds.push(String(actor.add(0x776).readU16()));
        }
    }
    const result = {ticks, generation: matchToken(), simulationTicks: simTicks,
        paused: ptr('0xfbaffc').readU32() !== 0, owner: String(owner), commandRevision,
        ignoredUnownedCommands, ...map,
        selectedOwnedIds,
        units: rows, events, capabilities: caps, fault,
        limitations: ['Identity lifecycle requires further live trials',
            'Death, contacts, objectives, weapon readiness and command replication unverified']};
    result.perception = includePerception && caps.contacts === true ? collectPerception(rows, result) : [];
    result.perceptionEncoding = 'tuple-v1';
    result.observationMs = Date.now() - observationStarted;
    events = [];
    return result;
}
function collectPerception(rows, baseline) {
    // Individually commanded soldiers can be far from their squad leader.
    // A leader's sensor cannot stand in for each member's local perception.
    const observers = rows.filter(row => row.eligible && row.enrolled &&
        (row.movementBits === 0 || row.controllerGroup) && !row.controlLockRaw && row.individualOrder)
        .sort((a, b) => Number(a.id) - Number(b.id));
    const live = new Set(observers.map(row => row.id + ':' + row.incarnation));
    for (const key of sensorSampleOffsets.keys()) if (!live.has(key)) sensorSampleOffsets.delete(key);
    for (const [key, report] of perceptionCache)
        if (!live.has(key) || baseline.simulationTicks - report.simulationTicks > 2000) perceptionCache.delete(key);
    // Service up to 256 observers over eight snapshots, with at most 32
    // sensor reads per snapshot. Larger armies remain fair but can lose stale
    // reports; never extend visibility validity to disguise a slow refresh.
    const budget = Math.min(observers.length, Math.max(4, Math.min(32, Math.ceil(observers.length / 8))));
    const registryIndex = new Map();
    for (const [id, candidate] of actors) registryIndex.set(candidate.toString(), {id, candidate});
    let recordCount = [...perceptionCache.values()].reduce((sum, report) => sum + report.records.length, 0);
    for (let n = 0; n < budget; n++) {
        const row = observers[perceptionCursor++ % observers.length];
        const key = row.id + ':' + row.incarnation;
        const report = sensorObservation(actors.get(Number(row.id)), row, baseline, registryIndex,
            sensorSampleOffsets.get(key) || 0);
        sensorSampleOffsets.set(key, report.nextSampleOffset);
        recordCount -= perceptionCache.get(key)?.records.length || 0;
        perceptionCache.delete(key); perceptionCache.set(key, report);
        recordCount += report.records.length;
        while (perceptionCache.size > 128 || recordCount > 4096) {
            const oldest = perceptionCache.keys().next().value;
            recordCount -= perceptionCache.get(oldest).records.length;
            perceptionCache.delete(oldest);
        }
    }
    perceptionCursor %= Math.max(1, observers.length);
    return [...perceptionCache.values()].map(report => ({...report, records: report.records.filter(record => {
        const identity = record.identity;
        if (!identity) return false;
        const actor = actors.get(Number(identity.id));
        return actor && incarnations.get(Number(identity.id)) === identity.incarnation &&
            String(actor.add(0x774).readU8()) === identity.owner && actorKinds.get(Number(identity.id)) === identity.kind;
    }).map(record => {
        // Keep every admission/visibility field consumed by NativeAdapter and
        // unseen identities needed to invalidate reuse. Debug-only sensor fields
        // remain available through sensor_query, outside the army snapshot loop.
        const {identity, visible, enemy, nativeDeadPredicate, nativeOwnerRelation,
            visualObservedPosition, visualObservedAtTicks, positionUpdateTicks} = record;
        return [identity, visible, enemy, nativeDeadPredicate, nativeOwnerRelation,
            visualObservedPosition, visualObservedAtTicks, positionUpdateTicks];
    })}));
}
// Observe installation only through its verified entity-creation call site.
hooks.push(Interceptor.attach(ptr('0x794120'), {
    onEnter() {
        this.installOwner = null;
        if (!this.returnAddress.equals(ptr('0xa9cc7d'))) return;
        installationCalls = Math.min(installationCalls + 1, 1000000);
        try {
            // At this exact call site EBP is the verified install-instruction frame.
            const frame = this.context.ebp, actor = frame.add(0x10).readPointer();
            const instruction = frame.sub(4).readPointer();
            if (actor.isNull() || actor.add(0x774).readU8() !== ptr('0xf39e64').readU8() ||
                instruction.isNull() || !instruction.readPointer().equals(ptr('0xe1a1dc'))) return;
            const id = actor.add(0x776).readU16(), current = actors.get(id);
            if (!current || !current.equals(actor)) return;
            // The original target argument is reused by this point. These are
            // the three locals passed to the verified placement setter 7941d0.
            const preparedPosition = [-0x10, -0xc, -8].map(o => frame.add(o).readFloat());
            if (!preparedPosition.every(Number.isFinite)) throw Error('Invalid installation position');
            this.installOwner = {id, actor, incarnation: incarnations.get(id), generation: matchToken(),
                requestedEntity: stringAt(instruction.add(8)), preparedPosition};
        } catch (error) { fault = String(error); }
    },
    onLeave(result) {
        const owner = this.installOwner;
        if (!owner || result.isNull() || owner.generation !== matchToken() ||
            owner.incarnation !== incarnations.get(owner.id)) return;
        const current = actors.get(owner.id);
        if (!current || !current.equals(owner.actor)) return;
        try {
            event('install_entity_created', {id: String(owner.id), incarnation: owner.incarnation,
                requestedEntity: owner.requestedEntity, preparedPosition: owner.preparedPosition,
                createdEntityId: result.add(0x54).readU16(), simulationTicks: ptr('0xfbb000').readU32(),
                usableDefense: null});
        } catch (error) { fault = String(error); }
    }
}));
// Attribute bullets using current registry identity, never a saved actor pointer.
hooks.push(Interceptor.attach(ptr('0x85cc30'), {
    onEnter(args) {
        this.bulletOwner = null;
        if (!this.returnAddress.equals(ptr('0x84de9f'))) return;
        try {
            const actor = args[0];
            if (actor.isNull() || actor.add(0x774).readU8() !== ptr('0xf39e64').readU8()) return;
            const id = actor.add(0x776).readU16(), current = actors.get(id);
            if (current && current.equals(actor)) this.bulletOwner = {
                id, actor, incarnation: incarnations.get(id), generation: matchToken()};
        } catch (error) { fault = String(error); }
    },
    onLeave(result) {
        const owner = this.bulletOwner;
        if (!owner || result.isNull() || owner.generation !== matchToken() ||
            owner.incarnation !== incarnations.get(owner.id)) return;
        const current = actors.get(owner.id);
        if (!current || !current.equals(owner.actor)) return;
        event('bullet_created', {id: String(owner.id), incarnation: owner.incarnation,
            simulationTicks: ptr('0xfbb000').readU32()});
    }
}));
hooks.push(Interceptor.attach(ptr('0x9dacb0'), {
    onEnter(args) {
        try {
            const actor = args[0], id = actor.add(0x776).readU16();
            // Invalidate at entry, before removal or any possible ID reuse.
            actors.delete(id);
            enrollment.delete(id);
            incarnations.set(id, (incarnations.get(id) || 0) + 1);
            event('registry_change', {id: String(id), registering: (args[1].toUInt32() & 255) !== 0});
        } catch (error) { fault = String(error); }
    }
}));
hooks.push(Interceptor.attach(ptr('0x830f90'), {
    onEnter(args) {
        try {
            const actor = this.context.ecx, id = actor.add(0x776).readU16(), current = actors.get(id);
            if (!current || !current.equals(actor)) return;
            const before = actor.add(0x774).readU8(), after = args[0].toUInt32() & 255;
            if (before === after) return;
            // A transfer away and back can occur between snapshots. Invalidate
            // before native callbacks, including any reentrant command dispatch.
            actors.delete(id); enrollment.delete(id);
            incarnations.set(id, (incarnations.get(id) || 0) + 1);
            event('ownership_change', {id: String(id), previousOwner: String(before), owner: String(after)});
        } catch (error) { fault = String(error); }
    }
}));
hooks.push(Interceptor.attach(ptr('0x9dc350'), {
    onEnter(args) {
        if (!coverSources.size) return;
        try {
            const entity = args[0];
            if (entity.isNull()) return;
            const id = entity.add(0x54).readU16(), source = coverSources.get(id);
            if (!source || source.address !== entity.toString()) return;
            const previous = source.incarnation;
            source.address = null; source.incarnation++;
            event('cover_source_invalidated', {entityId: id, incarnation: previous,
                reason: 'native_registration_change', destroyed: null});
        } catch (error) { fault = String(error); }
    }
}));
hooks.push(Interceptor.attach(ptr('0xaaa1a0'), {
    onEnter() {
        if (issuing) return;
        try {
            const command = this.context.ecx, type = command.add(4).readU8();
            const begin = command.add(0x10).readPointer(), end = command.add(0x14).readPointer();
            const size = end.sub(begin).toInt32(), addressed = [];
            if (size < 0 || size % 4 || size > MAX_OWNED_UNITS * 4) throw Error('Invalid player command vector');
            for (let offset = 0; offset < size; offset += 4) addressed.push(begin.add(offset).readPointer());
            // Native stance/mode handlers expand a sole leader to squad members.
            if (addressed.length === 1 && [3, 5, 6].includes(type)) {
                const brain = addressed[0].add(0x78c).readPointer(), squad = brain.add(0x8c).readPointer();
                if (!squad.isNull() && squad.add(0x70).readPointer().equals(addressed[0])) {
                    const first = squad.add(0x58).readPointer(), last = squad.add(0x5c).readPointer();
                    const bytes = last.sub(first).toInt32();
                    if (bytes < 0 || bytes % 4 || bytes > 128 * 4) throw Error('Invalid squad command scope');
                    addressed.length = 0;
                    for (let offset = 0; offset < bytes; offset += 4) addressed.push(first.add(offset).readPointer());
                }
            }
            const ids = [], previouslySuspendedIds = [];
            for (const actor of addressed) {
                if (actor.add(0x774).readU8() !== ptr('0xf39e64').readU8()) continue;
                const id = actor.add(0x776).readU16(), member = enrollment.get(id);
                ids.push(String(id));
                if (member && [1, 5].includes(type)) {
                    if (type === 5 && !member.enrolled) previouslySuspendedIds.push(String(id));
                    member.revision++;
                    member.enrolled = type === 5 && command.add(0x26).readU8() === 0;
                }
            }
            // This native emission path is also used for other owners' orders.
            // They cannot reclaim local infantry or invalidate local revisions.
            if (ids.length) {
                commandRevision++;
                event('player_command', {type, ids, mode: type === 5 ? command.add(0x26).readU8() : null,
                    flags: command.add(0xc).readU16(),
                    caller: this.returnAddress ? this.returnAddress.toString() : null,
                    previouslySuspendedIds});
            } else {
                ignoredUnownedCommands = Math.min(Number.MAX_SAFE_INTEGER, ignoredUnownedCommands + 1);
            }
        } catch (error) { fault = String(error); }
    }
}));
hooks.push(Interceptor.attach(ptr('0xaaa6f0'), {
    onEnter(args) {
        const command = args[0];
        event('stance_execution', {stance: command.add(0x1c).readS32(), owner: command.add(0x27).readU8()});
    }
}));
hooks.push(Interceptor.attach(ptr('0x8e8c80'), {
    onEnter(args) {
        try {
            const actor = this.context.ecx.add(0x20).readPointer();
            if (actor.add(0x774).readU8() === ptr('0xf39e64').readU8())
                event('mode_setter', {id: String(actor.add(0x776).readU16()), mode: args[0].toUInt32(),
                    caller: this.returnAddress ? this.returnAddress.toString() : null});
        } catch (e) { fault = String(e); }
    }
}));
// Both exact executor call sites run under its native lock. Normal work follows
// quant dispatch; paused observations use the final dispatcher because paused
// execution skips quant entirely. Trial admission rejects every paused action.
function dispatchPending() {
    if (stopped || !pending) return;
    const job = pending; pending = null;
    if (Date.now() > job.deadline) {
        job.resolve({error: 'Snapshot expired', rejected: !!job.options, unexecuted: true}); return;
    }
    try { job.resolve(job.options ? trial(job.options) : inspect(ptr('0xfbaffc').readU32() === 0)); }
    catch (e) {
        if (!(e instanceof Rejected)) fault = String(e);
        job.resolve({error: String(e), rejected: e instanceof Rejected, observedEvents: e.observedEvents || []});
    }
}
hooks.push(Interceptor.attach(ptr('0x715c60'), {
    onEnter() { this.main = this.returnAddress.equals(ptr('0x6654d7')) && this.context.ecx.equals(ptr('0xfbafdc')); },
    onLeave() {
        if (!this.main || stopped) return;
        ticks++;
        dispatchPending();
    }
}));
hooks.push(Interceptor.attach(ptr('0x715b60'), {
    onEnter() {
        if (this.returnAddress.equals(ptr('0x665556')) && this.context.ecx.equals(ptr('0xfbafdc')) &&
            ptr('0xfbaffc').readU32() !== 0) dispatchPending();
    }
}));
const watchdog = setInterval(() => {
    if (pending && Date.now() > pending.deadline) {
        const job = pending; pending = null;
        job.resolve({error: 'Game callback timeout', rejected: !!job.options, unexecuted: true});
    }
    if (Date.now() - lastPoll > 5000 && events.length) {
        fault ||= 'Observation event continuity lost after polling lapse';
        events = [];
    }
}, 100);
rpc.exports = {
    identity() { return {executable: gameModule.path, base: gameModule.base.toString(),
        size: gameModule.size, architecture: Process.arch, checkedSites: sites, activeMods: null}; },
    capabilities() { return caps; },
    snapshot() {
        if (stopped) throw Error('Bridge stopped');
        if (pending) throw Error('Snapshot already pending');
        lastPoll = Date.now();
        return new Promise(resolve => { pending = {resolve, deadline: Date.now() + 2000}; });
    },
    submit(options) {
        if (!['identityLifecycle', 'simulationClock', 'death', 'commandAuthority', 'synchronization']
            .every(key => caps[key] === true)) throw Error('Native command validation gates have not passed');
        if (!options || !['move', 'stance', 'attack'].includes(options.action) || caps[options.action] !== true ||
            (options.action === 'attack' && caps.contacts !== true) ||
            options.requireEnrolled !== true || !Number.isFinite(options.submitBeforeTicks))
            throw Error('Unsupported or incomplete native submission');
        return rpc.exports.trialstance(options);
    },
    trialstance(options) {
        if (stopped || pending || fault) throw Error('Bridge unavailable');
        lastPoll = Date.now();
        return new Promise(resolve => { pending = {resolve, options, deadline: Date.now() + 2000}; });
    },
    stop() {
        stopped = true;
        if (pending) { pending.resolve({error: 'Stopped'}); pending = null; }
        clearInterval(watchdog);
        for (const hook of hooks) hook.detach();
        actors.clear(); actorKinds.clear(); enrollment.clear(); coverSources.clear(); perceptionCache.clear(); sensorSampleOffsets.clear(); events = [];
        return {stopped: true, propertiesModified: false};
    }
};
