"""Bounded native tactical trials; writes raw evidence and an honest gate report."""
import _bootstrap
import argparse
from datetime import datetime, timezone
import json
import hashlib
import subprocess
import sys
from pathlib import Path
import time
import ctypes
from ctypes import wintypes
from dataclasses import asdict
from math import dist, sin, cos, pi

from tactical_controller import Evidence, ROOT, Runtime, NativeAdapter, NativeCalls, native_call, source_hashes, executable_identity
from tactical_map import Image, Reader
from tactical_policy import Contact, Identity, Objective, Policy, Snapshot, Unit
from tactical_operations import ForcePlanner, TacticalMetrics
from tactical_sync import SyncLogMonitor

ATTACK_TRIAL_RANGE = 1000.  # Scene bound, not a claim about a weapon's native range.


def diagnostic_memory_check(pid, evidence):
    """Avoid injecting into an already exhausted x86 address space."""
    from memory_diagnostics import Diagnostics
    reader = Reader(pid)
    try:
        sample = {}
        Diagnostics(reader.handle,pid,evidence.path).observe(sample,{'phase':'before_tactical_attach'})
        headroom = sample['address_space']
        # The observed Frida fault had 42 MiB total and only a 3.4 MiB region.
        # This conservative admission floor is not a memory-stability guarantee.
        if headroom['free_bytes'] < 128*1024*1024 or headroom['largest_free_region'] < 8*1024*1024:
            raise RuntimeError('Insufficient x86 address-space headroom for tactical injection: '+json.dumps(headroom))
        return headroom
    finally:
        reader.close()


def timing_metrics(samples):
    """External simulation progress, not render FPS; include sampler scheduling gaps."""
    from statistics import median
    if len(samples) < 2:
        raise ValueError('Insufficient timing samples')
    gaps, changed, last_change = [], [], samples[0][0]
    for previous, current in zip(samples, samples[1:]):
        if current[0] <= previous[0] or current[1] < previous[1] or current[2] or current[3] != samples[0][3]:
            raise ValueError('Timing scene paused, reset, or sampler clock invalid')
        gaps.append((current[0]-previous[0])*1000.)
        if current[1] != previous[1]:
            changed.append((current[0]-last_change)*1000.)
            last_change = current[0]
    if not changed or not samples[0][3] or samples[0][2]:
        raise ValueError('No active simulation progress')
    def spread(values):
        ordered = sorted(values)
        return dict(count=len(values), median=median(values), p95=ordered[int((len(values)-1)*.95)], max=max(values))
    return dict(simulationToWallRatio=(samples[-1][1]-samples[0][1])/1000./(samples[-1][0]-samples[0][0]),
                simulationProgressGapMs=spread(changed), samplerGapMs=spread(gaps),
                trailingNoProgressMs=(samples[-1][0]-last_change)*1000.)


def performance_trial(pid, output, baseline_bridge=None, seconds=8.):
    """Counterbalanced observation profiles; no native orders or resource changes."""
    import frida
    import re
    import struct
    import threading
    from headless_host import process_identity, SUPPORTED_SHA256
    identity = process_identity(pid)
    if identity['sha256'] != SUPPORTED_SHA256:
        raise RuntimeError('Unsupported profiling executable')
    current = (ROOT / 'headless/tactical_bridge.js').read_text()
    sources = {'current': current}
    if baseline_bridge is not None:
        sources['previous'] = baseline_bridge.read_text()
    order = ['uninstrumented', *sources]
    evidence = Evidence(output, limit=32*1024*1024)
    summary = dict(scenario='native_observation_performance', result='failed', executableIdentity=identity,
        ordersIssued=0, phases=[], configuration=dict(phaseSeconds=seconds, phaseOrder=order+order[::-1],
        sampleSeconds=.005, snapshotSeconds=.5, snapshotSchedule='absolute; missed slots skipped'), sourceHashes={k:hashlib.sha256(v.encode()).hexdigest() for k,v in sources.items()},
        limitation='Successive combat windows, not identical scenes; simulation timing is not render FPS')
    reader = Reader(pid)
    sites = dict(re.findall(r"'(0x[0-9a-f]+)': '([0-9a-f]+)'", current))
    def restored():
        return all(reader.read(int(address,16),len(value)//2)==bytes.fromhex(value) for address,value in sites.items())
    try:
        for label in order+order[::-1]:
            if not restored():
                raise RuntimeError('Profiling requires restored tactical hook sites')
            diagnostic_memory_check(pid, evidence)
            session = script = None
            stop = threading.Event()
            samples, errors, observations = [], [], []
            missed_polls = 0
            def sample():
                try:
                    while not stop.is_set() and len(samples)<20000:
                        paused,ticks = struct.unpack('<II',reader.read(0xfbaffc,8))
                        world = int.from_bytes(reader.read(0xfe17d4,4),'little')
                        samples.append((time.perf_counter(),ticks,paused,world))
                        stop.wait(.005)
                except Exception as error:
                    errors.append(str(error))
                    stop.set()
            worker = None
            try:
                if label != 'uninstrumented':
                    session = native_call(frida.attach, pid)
                    script = native_call(session.create_script, sources[label]+BOT_TRIAL_JS)
                    native_call(script.load)
                    executable_identity(NativeCalls(script.exports_sync))
                worker = threading.Thread(target=sample,daemon=True)
                worker.start()
                next_poll = time.monotonic()
                deadline = next_poll+seconds
                while time.monotonic()<deadline and not stop.is_set():
                    if script:
                        started=time.perf_counter()
                        raw=native_call(script.exports_sync.snapshot)
                        elapsed=(time.perf_counter()-started)*1000.
                        if raw.get('error') or raw.get('fault') or not raw.get('playing') or raw.get('paused'):
                            raise RuntimeError('Profiling scene unavailable: '+str(raw.get('error') or raw.get('fault')))
                        observations.append(dict(rpcMs=elapsed,observationMs=raw['observationMs'],
                            units=len(raw['units']),simulationTicks=raw['simulationTicks']))
                    next_poll += .5
                    now = time.monotonic()
                    if now > next_poll:
                        missed = int((now-next_poll)//.5)+1
                        missed_polls += missed
                        next_poll += missed*.5
                    stop.wait(max(0,min(next_poll,deadline)-now))
            finally:
                stop.set()
                if worker: worker.join(timeout=1)
                if script:
                    try: native_call(script.exports_sync.stop)
                    finally:
                        if session: native_call(session.detach)
                elif session: native_call(session.detach)
            if errors or (worker and worker.is_alive()):
                raise RuntimeError('Timing sampler failed: '+str(errors))
            evidence.write(dict(phase=label,samples=samples,observations=observations))
            phase=dict(label=label,**timing_metrics(samples),observations=observations,
                       missedSnapshotSlots=missed_polls,hooksRestored=restored())
            summary['phases'].append(phase)
            if not phase['hooksRestored']:
                raise RuntimeError('Profiling hooks did not restore')
            print('PROFILE '+label+' '+json.dumps({k:v for k,v in phase.items() if k!='observations'}),flush=True)
        summary['result']='observed'
    except BaseException as error:
        summary['error']=str(error)
        raise
    finally:
        reader.close()
        evidence.close(summary)
    return summary

# Diagnostic scope only. These offsets and types are the existing host's guarded
# session-card reader; no host mutation or UI input is needed. Recheck on the
# game thread before every trial action as well as every observation.
BOT_TRIAL_JS = r"""
let botTrialRoster = null;
function botRosterGuard() {
    const first = ptr('0xfead5c').readPointer(), last = ptr('0xfead60').readPointer();
    const bytes = last.sub(first).toInt32(), services = [];
    if (bytes < 0 || bytes % 4 || bytes > 128 * 4) throw Error('Invalid bot trial services');
    for (let at = 0; at < bytes; at += 4) {
        const service = first.add(at).readPointer();
        if (!service.isNull() && service.add(8).readU32() === 8 && service.add(0xd).readU8() === 0)
            services.push(service);
    }
    if (services.length !== 1 || !services[0].readPointer().equals(ptr('0xde0fd0')))
        throw Error('Bot trial session unavailable');
    const service = services[0], card = service.add(0x184).readPointer();
    const owner = ptr('0xf39e64').readU8();
    // Lobby member IDs and simulation ownership IDs are separate namespaces.
    // The native local-player global governs actor control; lobby authority
    // must compare the service member to the card's host member instead.
    const localMember = service.add(0x20).readU32();
    if (card.isNull() || !card.readPointer().equals(ptr('0xe274dc')) ||
        localMember === 0 || card.add(0xcc).readU32() !== localMember)
        throw Error('Bot trial local host authority changed');
    const begin = card.add(0x4f4).readPointer(), end = card.add(0x4f8).readPointer();
    const length = end.sub(begin).toInt32(), rows = [], ids = new Set();
    if (length < 8 || length % 4 || length > 64 * 4) throw Error('Bot trial roster unavailable');
    for (let at = 0; at < length; at += 4) {
        const row = begin.add(at).readPointer(), id = row.add(8).readU32(), type = row.add(4).readU32();
        const humanTrial = typeof humanOpponentTrial !== 'undefined' && humanOpponentTrial === true;
        if (ids.has(id) || (id === localMember ? type !== 1 : humanTrial ? ![1,2].includes(type) : type !== 2))
            throw Error('Bot trial requires only the local human and bots');
        ids.add(id);
        rows.push([id, type, row.add(0x134).readU32(), row.add(0x138).readU32(), stringAt(row.add(0x50))]);
    }
    if (!ids.has(localMember)) throw Error('Bot trial local member missing');
    if (typeof humanOpponentTrial !== 'undefined' && humanOpponentTrial === true) {
        const local=rows.find(r=>r[0]===localMember), opponents=rows.filter(r=>r[1]===1 && r[0]!==localMember);
        if (!['a','b'].includes(local[4]) || opponents.length<1 || opponents.length>3 ||
            opponents.some(r=>r[4]===local[4] || !['a','b'].includes(r[4])))
            throw Error('Human trial requires one to three opposing humans and sole local human team member');
    }
    rows.sort((a,b) => a[0] - b[0]);
    const signature = JSON.stringify([card.toString(), stringAt(card.add(0x544)), [owner, localMember, rows]]);
    if (botTrialRoster !== null && signature !== botTrialRoster) throw Error('Bot trial roster changed');
    botTrialRoster = signature;
    return signature;
}
const botTrialInspect = inspect;
const botAdoptions = new Map();
inspect = function(includePerception=false, includeAmmunition=true, onlyUnit=null) {
    const signature = botRosterGuard();
    const raw = botTrialInspect(includePerception, includeAmmunition, onlyUnit);
    for (const [id, request] of botAdoptions) {
        if (onlyUnit !== null && !(Array.isArray(onlyUnit) ? onlyUnit.includes(id) : id === onlyUnit)) continue;
        const row=raw.units.find(u=>u.id===id), member=enrollment.get(Number(id));
        if (!row || !member || raw.generation!==request.generation || row.incarnation!==request.incarnation ||
            row.revision!==request.revision || !row.eligible || row.controlLockRaw || raw.simulationTicks>=request.deadline) {
            botAdoptions.delete(id);continue;
        }
        if (row.movementBits===0) {
            member.enrolled=true;member.revision++;
            row.enrolled=true;row.revision=member.revision;
            botAdoptions.delete(id);
        }
    }
    return {...raw, botTrialRoster: signature};
};
const botObservedTrial=trialObserved;
trialObserved=function(options, baseline) {
    if (options.adoptAfterMode && (options.action!=='mode' || options.mode!==0 ||
        !baseline.units.some(u=>u.id===options.id && u.incarnation===options.incarnation &&
            u.revision===0 && options.unitRevision===0 && !u.enrolled)))
        throw new Rejected('Automatic test adoption requires untouched newly purchased infantry');
    const result=botObservedTrial(options,baseline);
    if (options.adoptAfterMode && result.status==='serialized')
        botAdoptions.set(options.id,{generation:baseline.generation,incarnation:options.incarnation,
            revision:0,deadline:baseline.simulationTicks+2000});
    return result;
};
caps.contacts = true; // Diagnostic observation only; production source stays gated.
"""

PATH_WATCH_JS = r"""
const pathWatchAddress = ptr('0x8c3c40');
const pathWatchBytes = Array.from(new Uint8Array(pathWatchAddress.readByteArray(16)))
    .map(value => value.toString(16).padStart(2, '0')).join('');
if (pathWatchBytes !== '558bec83ec348b55105356578b028bf9') throw Error('Unsupported native path wrapper');
let pathWatchCount = 0;
const pathWatchBuffers = new Map();
const pathWatchStats = {calls:0,owned:0,exact:0,taskTypes:{}};
const pathWatchInspect = inspect;
inspect = function(includePerception=false, includeAmmunition=true, onlyUnit=null) {
    return {...pathWatchInspect(includePerception, includeAmmunition, onlyUnit),pathWatchStats:{...pathWatchStats}};
};
hooks.push(Interceptor.attach(pathWatchAddress, {
    onEnter(args) {
        this.pathWatch = null;
        pathWatchStats.calls++;
        if (pathWatchCount >= 128) return;
        try {
            const descriptor = args[0], actor = descriptor.readPointer();
            if (actor.isNull() || actor.add(0x774).readU8() !== ptr('0xf39e64').readU8()) return;
            const id = actor.add(0x776).readU16(), current = actors.get(id);
            if (!current || !current.equals(actor)) return;
            pathWatchStats.owned++;
            const task = this.context.ecx;
            const type = task.readPointer().toString();
            pathWatchStats.taskTypes[type] = (pathWatchStats.taskTypes[type] || 0) + 1;
            if (pathWatchStats.owned <= 16)
                event('native_path_task', {id:String(id),taskType:type,
                    taskWords:[0,4,8,12,16,20,24].map(offset=>task.add(offset).readU32()),
                    caller:this.returnAddress.toString(),simulationTicks:ptr('0xfbb000').readU32()});
            if (!['0xdf9858','0xdf8728'].includes(type)) return;
            pathWatchStats.exact++;
            this.pathWatch = {id:String(id), incarnation:incarnations.get(id), generation:matchToken(),
                taskType:type,
                origin:[args[2].readFloat(), args[2].add(4).readFloat()],
                target:[task.add(0xc).readFloat(), task.add(0x10).readFloat()],
                taskFlag:task.add(4).readU8(), taskLimit:task.add(8).readFloat(),
                descriptorWords:[0,4,8,12].map(offset => descriptor.add(offset).readU32()),
                output:args[1], started:Date.now()};
        } catch (error) { fault = String(error); }
    },
    onLeave(result) {
        const trace = this.pathWatch;
        if (!trace || trace.generation !== matchToken() || trace.incarnation !== incarnations.get(Number(trace.id))) return;
        try {
            const first = trace.output.readPointer(), last = trace.output.add(4).readPointer();
            const capacity = trace.output.add(8).readPointer(), bytes = last.sub(first).toInt32();
            if (bytes < 0 || bytes % 12 || bytes > 4096 * 12 || capacity.compare(last) < 0)
                throw Error('Native path trace vector invalid');
            const points = [];
            for (let at = 0; at < bytes && points.length < 128; at += 12)
                points.push([0,4,8].map(offset => first.add(at + offset).readFloat()));
            const {output, started, ...input} = trace;
            if (!first.isNull()) pathWatchBuffers.set(first.toString(),
                {id:trace.id,incarnation:trace.incarnation,capacity:(capacity.sub(first).toInt32()) / 12});
            event('native_path_result', {...input, resultByte:result.toUInt32() & 255,
                outputFlags:[output.add(0x20).readU8(),output.add(0x21).readU8()],
                cost:output.add(0xc).readFloat(), pointCount:bytes / 12, points,
                simulationTicks:ptr('0xfbb000').readU32(), elapsedMs:Date.now() - started});
            pathWatchCount++;
        } catch (error) { fault = String(error); }
    }
}));
const pathFreeAddress = ptr('0x8b2740');
const pathFreeBytes = Array.from(new Uint8Array(pathFreeAddress.readByteArray(16)))
    .map(value => value.toString(16).padStart(2, '0')).join('');
if (pathFreeBytes !== '558bec8b450c8b4d083d555555157734') throw Error('Unsupported path vector release');
hooks.push(Interceptor.attach(pathFreeAddress, {
    onEnter(args) {
        const key = args[0].toString(), allocation = pathWatchBuffers.get(key);
        if (!allocation) return;
        pathWatchBuffers.delete(key);
        event('native_path_release', {...allocation,nativeCapacity:args[1].toUInt32(),
            simulationTicks:ptr('0xfbb000').readU32()});
    }
}));
"""


def policy_scale_trial(output):
    """Repeatable offline CPU measurements, kept separate from game evidence."""
    import platform
    import statistics
    from dataclasses import replace
    evidence = Evidence(output)
    summary = dict(scenario='offline_policy_scale', sourceHashes=source_hashes(),
        scenarioSourceSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        configuration=dict(unitCounts=[128, 256, 512, 1024], contacts=256, repetitions=5),
        python=platform.python_version(), machine=platform.machine(), measurements=[],
        nativeEngineMeasured=False, synchronization='unverified', ordersIssued=0)
    try:
        for count in summary['configuration']['unitCounts']:
            units = tuple(Unit(Identity('scale', str(i), 1), 'local', str(i // 12),
                (float(i % 32) * 10, float(i // 32) * 10), move_at_will=True) for i in range(count))
            contacts = tuple(Contact(Identity('scale', 'e' + str(i), 1),
                (float(i % 16) * 12 + 400, float(i // 16) * 12), 0., True, True) for i in range(256))
            snapshot = Snapshot('scale', 0., 'local', units, contacts=contacts,
                objectives=(Objective('flag', (2000., 2000.), 'enemy'),),
                capabilities=frozenset({'move', 'attack', 'stance'}))
            cold, warm = [], []
            for repeat in range(5):
                policy = Policy()
                for phase, scene, timings in (('cold', snapshot, cold),
                        ('continuing', replace(snapshot, time=.2), warm)):
                    start = time.perf_counter()
                    intents = policy.step(scene)
                    elapsed = (time.perf_counter() - start) * 1000.
                    timings.append(elapsed)
                    if len(policy.members) != count or len(intents) > 32:
                        raise RuntimeError('Scale identity/order budget mismatch')
                    evidence.write(dict(units=count, contacts=256, repetition=repeat,
                        phase=phase, milliseconds=elapsed, intents=len(intents)))
            summary['measurements'].append(dict(units=count, coldMedianMs=statistics.median(cold),
                continuingMedianMs=statistics.median(warm), maxMs=max(cold + warm)))
        summary.update(result='pass', gateScope='Offline bounded policy processing only; live hundreds-unit throughput remains unverified')
    except BaseException as error:
        summary.update(result='failed', error=str(error))
        raise
    finally:
        evidence.close(summary)
    return summary


def army_mode_setup(api, baseline, evidence, summary, bots=False):
    """Prepare native modes; the next attachment separately tests adoption."""
    if (not baseline.get('playing') or baseline.get('paused') or
            (not baseline.get('botTrialRoster') if bots else
             set(baseline.get('playerTeams', {})) != {baseline['owner']})):
        raise RuntimeError('Army setup needs an active scene with only the local player')
    eligible = [u for u in baseline['units'] if u['eligible'] and not u['squadLeader'] and not u['controlLockRaw']]
    sequence = 0
    for unit in eligible:
        if unit['movementBits'] == 0:
            continue
        sequence += 1
        reply = api.trialstance(dict(id=unit['id'], incarnation=unit['incarnation'],
            generation=baseline['generation'], revision=baseline['commandRevision'],
            sequence=sequence, action='mode', mode=0))
        evidence.write({'setupMode': unit['id'], 'ack': reply})
        if reply.get('status') != 'serialized':
            raise RuntimeError('Army opt-in setup failed; no replay: ' + str(reply))
    deadline = time.monotonic() + 4
    while True:
        raw = api.snapshot()
        evidence.write({'afterModeSetup': raw})
        if raw.get('error') or raw.get('fault') or raw.get('generation') != baseline['generation']:
            raise RuntimeError('Army mode setup observation lost')
        if bots and raw.get('botTrialRoster') != baseline['botTrialRoster']:
            raise RuntimeError('Army mode setup bot roster changed')
        rows = {u['id']: u for u in raw['units']}
        if any(u['id'] not in rows or rows[u['id']]['incarnation'] != u['incarnation'] for u in eligible):
            raise RuntimeError('Army mode setup identity changed')
        if all(rows[u['id']]['movementBits'] == 0 for u in eligible):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('Army mode setup did not complete; no replay')
        time.sleep(.1)
    summary.update(result='pass', setupModeOrders=sequence, preparedUnits=[u['id'] for u in eligible],
        gateScope='Native Move-at-will modes only; adoption requires a new attachment')


class BotSupply:
    """One normal purchase in flight; opt in only its newly observed infantry."""
    def __init__(self, api, adapter, evidence):
        self.api,self.adapter,self.evidence=api,adapter,evidence
        self.purchase=None
        self.recruits={}
        self.next_purchase=0.
        self.purchases=0
        self.adopted=0
        self.planner=ForcePlanner()

    def request(self,raw,action,**options):
        self.adapter.sequence+=1
        intent=dict(generation=raw['generation'],revision=raw['commandRevision'],
                    sequence=self.adapter.sequence,action=action,**options)
        reply=self.api.trialstance(intent)
        self.adapter._submission_events(reply)
        self.evidence.write(dict(supplyIntent=intent,ack=reply))
        if reply.get('error') and reply.get('rejected') is not True:
            raise RuntimeError('Uncertain supply request; no replay: '+str(reply))
        return reply

    def step(self,raw,snapshot=None,policy=None):
        if raw.get('paused') or not raw.get('playing'):
            return
        now=raw['simulationTicks']/1000.
        template=self.planner.choose(snapshot,policy) if snapshot is not None and policy is not None else 'rifle'
        rows={(u['id'],u['incarnation']):u for u in raw['units']}
        # The user authorized utilizing the stranded owned force. Adopt only
        # untouched actors with verified individual command scope; subsequent
        # manual revisions still win. This also catches newly orphaned leaders.
        for key,row in rows.items():
            if (row['eligible'] and row.get('individualOrder',not row['squadLeader']) and
                    not row['enrolled'] and row['revision']==0 and not row['controlLockRaw']):
                self.recruits.setdefault(key,None)
        if self.purchase is not None:
            before,deadline=self.purchase
            spawned={key:u for key,u in rows.items() if key not in before and u['eligible']}
            if spawned:
                self.evidence.write(dict(purchaseObserved=list(u['id'] for u in spawned.values()),simulationTime=now))
                self.recruits.update({key:None for key,u in spawned.items()
                    if u.get('individualOrder',not u['squadLeader']) and not u['controlLockRaw']})
                self.purchase=None
            elif now>=deadline:
                raise RuntimeError('Purchase arrival unobserved; uncertain purchase will not be replayed')
        mode_budget=4
        for key,deadline in list(self.recruits.items()):
            row=rows.get(key)
            if not row or not row['eligible'] or row['controlLockRaw']:
                del self.recruits[key];continue
            if row['enrolled'] and (row['movementBits']==0 or row.get('controllerGroup') is True):
                self.adopted+=1;del self.recruits[key];continue
            if row['revision']!=0:
                del self.recruits[key];continue  # Player reclamation wins.
            if deadline is not None:
                if now>=deadline:
                    raise RuntimeError('Native recruit mode/enrollment unobserved; no replay')
                continue
            if mode_budget==0:
                continue
            mode_budget-=1
            reply=self.request(raw,'mode',id=row['id'],incarnation=row['incarnation'],
                               unitRevision=0,mode=0,adoptAfterMode=True)
            if reply.get('rejected') is True:
                del self.recruits[key];continue
            if reply.get('status')!='serialized':
                raise RuntimeError('Uncertain recruit mode; no replay')
            self.recruits[key]=now+3.
        if (self.purchase is not None or self.recruits or now<self.next_purchase or self.purchases>=256 or
                len(rows) > Policy.MAX_UNITS - 128):
            return
        self.next_purchase=now+5.
        self.evidence.write(dict(purchasePlan=template,reason=self.planner.reason,
            effectiveStrength=self.planner.strength,simulationTime=now))
        query=self.request(raw,'purchase_query',purchaseTemplate=template)
        if query.get('rejected') is True:
            return
        if query.get('status')!='queried' or type(query.get('available')) is not bool:
            raise RuntimeError('Invalid native purchase availability')
        if not query['available']:
            return
        reply=self.request(raw,'purchase',purchaseTemplate=template)
        if reply.get('rejected') is True:
            return
        if reply.get('status')!='submitted_unconfirmed':
            raise RuntimeError('Uncertain native purchase; no replay')
        self.purchases+=1
        self.purchase=(set(rows),now+45.)


def army_combat_trial(api, baseline, evidence, summary, battle=False, duration=None):
    """Exercise the actual runtime locally; outcomes are measurements, not wins."""
    if (not baseline.get('playing') or (baseline.get('paused') and not battle) or not baseline.get('botTrialRoster')):
        raise RuntimeError('Army combat trial requires the guarded local-host bot scene')
    enrolled = [u for u in baseline['units'] if u['eligible'] and u['enrolled'] and
                u.get('individualOrder',not u['squadLeader']) and not u['controlLockRaw'] and u['movementBits'] == 0]
    if not (0 if battle else 4) <= len(enrolled) <= Policy.MAX_UNITS:
        raise RuntimeError('Army combat trial requires 4..1024 opted-in owned nonleaders')
    if battle:
        roster_identity = json.loads(baseline['botTrialRoster'])
        if not isinstance(roster_identity, list) or len(roster_identity) != 3 or not roster_identity[1]:
            raise RuntimeError('Battle native start identity unavailable')
        summary['battleNativeStartTime'] = roster_identity[1]
    class DiagnosticApi:
        def submit(self, options): return api.trialstance(options)
        def trialstance(self, options): return api.trialstance(options)
    adapter = NativeAdapter(DiagnosticApi(), evidence)
    runtime = Runtime(adapter.submit, evidence)
    supply=BotSupply(api,adapter,evidence) if battle else None
    metrics=TacticalMetrics()
    summary.update(result='observed', localTeam=baseline.get('team'), selectedUnits=[u['id'] for u in enrolled], orders={},
        samples=0, visibleContactSamples=0, visibleVehicleContactSamples=0, peakVisibleVehicles=0,
        firingGuardSamples=0, nativeDeaths=0,
        nativeObservationMaxMs=0, runtimeStepMaxMs=0, reachedUnits=[],
        readinessSamples={}, peakPressureRatio=0., squadStateSamples={}, withdrawalOrders=0, withdrawalArrivals=0,
        gateScope='Bounded local bot combat integration; no matched superiority or replication claim',
        diagnosticCapabilities=['move', 'stance', 'attack', 'objectives', 'death', 'contacts', 'pathQuery'] +
            (['nativeCover', 'leaderFollow'] if battle else []))
    if summary.get('humanOpponentsAuthorized'):
        summary['diagnosticCapabilities'].remove('nativeCover')
        summary['coverDisabledReason'] = 'First human-client desync interval contained the first native cover probe; causation unresolved'
    seen_events, reached = set(), set()
    start = time.monotonic()
    duration = (1800 if battle else 120) if duration is None else duration
    if not isinstance(duration, (int, float)) or not 0 < duration <= 1800:
        raise ValueError('Invalid bounded battle duration')
    summary['configuredWallSeconds'] = duration
    sync_monitor = SyncLogMonitor(Path.home()/'Documents/my games/men of war - assault squad 2/log/game.log',
                                  baseline['simulationTicks']) if battle else None
    next_status=start+10.
    try:
        while time.monotonic() - start < duration:
            if battle and (evidence.path / 'STOP').exists():
                summary['controllerStoppedByFile'] = True
                break
            raw = api.snapshot()
            evidence.write({'observation': raw})
            if (raw.get('error') or raw.get('fault') or raw.get('generation') != baseline['generation'] or
                    raw.get('botTrialRoster') != baseline['botTrialRoster']):
                raise RuntimeError('Army combat observation/authority changed')
            if sync_monitor:
                failure = sync_monitor.poll(raw['simulationTicks'])
                summary['syncLogMonitorStatus'] = sync_monitor.status
                if failure:
                    summary.update(failureKind='out_of_sync', synchronizationFailure=failure,
                                   outcome='interrupted', matchCompleted=False)
                    evidence.write({'synchronizationFailure': failure})
                    (evidence.path/'synchronization_failure.json').write_text(
                        json.dumps(failure, indent=2), encoding='utf-8')
                    break
            if not raw.get('playing'):
                summary['gameplayStopped'] = True
                summary['matchCompleted'] = type(raw.get('managerStateRaw')) is int and raw['managerStateRaw'] == 3
                summary['terminalObservation'] = {key: raw.get(key) for key in
                    ('generation', 'simulationTicks', 'managerStateRaw', 'botTrialRoster')}
                break
            for event in adapter.events + raw['events']:
                if event['kind'] != 'owned_death':
                    continue  # This metric deduplicates deaths, not every bullet.
                if event['key'] in seen_events:
                    continue
                seen_events.add(event['key'])
                if len(seen_events) > 8192:
                    raise RuntimeError('Army combat event accounting budget exceeded')
                summary['nativeDeaths'] += 1
            caps = {**raw['capabilities'], **{key: True for key in summary['diagnosticCapabilities']}}
            snapshot = adapter.snapshot({**raw, 'capabilities': caps})
            completed = adapter.completions(snapshot, runtime.inflight)
            reached.update(intent.identity.unit for intent, status in completed
                           if intent.action == 'move' and status == 'completed')
            tick_start = time.perf_counter()
            sent = runtime.step(snapshot, completed)
            summary['runtimeStepMaxMs'] = max(summary['runtimeStepMaxMs'], (time.perf_counter() - tick_start) * 1000.)
            if battle:
                cover_start = time.perf_counter()
                adapter.prepare_cover(snapshot, runtime.policy)
                summary['coverProbeMaxMs'] = max(summary.get('coverProbeMaxMs', 0.),
                    (time.perf_counter() - cover_start) * 1000.)
            if supply:
                # Supply RPCs can return shots newer than this snapshot. Keep
                # those events for the next observation, just like order RPCs.
                supply.step(raw,snapshot,runtime.policy)
                summary.update(nativePurchases=supply.purchases,recruitsAdopted=supply.adopted,
                    selectedUnits=sorted(set(summary['selectedUnits']) |
                        {u['id'] for u in raw['units'] if u['eligible'] and u['enrolled'] and
                            u.get('individualOrder',not u['squadLeader'])}))
            summary['withdrawalArrivals'] += sum(intent.action == 'move' and intent.reason == 'withdraw'
                                                and status == 'completed'
                                                for intent, status in completed)
            summary['tactics']=metrics.sample(snapshot,runtime,completed)
            summary['controlCoverage']=adapter.control_coverage()
            for unit in snapshot.units:
                if not unit.move_at_will or unit.direct_control:
                    continue
                summary['readinessSamples'][unit.readiness] = summary['readinessSamples'].get(unit.readiness, 0) + 1
                if not snapshot.paused:
                    ratio = runtime.policy.pressure(unit.position)
                    summary['peakPressureRatio'] = max(summary['peakPressureRatio'], ratio)
            for squad in runtime.policy.squads.values():
                summary['squadStateSamples'][squad.state] = summary['squadStateSamples'].get(squad.state, 0) + 1
            for intent in sent:
                summary['orders'][intent.action] = summary['orders'].get(intent.action, 0) + 1
                summary['withdrawalOrders'] += int(intent.action == 'move' and intent.reason == 'withdraw')
            summary['samples'] += 1
            summary['visibleContactSamples'] += sum(c.visible and c.enemy is True for c in snapshot.contacts)
            vehicles=sum(c.visible and c.enemy is True and not c.dead and c.kind=='vehicle' for c in snapshot.contacts)
            summary['visibleVehicleContactSamples'] += vehicles
            summary['peakVisibleVehicles'] = max(summary['peakVisibleVehicles'],vehicles)
            summary['firingGuardSamples'] += sum(u.readiness == 'firing' for u in snapshot.units)
            summary['nativeObservationMaxMs'] = max(summary['nativeObservationMaxMs'], raw.get('observationMs', 0))
            summary.update(reachedUnits=sorted(reached),
                elapsedSimulationSeconds=(raw['simulationTicks'] - baseline['simulationTicks']) / 1000.,
                finalObjectives=raw['objectives'], aliveEligible=sum(u['eligible'] for u in raw['units']))
            if time.monotonic()>=next_status:
                # Preserve a bounded current report even if the controller or
                # game exits before the final result dialog can be collected.
                summary['outcome'] = 'unknown'
                temporary=evidence.path / 'progress.json.tmp'
                temporary.write_text(json.dumps(summary,indent=2),encoding='utf-8')
                temporary.replace(evidence.path / 'progress.json')
                print('COMBAT '+json.dumps({key:summary.get(key) for key in
                    ('samples','nativePurchases','recruitsAdopted','aliveEligible','nativeDeaths',
                     'orders','elapsedSimulationSeconds')}),flush=True)
                next_status=time.monotonic()+10.
            if not battle and not any(u.move_at_will for u in snapshot.units):
                summary['noControlledSurvivors'] = True
                break
            time.sleep(.2)
    finally:
        summary['outcome'] = ('unknown' if summary.get('matchCompleted') else 'interrupted')
        runtime.stop()


def army_objectives_trial(api, baseline, evidence, summary):
    """Headless objective/throughput trial in a local-owner-only controlled scene."""
    if (not baseline.get('playing') or baseline.get('paused') or
            set(baseline.get('playerTeams', {})) != {baseline['owner']} or not baseline['objectives']):
        raise RuntimeError('Army trial needs an active objective scene with only the local player')
    eligible = [u for u in baseline['units'] if u['eligible'] and not u['squadLeader'] and
                not u['controlLockRaw'] and u['enrolled'] and u['movementBits'] == 0]
    if not 4 <= len(eligible) <= 1024:
        raise RuntimeError('Army trial requires 4..1024 opted-in owned nonleaders; use army_setup before attaching')
    summary.update(selectedUnits=[u['id'] for u in eligible], setupModeOrders=0, orders=0,
        diagnosticCapabilities=['move', 'stance', 'objectives', 'death', 'ammoLoading'],
        gateScope='Local headless multi-squad objective progress; no combat, cover, construction or synchronization claim')
    class DiagnosticApi:
        # Use the existing diagnostic serialization surface. Production admission
        # and its capability flags remain untouched and unavailable.
        def submit(self, options): return api.trialstance(options)
    adapter = NativeAdapter(DiagnosticApi(), evidence)
    runtime = Runtime(adapter.submit, evidence)
    initial = {u['id']: u for u in eligible}
    owned_before = {o['key'] for o in baseline['objectives'] if o['occupant'] == baseline['team']}
    arrived, moved, addressed = set(), set(), set()
    summary.update(nativeObservationMaxMs=0, runtimeStepIncludingRpcMaxMs=0, orders=0, sampleCount=0)
    start = time.monotonic()
    try:
        while time.monotonic() - start < 120:
            raw = api.snapshot()
            evidence.write({'observation': raw})
            if (raw.get('error') or raw.get('fault') or raw.get('generation') != baseline['generation'] or
                    set(raw.get('playerTeams', {})) != {baseline['owner']}):
                raise RuntimeError('Army observation or local-player authority changed')
            if raw.get('playing') is not True:
                summary['gameplayStopped'] = True
                summary['matchCompleted'] = type(raw.get('managerStateRaw')) is int and raw['managerStateRaw'] == 3
                break
            rows = {u['id']: u for u in raw['units']}
            if any(key not in rows or rows[key]['incarnation'] != u['incarnation'] for key, u in initial.items()):
                raise RuntimeError('Army identity changed during no-enemy trial')
            capabilities = dict(raw['capabilities'])
            capabilities.update({key: True for key in summary['diagnosticCapabilities']})
            snapshot = adapter.snapshot({**raw, 'capabilities': capabilities})
            completed = adapter.completions(snapshot, runtime.inflight)
            arrived.update(intent.identity.unit for intent, status in completed if intent.action == 'move')
            tick_start = time.perf_counter()
            sent = runtime.step(snapshot, completed)
            summary['runtimeStepIncludingRpcMaxMs'] = max(summary['runtimeStepIncludingRpcMaxMs'], (time.perf_counter() - tick_start) * 1000.)
            addressed.update(intent.identity.unit for intent in sent)
            summary['orders'] += len(sent)
            summary['sampleCount'] += 1
            summary['nativeObservationMaxMs'] = max(summary['nativeObservationMaxMs'], raw.get('observationMs', 0))
            moved.update(key for key, u in initial.items() if dist(rows[key]['position'], u['position']) > 100)
            captured = [o for o in raw['objectives'] if o['key'] not in owned_before and o['occupant'] == raw['team']]
            proximate = [o['key'] for o in captured if o.get('captureRadius') is not None and
                any(dist(rows[key]['position'], o['position']) < o['captureRadius'] for key in initial)]
            summary.update(movedUnits=sorted(moved), arrivedUnits=sorted(arrived), addressedUnits=sorted(addressed),
                capturedObjectives=[o['key'] for o in captured], proximateCapturedObjectives=proximate,
                elapsedSimulationSeconds=(raw['simulationTicks'] - baseline['simulationTicks']) / 1000.,
                queueSize=len(runtime.queue.pending), inflight=len(runtime.inflight))
            if proximate and len(arrived) >= len(initial) * .9:
                summary.update(result='pass', captureAttribution='Team capture with controlled-unit proximity')
                return
            time.sleep(.2)
        summary.update(result='observed', incomplete='Not all objective/progress thresholds reached in the bounded window')
    finally:
        runtime.stop()

# Diagnostic only: use the ordinary multiplayer pause request, never the local
# pause-reason setter. Kept outside the production RPC/action surface.
PAUSE_TRIAL_JS = r'''
const pauseSignature = '558bec83ec2456578bf98b078b405cffd0';
const pauseBytes = Array.from(new Uint8Array(ptr('0xb57a00').readByteArray(17)))
    .map(b => b.toString(16).padStart(2, '0')).join('');
if (pauseBytes !== pauseSignature) throw Error('Unsupported pause request entry');
const requestNativePause = new NativeFunction(ptr('0xb57a00'), 'void', ['pointer', 'int'],
    {abi: 'thiscall', exceptions: 'propagate'});
let pauseJob = null, pauseOwner = null, pauseMatch = null, pauseSent = false, resumeSent = false, resumeAt = 0;
function pauseClient() {
    const begin = ptr('0xfead5c').readPointer(), end = ptr('0xfead60').readPointer();
    const length = end.sub(begin).toInt32();
    if (length < 0 || length % 4 || length > 256) throw Error('Invalid service registry');
    let client = null, server = null;
    for (let offset = 0; offset < length; offset += 4) {
        const service = begin.add(offset).readPointer();
        if (service.isNull() || service.add(13).readU8()) continue;
        const id = service.add(8).readU32();
        if (id === 9) { if (client) throw Error('Duplicate client'); client = service; }
        if (id === 8) { if (server) throw Error('Duplicate server'); server = service; }
    }
    if (!client || !server || !client.readPointer().equals(ptr('0xdde5b8')) ||
        !server.readPointer().equals(ptr('0xde0fd0'))) throw Error('Unsupported local multiplayer services');
    const authority = server.add(0x184).readPointer();
    if (authority.isNull() || authority.add(0xcc).readU32() !== client.add(0x20).readU32())
        throw Error('Local client lacks native pause authority');
    return client;
}
function issuePauseRequest(resume) {
    const client = pauseClient();
    if (pauseOwner && (!client.equals(pauseOwner) || pauseMatch !== matchToken()))
        throw Error('Pause trial session changed');
    const state = client.add(0x1ac).readU32(), paused = ptr('0xfbaffc').readU32() !== 0;
    if (resume) {
        if (resumeSent) return;
        if (!pauseSent || !paused || state !== 1) throw Error('Resume requires confirmed trial pause');
        resumeSent = true;
    } else {
        const manager = ptr('0xfed0c4').readPointer();
        if (pauseSent || paused || state !== 0 || manager.isNull() ||
            !manager.readPointer().equals(ptr('0xe317f0')) || manager.add(12).readU32() !== 1)
            throw Error('Pause trial requires an active unpaused match');
        pauseOwner = client; pauseMatch = matchToken(); pauseSent = true; resumeAt = Date.now() + 5000;
    }
    requestNativePause(client, 0);
}
hooks.push(Interceptor.attach(ptr('0x715b60'), {
    onEnter() {
        if (stopped || !this.returnAddress.equals(ptr('0x665556')) || !this.context.ecx.equals(ptr('0xfbafdc'))) return;
        if (pauseJob) {
            const job = pauseJob; pauseJob = null;
            try {
                if (Date.now() > job.deadline) throw Error('Pause request expired');
                issuePauseRequest(job.resume); job.resolve({status: 'requested', resume: job.resume});
            } catch (error) { job.resolve({error: String(error)}); }
        }
        if (pauseSent && !resumeSent && Date.now() >= resumeAt && ptr('0xfbaffc').readU32() !== 0) {
            try { issuePauseRequest(true); }
            catch (error) { fault = String(error); }
        }
    }
}));
rpc.exports.pauserequest = function(resume) {
    if (stopped || pauseJob || typeof resume !== 'boolean') throw Error('Pause trial unavailable');
    return new Promise(resolve => { pauseJob = {resume, resolve, deadline: Date.now() + 2000}; });
};
'''


def pause_trial(api, baseline, evidence, summary, watchdog=False):
    if baseline.get('playing') is not True or baseline.get('paused') is not False:
        raise RuntimeError('Pause trial needs an active unpaused match')
    observed = []
    try:
        request = api.pauserequest(False)
        evidence.write({'pauseRequest': request})
        if request.get('status') != 'requested':
            raise RuntimeError(str(request))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            raw = api.snapshot()
            evidence.write({'pauseObservation': raw})
            if raw.get('error') or raw.get('generation') != baseline['generation']:
                raise RuntimeError('Pause observation/session unavailable')
            if raw['paused']:
                observed.append(raw['simulationTicks'])
                if len(observed) >= 5:
                    break
            time.sleep(.2)
        if len(observed) < 5 or len(set(observed)) != 1:
            raise RuntimeError('Pause did not provide five frozen-clock snapshots')
        rejected = api.trialstance({'generation': baseline['generation'], 'sequence': 1,
                                   'revision': baseline['commandRevision'], 'action': 'purchase_query'})
        evidence.write({'pausedAction': rejected})
        if rejected.get('rejected') is not True or 'Game paused' not in rejected.get('error', ''):
            raise RuntimeError('Paused action was not rejected')
        summary.update(pausedSamples=len(observed), frozenSimulationTicks=observed[0], pausedActionRejected=True)
        if watchdog:
            # Leave the native safeguard responsible for resume. The controller
            # sends no RPC or input during this interval.
            time.sleep(5.5)
            recovered = api.snapshot()
            evidence.write({'watchdogResume': recovered})
            if (recovered.get('error') or recovered.get('fault') or
                    recovered.get('generation') != baseline['generation'] or
                    recovered.get('paused') is not False or recovered.get('simulationTicks', 0) <= observed[-1]):
                raise RuntimeError('Native automatic resume did not recover progressing observations')
            summary['automaticResumeValidated'] = True
    finally:
        current = api.snapshot()
        evidence.write({'beforeResume': current})
        if current.get('generation') == baseline['generation'] and current.get('paused') is True:
            reply = api.pauserequest(True)
            evidence.write({'resumeRequest': reply})
            if reply.get('status') != 'requested':
                raise RuntimeError('Resume request failed: ' + str(reply))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            current = api.snapshot()
            evidence.write({'resumeObservation': current})
            if (current.get('generation') == baseline['generation'] and current.get('paused') is False and
                    current.get('simulationTicks', 0) > (observed[-1] if observed else baseline['simulationTicks'])):
                summary['resumed'] = True
                break
            time.sleep(.2)
        if summary.get('resumed') is not True:
            raise RuntimeError('Native resume/tick progression unconfirmed')
    summary.update(result='pass', ordersIssued=0, pauseRequests=2)

FRIENDLY_RELOAD_JS = r'''
// Read-only diagnostic. No native calls and no orders to allied units.
const reloadCycles = new Map();
let reloadSequence = 0;
function reloadSubject(ammo) {
    if (ammo.isNull() || !ammo.readPointer().equals(ptr('0xdf525c'))) return null;
    const weapon = ammo.add(4).readPointer();
    if (weapon.isNull() || !weapon.readPointer().equals(ptr('0xdf51f0')) ||
        !weapon.add(0x64).readPointer().equals(ammo)) return null;
    const actor = weapon.add(0x54).readPointer();
    if (actor.isNull()) return null;
    const id = actor.add(0x776).readU16(), current = actors.get(id), owner = actor.add(0x774).readU8();
    const local = ptr('0xf39e64').readU8();
    if (!current || !current.equals(actor) || (owner !== local && ownerRelation(local, owner) !== 2) ||
        nativeDead(actor) !== false) return null;
    const definition = weapon.add(0x58).readPointer(), item = weapon.add(0xdc).readPointer();
    if (definition.isNull() || !definition.readPointer().equals(ptr('0xdf5fc0')) ||
        (!item.isNull() && !item.readPointer().equals(ptr('0xdf31b8')))) return null;
    const ammoCount = item.isNull() ? 0 : item.add(0x2c).readU32();
    const clipSize = definition.add(0x314).readU32(), pendingRounds = ammo.add(0xc).readU32();
    const placement = weapon.add(0x60).readPointer();
    if (ammoCount > 10000 || clipSize > 10000 || pendingRounds > 10000)
        throw Error('Friendly reload observation count exceeded');
    return {id: String(id), incarnation: incarnations.get(id), owner: String(owner),
        generation: matchToken(), simulationTicks: ptr('0xfbb000').readU32(), ammoCount,
        clipSize, pendingRounds, nativeLoading: !!(ammo.add(0x18).readU16() & 0x20),
        placementType: placement.isNull() ? null : placement.readPointer().toString(),
        recoveryUntilTicks: ammo.add(0x14).readU32()};
}
for (const [address, phase] of [['0x845050', 'begin'], ['0x8454c0', 'end']]) {
    hooks.push(Interceptor.attach(ptr(address), {
        onEnter() {
            this.before = null;
            try {
                this.ammo = this.context.ecx;
                this.before = reloadSubject(this.ammo);
            } catch (error) { fault = String(error); }
        },
        onLeave() {
            if (!this.before || stopped) return;
            try {
                const after = reloadSubject(this.ammo), before = this.before, key = this.ammo.toString();
                if (!after || ['id', 'incarnation', 'owner', 'generation'].some(k => before[k] !== after[k])) {
                    reloadCycles.delete(key); return;
                }
                for (const [oldKey, old] of reloadCycles) {
                    if (old.generation !== after.generation || after.simulationTicks - old.simulationTicks > 60000)
                        reloadCycles.delete(oldKey);
                }
                if (phase === 'begin') {
                    if (!reloadCycles.has(key) && reloadCycles.size >= 128) throw Error('Reload cycle budget exceeded');
                    const cycle = ++reloadSequence;
                    reloadCycles.set(key, {...after, cycle});
                    event('friendly_reload_begin', {...after, cycle, ammoBefore: before.ammoCount});
                } else {
                    const start = reloadCycles.get(key); reloadCycles.delete(key);
                    const matched = start && ['id', 'incarnation', 'owner', 'generation', 'clipSize']
                        .every(k => start[k] === after[k]);
                    event('friendly_reload_end', {...after, cycle: matched ? start.cycle : null,
                        startedAtTicks: matched ? start.simulationTicks : null, ammoBefore: before.ammoCount,
                        pendingBefore: before.pendingRounds});
                }
            } catch (error) { fault = String(error); }
        }
    }));
}
hooks.push(Interceptor.attach(ptr('0x844650'), {
    onEnter() {
        try {
            const ammo = this.context.ecx, cycle = reloadCycles.get(ammo.toString());
            if (!cycle || stopped) return;
            const now = ptr('0xfbb000').readU32();
            if (now - (cycle.sampledAtTicks || cycle.simulationTicks) < 1000) return;
            const current = reloadSubject(ammo);
            if (!current || ['id', 'incarnation', 'owner', 'generation'].some(k => current[k] !== cycle[k])) {
                reloadCycles.delete(ammo.toString()); return;
            }
            cycle.sampledAtTicks = now;
            event('friendly_reload_progress', {...current, cycle: cycle.cycle});
        } catch (error) { fault = String(error); }
    }
}));
'''


FRIENDLY_AIM_JS = r'''
let shooterCycleSamples = 0;
function shooterCycleState(shooter) {
    if (shooter.isNull() || !shooter.readPointer().equals(ptr('0xdf57b4'))) return null;
    const weapon = shooter.add(4).readPointer();
    if (weapon.isNull() || !weapon.add(0x68).readPointer().equals(shooter)) return null;
    const subject = reloadSubject(weapon.add(0x64).readPointer());
    if (!subject) return null;
    const placement = weapon.add(0x60).readPointer();
    if (placement.isNull() || !placement.readPointer().equals(ptr('0xdf59f4')) ||
        !placement.add(8).readPointer().equals(weapon)) return null;
    const fireState = rifleFireState(weapon, subject.ammoCount,
        weapon.add(0x64).readPointer().add(0x18).readU16(), subject.recoveryUntilTicks);
    return {...subject, fireState, shotsRaw: shooter.add(8).readU32(),
        burstRemainingRaw: shooter.add(0x10).readU32(), activeRaw: shooter.add(0xc).readU8(),
        placementStateRaw: placement.add(0xc).readU32(), waitRaw: placement.add(0x54).readU8(),
        placementDeadlineTicks: placement.add(4).readU32()};
}
const shooterCycleAddress = ptr('0x84d8a0');
const shooterCycleBytes = Array.from(new Uint8Array(shooterCycleAddress.readByteArray(16)))
    .map(value => value.toString(16).padStart(2, '0')).join('');
if (shooterCycleBytes !== '558bec83ec08578bf9807f0e000f859f') throw Error('Unsupported shooter cycle');
hooks.push(Interceptor.attach(shooterCycleAddress, {
    onEnter() {
        this.before = null;
        if (stopped || shooterCycleSamples >= 512) return;
        try {
            this.shooter = this.context.ecx;
            this.before = shooterCycleState(this.shooter);
            if (this.before) {
                this.weapon = this.shooter.add(4).readPointer();
                this.placement = this.weapon.add(0x60).readPointer();
            }
        } catch (error) { fault = String(error); }
    },
    onLeave() {
        if (!this.before || stopped) return;
        try {
            if (!this.shooter.add(4).readPointer().equals(this.weapon) ||
                !this.weapon.add(0x60).readPointer().equals(this.placement)) return;
            const after = shooterCycleState(this.shooter), before = this.before;
            if (!after || ['id','incarnation','owner','generation'].some(key => before[key] !== after[key])) return;
            event('friendly_shooter_cycle', {before, after,
                shotCounterAdvanced: after.shotsRaw > before.shotsRaw});
            shooterCycleSamples++;
        } catch (error) { fault = String(error); }
    }
}));
const placementSamples = new Map();
const firePredicateSamples = new Map();
let firePredicateCount = 0;
const firePredicateAddress = ptr('0x84d0a0');
const firePredicateBytes = Array.from(new Uint8Array(firePredicateAddress.readByteArray(16)))
    .map(value => value.toString(16).padStart(2, '0')).join('');
if (firePredicateBytes !== '568bf18b4e048b4160837810007428e8') throw Error('Unsupported fire predicate');
hooks.push(Interceptor.attach(firePredicateAddress, {
    onEnter() {
        this.before = null;
        if (stopped || firePredicateCount >= 1024) return;
        try {
            this.shooter = this.context.ecx;
            const before = shooterCycleState(this.shooter);
            if (!before || !before.fireState) return;
            const key = before.generation + ':' + before.id + ':' + before.incarnation;
            const old = firePredicateSamples.get(key), state = JSON.stringify(before.fireState);
            if (old && old.state === state && before.simulationTicks - old.ticks < 1000) return;
            if (!old && firePredicateSamples.size >= 128) throw Error('Fire predicate identity budget exceeded');
            firePredicateSamples.set(key, {state, ticks: before.simulationTicks});
            this.before = before;
            this.weapon = this.shooter.add(4).readPointer();
        } catch (error) { fault = String(error); }
    },
    onLeave(result) {
        if (!this.before || stopped) return;
        try {
            if (!this.shooter.add(4).readPointer().equals(this.weapon)) return;
            const after = shooterCycleState(this.shooter), before = this.before;
            if (!after || ['id','incarnation','owner','generation'].some(key => before[key] !== after[key])) return;
            const nativeResult = result.toUInt32() & 255;
            if (nativeResult > 1) throw Error('Invalid native fire predicate result');
            event('friendly_fire_predicate', {before, nativeResult: !!nativeResult,
                matchesMirror: !!nativeResult === before.fireState.nativeFirePredicate});
            firePredicateCount++;
        } catch (error) { fault = String(error); }
    }
}));
hooks.push(Interceptor.attach(ptr('0x851330'), {
    onEnter() {
        this.subject = null;
        try {
            this.placement = this.context.ecx;
            this.placementType = this.placement.readPointer().toString();
            const prepare = this.placement.readPointer().add(0x10).readPointer().toString();
            // These mapped overrides all use the same base placement routine
            // and weapon back-pointer; record the concrete type for attribution.
            if (!['0x851330', '0x855400', '0x855710', '0x855280'].includes(prepare)) return;
            const weapon = this.placement.add(8).readPointer();
            if (weapon.isNull() || !weapon.add(0x60).readPointer().equals(this.placement)) return;
            this.ammo = weapon.add(0x64).readPointer();
            this.subject = reloadSubject(this.ammo);
            this.stateBefore = this.placement.add(0xc).readU32();
            this.caller = this.returnAddress.toString();
        } catch (error) { fault = String(error); }
    },
    onLeave(result) {
        if (!this.subject || stopped) return;
        try {
            const current = reloadSubject(this.ammo);
            if (!current || ['id', 'incarnation', 'owner', 'generation'].some(k => current[k] !== this.subject[k])) return;
            const weapon = this.ammo.add(4).readPointer();
            if (!weapon.add(0x60).readPointer().equals(this.placement) ||
                !this.placement.add(8).readPointer().equals(weapon) ||
                this.placement.readPointer().toString() !== this.placementType) return;
            const code = result.toUInt32() & 255, waitRaw = this.placement.add(0x54).readU8();
            const key = current.generation + ':' + current.id + ':' + current.incarnation;
            const old = placementSamples.get(key);
            if (old && old.code === code && old.waitRaw === waitRaw && current.simulationTicks - old.ticks < 1000) return;
            if (!old && placementSamples.size >= 128) throw Error('Placement observation budget exceeded');
            placementSamples.set(key, {code, waitRaw, ticks: current.simulationTicks});
            const shooter = weapon.add(0x68).readPointer();
            const supportedShooter = !shooter.isNull() && shooter.readPointer().equals(ptr('0xdf57b4')) &&
                shooter.add(4).readPointer().equals(weapon);
            event('friendly_placement_result', {...current, resultRaw: code, waitRaw,
                placementDeadlineTicks: this.placement.add(4).readU32(), caller: this.caller,
                placementType: this.placementType, stateBeforeRaw: this.stateBefore,
                // The caller stores this result and updates the shooter AFTER
                // this hook returns. These counters describe the preceding work.
                shooterShotsRaw: supportedShooter ? shooter.add(8).readU32() : null,
                shooterActiveRaw: supportedShooter ? shooter.add(0xc).readU8() : null,
                shooterBurstRemainingRaw: supportedShooter ? shooter.add(0x10).readU32() : null});
        } catch (error) { fault = String(error); }
    }
}));
'''


FRIENDLY_COVER_JS = r'''
// Observe engine-generated requests. Do not alter weights or call native code.
const coverAssessmentSamples = new Map();
function coverAssessmentSubject(request) {
    const actor = request.add(0x1c).readPointer();
    if (actor.isNull()) return null;
    const id = actor.add(0x776).readU16(), current = actors.get(id);
    const owner = actor.add(0x774).readU8(), local = ptr('0xf39e64').readU8();
    if (!current || !current.equals(actor) || nativeDead(actor) !== false ||
        (owner !== local && ownerRelation(local, owner) !== 2)) return null;
    return {id: String(id), incarnation: incarnations.get(id), owner: String(owner),
        generation: matchToken(), actor: actor.toString()};
}
hooks.push(Interceptor.attach(ptr('0x8a75a0'), {
    onEnter() {
        this.subject = null;
        if (stopped) return;
        try {
            this.request = this.context.ecx;
            const subject = coverAssessmentSubject(this.request);
            if (!subject) return;
            const key = subject.generation + ':' + subject.id + ':' + subject.incarnation;
            const ticks = ptr('0xfbb000').readU32(), old = coverAssessmentSamples.get(key);
            if (old !== undefined && ticks - old < 2000) return;
            if (old === undefined && coverAssessmentSamples.size >= 128) throw Error('Cover assessment identity budget exceeded');
            coverAssessmentSamples.set(key, ticks);
            this.weights = Array.from({length: 8}, (_, i) => this.request.add(0x68 + i * 4).readFloat());
            if (!this.weights.every(Number.isFinite)) throw Error('Invalid cover assessment weights');
            this.inputRecords = coverInputCount(ptr(subject.actor));
            this.subject = subject;
            this.caller = this.returnAddress.toString();
        } catch (error) { fault = String(error); }
    },
    onLeave() {
        if (!this.subject || stopped) return;
        try {
            const current = coverAssessmentSubject(this.request);
            if (!current || Object.keys(current).some(k => current[k] !== this.subject[k])) return;
            const begin = this.request.readPointer(), end = this.request.add(4).readPointer();
            const bytes = end.sub(begin).toInt32();
            if (bytes < 0 || bytes % 128 || bytes > 4096 * 128) throw Error('Invalid native cover assessment vector');
            const candidates = [];
            for (let i = 0; i < Math.min(bytes / 128, 8); i++) {
                const candidate = begin.add(i * 128);
                const position = [candidate.add(0x10).readFloat(), candidate.add(0x14).readFloat()];
                const components = Array.from({length: 10}, (_, j) => candidate.add(0x58 + j * 4).readFloat());
                if (![...position, ...components].every(Number.isFinite)) throw Error('Invalid assessed cover components');
                candidates.push({typeRaw: candidate.readU32(), flagsRaw: candidate.add(0x4c).readU32() & 0x1f,
                    position, componentsRaw: components});
            }
            const actor = ptr(current.actor), targetRecord = this.request.add(0x4c).readPointer();
            const observerPosition = [0x44, 0x48, 0x4c].map(offset => actor.add(offset).readFloat());
            const targetRecordedPosition = targetRecord.isNull() ? null :
                [0x10, 0x14, 0x18].map(offset => targetRecord.add(offset).readFloat());
            if (![...observerPosition, ...(targetRecordedPosition || [])].every(Number.isFinite))
                throw Error('Invalid cover assessment spatial context');
            const {actor: actorAddress, ...identity} = current;
            event('friendly_cover_assessment', {...identity, simulationTicks: ptr('0xfbb000').readU32(),
                observerPosition, targetRecordedPosition,
                inputRecordCountRaw: this.inputRecords, hasTargetRecordRaw: !this.request.add(0x4c).readPointer().isNull(),
                caller: this.caller, weightsRaw: this.weights, candidateCount: bytes / 128, candidates});
        } catch (error) { fault = String(error); }
    }
}));
'''


def friendly_reload_watch(api, baseline, evidence, summary, aim=False, cover=False):
    if baseline.get('playing') is not True or baseline.get('paused') is not False:
        raise RuntimeError('Friendly observation needs an active unpaused match')
    completed, seen, loading_cycles = [], set(), set()
    summary.update(ordersIssued=0, reloadCycles=completed, samples=0, activeLoadingSamples=0)
    if aim:
        summary.update(placementSamples=0, placementResults={}, placementWaitingSamples=0,
                       shooterCycles=0, advancedShotCycles=0, firingPlacementStates={},
                       nativeFireSamples=0, nativeFireAllowed=0, nativeFireRefused=0, firePredicateMismatches=0)
    if cover:
        summary.update(coverAssessmentSamples=0, weightedCoverSamples=0,
                       weightedCoverWithInputs=0, weightedCoverWithTarget=0)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        raw = api.snapshot()
        evidence.write({'observation': raw})
        if (raw.get('error') or raw.get('fault') or raw.get('generation') != baseline['generation'] or
                raw.get('playing') is not True):
            raise RuntimeError('Friendly observation lost match continuity')
        summary['samples'] += 1
        for event in raw.get('events', []):
            if event['key'] in seen:
                continue
            seen.add(event['key'])
            if len(seen) > 2048:
                raise RuntimeError('Friendly observation event budget exceeded')
            if aim and event['kind'] == 'friendly_placement_result':
                summary['placementSamples'] += 1
                result = str(event['resultRaw'])
                summary['placementResults'][result] = summary['placementResults'].get(result, 0) + 1
                summary['placementWaitingSamples'] += int(event['waitRaw'] != 0)
            if aim and event['kind'] == 'friendly_shooter_cycle':
                summary['shooterCycles'] += 1
                if event['shotCounterAdvanced'] is True:
                    summary['advancedShotCycles'] += 1
                    state = str(event['before']['placementStateRaw'])
                    summary['firingPlacementStates'][state] = summary['firingPlacementStates'].get(state, 0) + 1
            if aim and event['kind'] == 'friendly_fire_predicate':
                summary['nativeFireSamples'] += 1
                summary['nativeFireAllowed'] += int(event['nativeResult'] is True)
                summary['nativeFireRefused'] += int(event['nativeResult'] is False)
                summary['firePredicateMismatches'] += int(event['matchesMirror'] is not True)
            if cover and event['kind'] == 'friendly_cover_assessment':
                summary['coverAssessmentSamples'] += 1
                weighted = bool(any(event['weightsRaw']) and event['candidateCount'] > 0)
                summary['weightedCoverSamples'] += int(weighted)
                inputs = event.get('inputRecordCountRaw')
                summary['weightedCoverWithInputs'] += int(weighted and type(inputs) is int and inputs > 0)
                summary['weightedCoverWithTarget'] += int(weighted and event.get('hasTargetRecordRaw') is True)
            if event['kind'] == 'friendly_reload_progress' and event['nativeLoading'] is True:
                loading_cycles.add(event['cycle'])
                summary['activeLoadingSamples'] += 1
            if (event['kind'] == 'friendly_reload_end' and event['cycle'] is not None and
                    event['generation'] == baseline['generation'] and event['nativeLoading'] is False and
                    event['pendingRounds'] == 0 and event['ammoCount'] > event['ammoBefore'] and
                    event['simulationTicks'] > event['startedAtTicks']):
                completed.append({**event, 'activeLoadingObserved': event['cycle'] in loading_cycles})
        if aim and summary['placementSamples'] >= 30 and summary['placementWaitingSamples'] and any(
                k in summary['placementResults'] for k in ('3', '4')):
            summary.update(result='observed', gateScope='Raw placement return/wait fields; aim readiness unverified')
            return
        if cover and summary['weightedCoverWithInputs'] >= 10:
            summary.update(result='observed', gateScope='Native weighted cover assessments with input records; suitability unverified')
            return
        if not aim and not cover and len([e for e in completed if e['clipSize'] == 8 and e['activeLoadingObserved']]) >= 2:
            summary.update(result='pass', gateScope='Friendly native ammunition loading; aim and replication unverified')
            return
        time.sleep(.2)
    summary.update(result='observed', gateScope='Insufficient weighted cover observations with input records' if cover else 'Insufficient placement observations' if aim else
                   'Insufficient completed eight-round loading cycles')


class GameKeys:
    """Send verified bindings only while this PID's game window has focus."""
    def __init__(self, pid, posted=False):
        self.pid, self.posted = pid, posted
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.user.SetProcessDPIAware()  # Client pixels must match physical screenshots.
        self.user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        self.user.FindWindowW.restype = wintypes.HWND
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.user.PostMessageW.restype = wintypes.BOOL
        self.user.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
        self.user.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
        self.user.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self.user.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
        self.window = self.user.FindWindowW(None, 'Men of War: Assault Squad 2')
        actual = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(self.window, ctypes.byref(actual))
        if actual.value != pid:
            raise RuntimeError('Game window PID mismatch')
        self.previous = self.user.GetForegroundWindow()
        if not posted:
            self.user.ShowWindow(self.window, 9)
            self.user.SetForegroundWindow(self.window)
            time.sleep(.2)

    def press(self, key):
        if self.posted:
            actual = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(self.window, ctypes.byref(actual))
            if actual.value != self.pid:
                raise RuntimeError('Game window identity changed; message withheld')
            scan = self.user.MapVirtualKeyW(key, 0)
            down = 1 | scan << 16
            if not self.user.PostMessageW(self.window, 0x100, key, down):
                raise ctypes.WinError(ctypes.get_last_error())
            # Always pair the down/up messages immediately. This transport targets
            # only the verified game window and never changes the OS lock state.
            if not self.user.PostMessageW(self.window, 0x101, key, down | 0xc0000000):
                raise ctypes.WinError(ctypes.get_last_error())
            return
        if self.user.GetForegroundWindow() != self.window:
            raise RuntimeError('Game lost focus; key withheld')
        scan = self.user.MapVirtualKeyW(key, 0)
        if not 0 < scan < 256:
            raise RuntimeError('Unsupported keyboard scan code')
        self.user.keybd_event(key, scan, 0, 0)
        try:
            time.sleep(.1)
        finally:
            self.user.keybd_event(key, scan, 2, 0)
        # Native command acknowledgement precedes the UI/input refresh. Live
        # repeated toggles failed at .2 s and passed at .75 s on this build.
        time.sleep(.75)

    def click(self, point, right=False):
        if self.posted or self.user.GetForegroundWindow() != self.window:
            raise RuntimeError('Game lacks foreground input; click withheld')
        bounds = wintypes.RECT()
        if not self.user.GetClientRect(self.window, ctypes.byref(bounds)):
            raise ctypes.WinError(ctypes.get_last_error())
        if len(point) != 2 or any(type(v) is not int for v in point) or not (
                0 <= point[0] < bounds.right and 0 <= point[1] < bounds.bottom):
            raise ValueError('Click must be inside the game client')
        position = wintypes.POINT(*point)
        if not self.user.ClientToScreen(self.window, ctypes.byref(position)) or not self.user.SetCursorPos(position.x, position.y):
            raise ctypes.WinError(ctypes.get_last_error())
        time.sleep(.2)  # Let native mouse tracking observe the new cursor first.
        if self.user.GetForegroundWindow() != self.window:
            raise RuntimeError('Game lost focus; click withheld')
        down, up = (8, 16) if right else (2, 4)
        self.user.mouse_event(down, 0, 0, 0, 0)
        try:
            time.sleep(.1)
        finally:
            self.user.mouse_event(up, 0, 0, 0, 0)
        time.sleep(.75)

    def close(self):
        if not self.posted and self.user.GetForegroundWindow() == self.window and self.previous:
            self.user.SetForegroundWindow(self.previous)


def input_trial(api, baseline, evidence, summary, posted=False):
    selected = baseline['selectedOwnedIds']
    if len(selected) != 1:
        raise RuntimeError('Input trial needs an existing single owned selection')
    unit = next(u for u in baseline['units'] if u['id'] == selected[0])
    if unit['movementBits'] != 0 or unit['controlLockRaw']:
        raise RuntimeError('Input trial requires Move at will without direct control')
    addressed = set(unit['squadMembers']) if unit['squadLeader'] else {unit['id']}
    if any(u['movementBits'] != 0 for u in baseline['units'] if u['id'] in addressed):
        raise RuntimeError('Input trial requires uniformly opted-in addressed members')
    settings = Path.home() / 'Documents/My Games/men of war - assault squad 2/profiles/1101573056/keys.set'
    bindings = settings.read_text()
    import re
    for command, key in [('common/toggle_position', 'KEY_RBRACKET'), ('control_manual/toggle', 'KEY_E')]:
        if not re.search(r'\{"' + re.escape(command) + r'"\s*\{value ' + key + r'\}', bindings):
            raise RuntimeError('Unexpected input binding for ' + command)
    keys = GameKeys(summary['pid'], posted=posted)
    def wait_for(predicate):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            raw = api.snapshot()
            evidence.write({'observation': raw})
            if raw.get('generation') != baseline['generation']:
                raise RuntimeError('Match changed during input trial')
            row = next((u for u in raw['units'] if u['id'] == unit['id'] and
                        u['incarnation'] == unit['incarnation']), None)
            if row is None:
                raise RuntimeError('Selected unit invalidated')
            if predicate(row):
                return raw, row
            time.sleep(.1)
        raise RuntimeError('Input state timeout')
    try:
        for key, predicate, label in [
            (0xdd, lambda u: u['movementBits'] == 0x1000 and not u['enrolled'], 'hold'),
            (0xdd, lambda u: u['movementBits'] == 0 and u['enrolled'], 'move_at_will'),
            (0x45, lambda u: u['controlLockRaw'] != 0 and not u['enrolled'], 'direct_control'),
            (0x45, lambda u: u['controlLockRaw'] == 0 and not u['enrolled'], 'leave_direct_control'),
            (0xdd, lambda u: u['movementBits'] == 0x1000, 'hold_again'),
            (0xdd, lambda u: u['movementBits'] == 0 and u['enrolled'], 'reenable'),
        ]:
            evidence.write({'keyAction': label})
            keys.press(key)
            raw, row = wait_for(predicate)
            summary[label] = True
        others_before = {u['id']: u['enrolled'] for u in baseline['units'] if u['id'] not in addressed}
        others_after = {u['id']: u['enrolled'] for u in raw['units'] if u['id'] not in addressed}
        if others_before != others_after:
            raise RuntimeError('Input affected unrelated enrollment')
        summary.update(result='pass', inputUnit=unit['id'], unrelatedEnrollmentUnchanged=True)
    finally:
        keys.close()


def manual_move_trial(api, baseline, evidence, summary, point):
    """Real foreground right-click; validate reclamation before stale submission."""
    selected = baseline['selectedOwnedIds']
    unit = next((u for u in baseline['units'] if selected == [u['id']]), None)
    if not unit or unit['squadLeader'] or not unit['eligible'] or not unit['enrolled'] or unit['controlLockRaw']:
        raise RuntimeError('Manual move trial requires one selected, enrolled owned nonleader')
    stale = dict(id=unit['id'], incarnation=unit['incarnation'], generation=baseline['generation'],
        revision=baseline['commandRevision'], unitRevision=unit['revision'], sequence=1,
        action='stance', stance=unit['stance'], requireEnrolled=True)
    keys = GameKeys(summary['pid'])
    events, raw = [], baseline
    try:
        evidence.write({'manualMoveClick': point, 'staleIntent': stale})
        keys.click(point, right=True)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            raw = api.snapshot()
            evidence.write({'manualMoveObservation': raw})
            if raw.get('error') or raw.get('fault') or raw.get('generation') != baseline['generation']:
                raise RuntimeError('Manual move lost observation continuity')
            row = next((u for u in raw['units'] if (u['id'], u['incarnation']) == (unit['id'], unit['incarnation'])), None)
            if not row or not row['eligible']:
                raise RuntimeError('Manual move unit invalidated')
            events.extend(raw['events'])
            if any(e['kind'] == 'player_command' and e.get('type') == 1 and unit['id'] in e['ids'] for e in events):
                if row['enrolled'] or row['revision'] <= unit['revision'] or row['movementBits'] != 0:
                    raise RuntimeError('Manual order did not suspend Move-at-will enrollment')
                break
            time.sleep(.1)
        else:
            raise RuntimeError('No addressed native manual move command observed')
        # Refresh the global revision to isolate the per-unit takeover guard.
        stale['revision'] = raw['commandRevision']
        reply = api.trialstance(stale)
        evidence.write({'staleAfterManualMove': stale, 'ack': reply})
        if (reply.get('rejected') is not True or reply.get('status') == 'serialized' or
                'Unit reclaimed or revision cancelled' not in reply.get('error', '')):
            raise RuntimeError('Stale takeover intent was not rejected before execution')
        before = {(u['id'], u['incarnation']): (u['enrolled'], u['revision']) for u in baseline['units'] if u['id'] != unit['id']}
        after = {(u['id'], u['incarnation']): (u['enrolled'], u['revision']) for u in raw['units'] if u['id'] != unit['id']}
        if before != after:
            raise RuntimeError('Unrelated enrollment or identity changed')
        summary.update(result='pass', manualMoveSuspends=True, staleIntentRejected=True,
            unrelatedEnrollmentUnchanged=True, inputUnit=unit['id'], ordersIssued=0,
            playerInputCommands=1, finalEnrollment='suspended',
            gateScope='Player-origin move and stale unit revision; soldier remains manually controlled')
    finally:
        keys.close()


def barricade_trial(api, baseline, unit, evidence, summary, destination=None, cancel=False, direction=None):
    """One serialized build, bounded observation, no replay or usability claim."""
    sequence = 0
    def request(action, raw, **fields):
        nonlocal sequence
        sequence += 1
        intent = {'id': unit['id'], 'incarnation': unit['incarnation'],
            'generation': baseline['generation'], 'revision': raw['commandRevision'],
            'sequence': sequence, 'action': action, **fields}
        evidence.write({'intent': intent})
        reply = api.trialstance(intent)
        evidence.write({'ack': reply})
        return reply
    before = request('barricade_query', baseline)
    summary['inventoryBefore'] = before
    if before.get('status') != 'queried' or before.get('totalItemCount') != 1 or not before.get('nativeActorInventoryAllowed'):
        raise RuntimeError('Construction trial requires exactly one available kit')
    if destination is None:
        destination = list(unit['position'])
        destination[0] += 100
    summary.update(destination=destination, orders=0, createdEntities=[], usableDefense='unverified')
    reply = request('barricade', baseline, destination=destination,
                    **({'buildDirection': direction} if direction is not None else {}))
    summary['submission'] = reply
    if reply.get('status') != 'serialized':
        raise RuntimeError('Construction not serialized; no replay: ' + str(reply))
    summary['orders'] = 1
    deadline = time.monotonic() + 60
    interrupted_at = None
    seen = set()
    while time.monotonic() < deadline:
        raw = api.snapshot()
        evidence.write({'observation': raw})
        if raw.get('error') or raw.get('fault') or raw['generation'] != baseline['generation']:
            raise RuntimeError('Construction lost observation/match continuity')
        row = next((u for u in raw['units'] if u['id'] == unit['id'] and
                    u['incarnation'] == unit['incarnation']), None)
        if not row or not row['eligible'] or row['controlLockRaw'] or raw['commandRevision'] != baseline['commandRevision']:
            raise RuntimeError('Construction yielded to unit/player change; native outcome uncertain')
        inventory = request('barricade_query', raw)
        if inventory.get('status') != 'queried':
            raise RuntimeError('Construction inventory continuity lost: ' + str(inventory))
        summary['inventoryAfter'] = inventory
        for event in raw.get('events', []) + inventory.get('installationEvents', []):
            if (event['kind'] == 'install_entity_created' and event['id'] == unit['id'] and
                    event['incarnation'] == unit['incarnation'] and event['key'] not in seen):
                seen.add(event['key'])
                summary['createdEntities'].append(event)
        summary['sampleCount'] += 1
        if cancel and interrupted_at is None and inventory['heldItemCount'] > 0 and not summary['createdEntities']:
            interruption = request('move', raw, destination=unit['position'])
            summary['interruption'] = interruption
            if interruption.get('status') != 'serialized':
                raise RuntimeError('Construction interruption uncertain; no replay')
            summary['orders'] += 1
            interrupted_at = raw['simulationTicks']
            summary['interruptedAtSimulationTicks'] = interrupted_at
        if interrupted_at is not None:
            summary['kitCountDecrease'] = before['totalItemCount'] - inventory['totalItemCount']
            summary['returnedToStart'] = dist(row['position'][:2], unit['position'][:2]) <= 3
            if raw['simulationTicks'] - interrupted_at >= 20000:
                summary.update(result='pass' if not summary['createdEntities'] and summary['returnedToStart'] and
                    summary['kitCountDecrease'] == 0 else 'observed',
                    postInterruptionSimulationSeconds=(raw['simulationTicks'] - interrupted_at) / 1000.)
                summary['gateScope'] = 'Native interruption, return to start, kit retention and no creation for 20 simulation seconds'
                return
            time.sleep(.1)
            continue
        if summary['createdEntities']:
            matching = [e for e in summary['createdEntities'] if e['requestedEntity'] == 'sandbag3' and
                        dist(e['preparedPosition'][:2], destination[:2]) <= 50]
            summary.update(result='observed', matchingCreatedEntities=len(matching),
                kitCountDecrease=before['totalItemCount'] - inventory['totalItemCount'],
                elapsedSimulationSeconds=(raw['simulationTicks'] - baseline['simulationTicks']) / 1000.)
            cover = request('cover_query', raw)
            summary['coverAfter'] = cover
            ids = {e['createdEntityId'] for e in summary['createdEntities'] if e['requestedEntity'] == 'sandbag3'}
            associated = [c for c in cover.get('candidates', []) if c['found'] and c['nativeSourceEntityId'] in ids]
            summary['nativeCoverAssociated'] = bool(associated)
            if associated:
                summary['usableDefense'] = 'native cover candidates associated with created entity; protection unverified'
                summary['result'] = 'pass' if not cancel and len(ids) == 1 and summary['kitCountDecrease'] == 1 else 'observed'
                summary['gateScope'] = 'One created sandbag supplying native cover and one combined kit consumed; placement quality unverified'
                return
        time.sleep(.1)
    if summary['createdEntities'] or interrupted_at is not None:
        summary['result'] = 'observed'
        summary['observationDeadlineReached'] = True
        return
    raise RuntimeError('No attributed structure creation within bounded trial; no replay')


def squad_advance_trial(api, baseline, unit, evidence, summary):
    """Four opted-in nonleaders, at most two advancing legs each, no replay."""
    selected = sorted((u for u in baseline['units'] if u['id'] in unit['squadMembers'] and
                       u['eligible'] and not u['squadLeader'] and u['enrolled'] and
                       u['movementBits'] == 0 and not u['controlLockRaw']), key=lambda u: int(u['id']))[:4]
    if len(selected) != 4:
        raise RuntimeError('Squad advance requires four already opted-in nonleaders in one squad')
    objectives = [o for o in baseline['objectives'] if o['occupant'] != baseline['team']]
    if not baseline['team'] or not objectives:
        raise RuntimeError('Squad advance requires a playing team and uncaptured objective')
    target = min(objectives, key=lambda o: sum(dist(u['position'][:2], o['position'][:2]) for u in selected))
    identities = {u['id']: Identity(baseline['generation'], u['id'], u['incarnation']) for u in selected}
    issued, counts, completed_counts = {}, {}, {}
    summary.update(selectedUnits=list(identities), objective=target['key'], arrivals=[], orders=0,
                   minConcurrentEndpointGapWorld=None, maxConcurrentOrders=0,
                   gateScope='Four members advance, at most two legs each, all issued legs complete; no combat benefit claim')
    def submit(intent):
        if counts.get(intent.identity.unit, 0) >= 2 or intent.action != 'move':
            raise RuntimeError('Squad trial two-leg budget exceeded; no replay')
        row = rows[intent.identity.unit]
        destination = [v * 20. for v in intent.destination] + [row['position'][2]]
        gaps = [dist(destination[:2], [v * 20. for v in other.destination])
                for other in runtime.inflight.values() if other.destination is not None]
        if gaps:
            previous = summary['minConcurrentEndpointGapWorld']
            summary['minConcurrentEndpointGapWorld'] = min(gaps + ([] if previous is None else [previous]))
            if min(gaps) < 59.99:
                raise RuntimeError('Concurrent endpoints violate preset spacing threshold')
        reply = api.trialstance({'id': row['id'], 'incarnation': row['incarnation'],
            'generation': raw['generation'], 'revision': raw['commandRevision'],
            'sequence': intent.sequence, 'action': 'move', 'destination': destination,
            'requireEnrolled': True, 'unitRevision': row['revision']})
        evidence.write({'ack': reply, 'nativeDestination': destination})
        if reply.get('status') != 'serialized':
            raise RuntimeError('Squad command uncertain; no replay: ' + str(reply))
        issued[row['id']] = destination
        counts[row['id']] = counts.get(row['id'], 0) + 1
        summary['orders'] = sum(counts.values())
        return 'accepted'
    runtime = Runtime(submit, evidence, limit=4)
    start = time.monotonic()
    try:
        while time.monotonic() - start < 60:
            raw = api.snapshot()
            evidence.write({'observation': raw})
            if raw.get('error') or raw.get('fault') or raw['generation'] != baseline['generation'] or raw['commandRevision'] != baseline['commandRevision']:
                raise RuntimeError('Squad advance lost match/command continuity')
            rows = {u['id']: u for u in raw['units']}
            for key, identity in identities.items():
                row = rows.get(key)
                if (not row or row['incarnation'] != identity.incarnation or not row['eligible'] or
                        not row['enrolled'] or row['movementBits'] != 0 or row['controlLockRaw']):
                    raise RuntimeError('Squad member unavailable or reclaimed')
            now = (raw['simulationTicks'] - baseline['simulationTicks']) / 1000.
            completions = []
            for identity, intent in runtime.inflight.items():
                if intent.expires <= now:
                    raise RuntimeError('Squad leg completion deadline exceeded; no replay')
                if dist(rows[identity.unit]['position'][:2], issued[identity.unit][:2]) <= 40:
                    completions.append((intent, 'completed'))
            snapshot = Snapshot(baseline['generation'], now, raw['owner'],
                tuple(Unit(identities.get(u['id'], Identity(baseline['generation'], u['id'], u['incarnation'])),
                    raw['owner'], 'trial' if u['id'] in identities else 'background',
                    tuple(v / 20. for v in u['position'][:2]),
                    move_at_will=u['id'] in identities and (identities[u['id']] in runtime.inflight or
                        (completed_counts.get(u['id'], 0) < 2 and len(completed_counts) < 4)))
                    for u in raw['units'] if u['eligible']),
                objectives=(Objective(target['key'], tuple(v / 20. for v in target['position'][:2]), 'target'),),
                capabilities=frozenset({'move'}))
            runtime.step(snapshot, completions)
            for intent, _ in completions:
                completed_counts[intent.identity.unit] = completed_counts.get(intent.identity.unit, 0) + 1
            summary['arrivals'] = sorted(completed_counts)
            summary['completedLegsByUnit'] = dict(completed_counts)
            summary['maxConcurrentOrders'] = max(summary['maxConcurrentOrders'], len(runtime.inflight))
            positions = [rows[k]['position'][:2] for k in identities]
            gap = min(dist(a, b) for i, a in enumerate(positions) for b in positions[i + 1:])
            summary.setdefault('initialMinPhysicalGapWorld', gap)
            summary['lastMinPhysicalGapWorld'] = gap
            summary['elapsedSimulationSeconds'] = now
            summary['sampleCount'] += 1
            if len(completed_counts) == 4 and not runtime.inflight and not runtime.queue.pending:
                summary['result'] = 'pass'
                return
            time.sleep(.1)
        raise RuntimeError('Squad advance observation deadline exceeded')
    finally:
        runtime.stop()


def weapon_trial(api, baseline, unit, evidence, summary, action='weapon_watch', sequence_start=0):
    if action == 'attack':
        if baseline.get('playing') is not True or baseline.get('paused') is not False or not unit['enrolled']:
            raise RuntimeError('Attack trial requires enrolled infantry in an active unpaused match')
        identity = dict(id=unit['id'], incarnation=unit['incarnation'], generation=baseline['generation'],
            revision=baseline['commandRevision'], requireEnrolled=True, unitRevision=unit['revision'])
        query = api.trialstance({**identity, 'sequence': sequence_start + 1, 'action': 'attack_query'})
        evidence.write({'query': query})
        if query.get('status') != 'queried' or not query['targets']:
            raise RuntimeError('No validated visible enemy for attack trial')
        target = min(query['targets'], key=lambda t: dist(unit['position'], t['observedPosition']))
        target_distance = dist(unit['position'], target['observedPosition'])
        if target_distance > ATTACK_TRIAL_RANGE:
            raise RuntimeError('No visible enemy within the attack trial distance bound')
        intent = {**identity, 'sequence': sequence_start + 2, 'action': 'attack',
            'target': {**target['identity'], 'generation': baseline['generation'], 'entityId': target['entityId']}}
        evidence.write({'intent': intent})
        reply = api.trialstance(intent)
        evidence.write({'ack': reply})
        if reply.get('status') != 'serialized':
            raise RuntimeError('Attack not confirmed serialized; no replay: ' + str(reply))
        summary.update(attackTarget=target, attackSerialized=True, attackCompleted=False,
                       attackTargetDistanceWorld=target_distance, attackTrialRangeWorld=ATTACK_TRIAL_RANGE)
        sequence_start += 2
    previous, transitions, samples, projectiles = None, [], 0, 0
    summary.update(samples=0, weaponTransitions=transitions, attributedBulletConstructions=0,
                   readinessSemantics='native fields only; shot/reload attribution incomplete')
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        samples += 1
        reply = api.trialstance({'id': unit['id'], 'incarnation': unit['incarnation'],
            'generation': baseline['generation'], 'revision': baseline['commandRevision'],
            'sequence': samples + sequence_start, 'action': 'weapon_query'})
        evidence.write({'query': reply})
        if reply.get('status') != 'queried':
            raise RuntimeError(str(reply))
        projectiles += len(reply.get('projectileEvents', []))
        current = tuple(reply.get(k) for k in ('equipped', 'supportedAmmo', 'ammoCount',
                                               'loadingSerialized', 'reloadRequestedSerialized',
                                               'recoveryUntilTicks', 'nativeFirePredicate'))
        if previous is not None and previous != current:
            transitions.append({'before': previous, 'after': current,
                                'simulationTicks': reply.get('simulationTicks')})
        previous = current
        summary.update(samples=samples, attributedBulletConstructions=projectiles)
        time.sleep(.1)
    summary.update(result='observed', samples=samples, weaponTransitions=transitions,
                   attributedBulletConstructions=projectiles,
                   readinessSemantics='native fields only; shot/reload attribution incomplete')
    return summary


def objective_trial(api, baseline, unit, evidence, summary, combat_observation=False, attack_on_contact=False):
    """One local nonleader; no combat or synchronization claim from this scene."""
    if baseline.get('playing') is not True or baseline.get('paused') is not False:
        raise RuntimeError('Objective trial requires an active unpaused match')
    if unit['movementBits'] != 0 or not baseline['team'] or not baseline['objectives']:
        raise RuntimeError('Objective trial requires opted-in infantry and validated map/team')
    identity = Identity(str(baseline['generation']), unit['id'], unit['incarnation'])
    start_sim = baseline['simulationTicks']
    start = time.monotonic()
    active = None
    orders = 0
    target_key = None
    target_is_defense = False
    native_sequence, next_query = 0, 0.
    seen_events = set()
    def record_events(events):
        for event in events:
            if event['key'] in seen_events:
                continue
            seen_events.add(event['key'])
            if len(seen_events) > 2048:
                raise RuntimeError('Combat event budget exceeded')
            if event.get('id') != unit['id'] or event.get('incarnation') != unit['incarnation']:
                continue
            if event['kind'] in {'owned_death', 'bullet_created'}:
                counts = summary.setdefault('observedNativeEvents', {})
                counts[event['kind']] = counts.get(event['kind'], 0) + 1
    def submit(intent):
        nonlocal orders, target_key, native_sequence, target_is_defense
        if orders >= 64:
            raise RuntimeError('Objective trial order budget exhausted')
        target_key = runtime.policy.squads['trial'].goal
        target_is_defense = defending_only
        if not defending_only and any(o['key'] == target_key and o['occupant'] == raw['team'] for o in raw['objectives']):
            raise RuntimeError('Chosen objective is already friendly in the current snapshot')
        destination = [v * 20. for v in intent.destination] + [row['position'][2]]
        evidence.write({'nativeDestination': destination, 'sequence': intent.sequence})
        native_sequence += 1
        reply = api.trialstance({'id': unit['id'], 'incarnation': unit['incarnation'],
            'generation': raw['generation'], 'revision': raw['commandRevision'],
            'sequence': native_sequence, 'action': 'move', 'destination': destination,
            'requireEnrolled': True, 'unitRevision': row['revision']})
        evidence.write({'ack': reply})
        record_events(reply.get('observedEvents', []))
        readiness_adapter._submission_events(reply)
        if reply.get('status') != 'serialized':
            if reply.get('rejected') is True:
                summary['admissionCancellations'] = summary.get('admissionCancellations', 0) + 1
                return 'cancelled'  # Native admission proves this request never executed.
            raise RuntimeError('Uncertain command; no replay: ' + str(reply))
        orders += 1
        return 'accepted'
    runtime = Runtime(submit, evidence, limit=1)
    readiness_adapter = NativeAdapter(api, evidence)
    while time.monotonic() - start < 180:
        raw = api.snapshot()
        evidence.write({'observation': raw})
        record_events(raw.get('events', []))
        if raw.get('error') or raw.get('fault'):
            raise RuntimeError(str(raw))
        row = next((u for u in raw['units'] if u['id'] == unit['id'] and
                    u['incarnation'] == unit['incarnation']), None)
        if (raw.get('playing') is not True or raw.get('paused') is not False or
                not row or raw['generation'] != baseline['generation'] or not row['eligible']
                or row['movementBits'] != 0 or row['controlLockRaw']
                or raw['commandRevision'] != baseline['commandRevision']):
            raise RuntimeError('Trial yielded to unit/match change or a player command')
        now = (raw['simulationTicks'] - start_sim) / 1000.
        readiness_snapshot = readiness_adapter.snapshot(raw)
        observed_unit = next(u for u in readiness_snapshot.units if u.identity == identity)
        ammo, readiness = observed_unit.ammo, observed_unit.readiness
        if readiness == 'firing':
            summary['recentShotGuardSamples'] = summary.get('recentShotGuardSamples', 0) + 1
        if combat_observation and now >= next_query:
            next_query = now + 1.
            for action in ('weapon_query', 'attack_query' if attack_on_contact else 'sensor_query'):
                native_sequence += 1
                reply = api.trialstance({'id': unit['id'], 'incarnation': unit['incarnation'],
                    'generation': raw['generation'], 'revision': raw['commandRevision'],
                    'sequence': native_sequence, 'action': action,
                    'requireEnrolled': True, 'unitRevision': row['revision']})
                evidence.write({'query': reply, 'queryAction': action})
                record_events(reply.get('observedEvents', []))
                readiness_adapter._submission_events(reply)
                if reply.get('status') != 'queried':
                    raise RuntimeError('Combat observation lost admission: ' + str(reply))
                summary['combatQueryCount'] = summary.get('combatQueryCount', 0) + 1
                if attack_on_contact and action == 'attack_query' and any(
                        dist(row['position'], t['observedPosition']) <= ATTACK_TRIAL_RANGE for t in reply['targets']):
                    runtime.stop()
                    summary['approachOrders'] = orders
                    weapon_trial(api, raw, row, evidence, summary, 'attack', native_sequence)
                    return
        # Policy geometry uses units of 20 native world coordinates, matching
        # the engine geometry scale; this trial makes no range/accuracy claims.
        position = tuple(v / 20. for v in row['position'][:2])
        defending_only = combat_observation and bool(raw['objectives']) and all(
            o['occupant'] == raw['team'] for o in raw['objectives'])
        if defending_only:
            summary['approachPurpose'] = 'defend a friendly objective; no unseen enemy destination'
        snapshot = Snapshot(identity.match, now, raw['owner'],
            (Unit(identity, raw['owner'], 'trial', position, move_at_will=True, ammo=ammo, readiness=readiness),),
            objectives=tuple(Objective(o['key'], tuple(v / 20. for v in o['position'][:2]),
                raw['owner'] if o['occupant'] == raw['team'] else (o['occupant'] or None),
                reachable=None) for o in raw['objectives'] if defending_only or o['occupant'] != raw['team']),
                capabilities=frozenset({'move'}))
        if not target_is_defense and target_key and any(o['key'] == target_key and o['occupant'] == raw['team'] for o in raw['objectives']):
            target = next(o for o in raw['objectives'] if o['key'] == target_key)
            radius = target.get('captureRadius')
            distance = dist(row['position'], target['position'])
            reached = distance < radius if radius is not None else distance <= 400
            summary.update(result='pass' if reached else 'observed', objective=target_key, orders=orders,
                           simulationSeconds=now, objectiveCaptured=True,
                           unitReachedObjective=reached, distanceToObjectiveWorld=distance,
                           objectiveProximityBasis='native shared capture zone' if radius is not None else '400-world-unit fallback',
                           objectiveCaptureRadiusWorld=radius,
                           captureAttribution='team only; independent contribution not measured',
                           combatValidated=False, finalPosition=row['position'])
            if not attack_on_contact and (not combat_observation or reached):
                return
            target_key = None
        completions = ((active, 'completed'),) if active and dist(position, active.destination) <= 2. else ()
        runtime.step(snapshot, completions)
        active = next(iter(runtime.inflight.values()), None)
        time.sleep(.2)
    raise RuntimeError('Objective trial timed out without confirmed capture')


def handoff_trial(api, baseline, unit, evidence, summary):
    if not unit['enrolled']:
        raise RuntimeError('Handoff trial requires an enrolled unit')
    identity = {'id': unit['id'], 'incarnation': unit['incarnation'], 'generation': baseline['generation']}
    reply = api.trialstance({**identity, 'revision': baseline['commandRevision'], 'sequence': 1,
        'action': 'move', 'destination': unit['position'], 'asPlayerCommand': True})
    evidence.write({'manualMove': reply})
    if reply.get('status') != 'serialized':
        raise RuntimeError(str(reply))
    after = api.snapshot()
    evidence.write({'afterManual': after})
    row = next(u for u in after['units'] if u['id'] == unit['id'])
    if row['enrolled'] or row['movementBits'] != 0:
        raise RuntimeError('Manual move did not suspend Move-at-will enrollment')
    reply = api.trialstance({**identity, 'revision': after['commandRevision'], 'sequence': 2,
        'action': 'stance', 'stance': row['stance'], 'requireEnrolled': True, 'unitRevision': unit['revision']})
    evidence.write({'staleIntent': reply})
    if not reply.get('rejected'):
        raise RuntimeError('Reclaimed intent was not rejected')
    reply = api.trialstance({**identity, 'revision': after['commandRevision'], 'sequence': 3,
        'action': 'mode', 'mode': 0, 'asPlayerCommand': True})
    evidence.write({'reenableSameValue': reply})
    if reply.get('status') != 'serialized':
        raise RuntimeError(str(reply))
    after = api.snapshot()
    evidence.write({'afterReenable': after})
    row = next(u for u in after['units'] if u['id'] == unit['id'])
    if not row['enrolled']:
        raise RuntimeError('Same-value Move-at-will did not re-enable enrollment')
    reply = api.trialstance({**identity, 'revision': after['commandRevision'], 'sequence': 4,
        'action': 'stance', 'stance': row['stance'], 'requireEnrolled': True, 'unitRevision': row['revision']})
    evidence.write({'controllerOrder': reply})
    if reply.get('status') != 'serialized':
        raise RuntimeError(str(reply))
    after = api.snapshot()
    evidence.write({'afterControllerOrder': after})
    if not next(u for u in after['units'] if u['id'] == unit['id'])['enrolled']:
        raise RuntimeError('Controller order revoked its own enrollment')
    before_others = {u['id']: u['enrolled'] for u in baseline['units'] if u['id'] != unit['id']}
    after_others = {u['id']: u['enrolled'] for u in after['units'] if u['id'] != unit['id']}
    if before_others != after_others:
        raise RuntimeError('Unrelated enrollment changed')
    summary.update(result='pass', manualMoveSuspends=True, staleIntentRejected=True,
                   sameValueReenables=True, controllerOrderKeepsEnrollment=True,
                   unrelatedEnrollmentUnchanged=True)


def stance_trial(pid, output, action='stance', unit_id=None, destination=None, direction=None, screen_point=None, battle_seconds=None, human_opponents=False):
    import frida
    path_trace = action in {'path_move', 'path_squad_advance', 'path_query', 'path_scan', 'path_follow'}
    # Combat retains full per-observer sensor records, including friendly
    # relationships. Keep a bounded, lossless budget for the 120-second trial.
    # The 96-infantry trial reached 256 MiB after 70 seconds. Larger sensor
    # snapshots need a larger finite budget; never rotate away required evidence.
    evidence = Evidence(output, limit=(2048 if action in {'bot_army_combat', 'bot_battle'} else
                                      64 if action == 'army_objectives' else 16) * 1024 * 1024)
    summary = {'scenario': 'serialized_' + action, 'pid': pid, 'sourceHashes': source_hashes(),
               'scenarioSourceSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'configuration': {'action': action, 'unitId': unit_id, 'destination': destination, 'direction': direction, 'screenPoint': screen_point},
               'synchronization': 'unverified', 'sampleCount': 1}
    session = script = None
    try:
        summary['memoryBeforeAttach'] = diagnostic_memory_check(pid, evidence)
        evidence.write({'stage': 'attach'})
        session = native_call(frida.attach, pid)
        evidence.write({'stage': 'create_script'})
        bridge_source = (ROOT / 'headless/tactical_bridge.js').read_text()
        if human_opponents:
            if action != 'bot_battle':
                raise ValueError('Human opponents require the explicit battle scenario')
            bridge_source = 'const humanOpponentTrial = true;\n' + bridge_source
            summary['humanOpponentsAuthorized'] = True
        script = native_call(session.create_script, bridge_source +
            (PATH_WATCH_JS if path_trace else '') +
            (BOT_TRIAL_JS + '\ncaps.contacts = false;\n' if path_trace else '') +
            (BOT_TRIAL_JS if action in {'bot_army_setup', 'bot_army_combat', 'bot_battle', 'grenade_query'} else '') +
            (PAUSE_TRIAL_JS if action in {'pause', 'pause_watchdog'} else '') +
            (FRIENDLY_RELOAD_JS if action in {'friendly_reload_watch', 'friendly_aim_watch'} else '') +
            (FRIENDLY_AIM_JS if action == 'friendly_aim_watch' else '') +
            (FRIENDLY_COVER_JS if action == 'friendly_cover_watch' else ''))
        script.on('message', lambda message, data: evidence.write({'bridgeMessage': message}))
        evidence.write({'stage': 'load_script'})
        native_call(script.load)
        api = NativeCalls(script.exports_sync)
        summary['executableIdentity'] = executable_identity(api)
        baseline = api.snapshot()
        evidence.write({'baseline': baseline})
        if baseline.get('error') or baseline.get('fault'):
            raise RuntimeError('Baseline unavailable: ' + str(baseline.get('error') or baseline['fault']))
        if path_trace and action in {'path_move', 'path_squad_advance'}:
            action = 'move' if action == 'path_move' else 'squad_advance'
        if action == 'army_objectives':
            army_objectives_trial(api, baseline, evidence, summary)
            return summary
        if action in {'bot_army_combat','bot_battle'}:
            army_combat_trial(api, baseline, evidence, summary, battle=action=='bot_battle', duration=battle_seconds)
            return summary
        if action == 'bot_army_setup':
            army_mode_setup(api, baseline, evidence, summary, bots=True)
            return summary
        if action == 'army_setup':
            army_mode_setup(api, baseline, evidence, summary)
            return summary
        if action in {'pause', 'pause_watchdog'}:
            pause_trial(api, baseline, evidence, summary, watchdog=action == 'pause_watchdog')
            return summary
        if action in {'friendly_reload_watch', 'friendly_aim_watch', 'friendly_cover_watch'}:
            friendly_reload_watch(api, baseline, evidence, summary, aim=action == 'friendly_aim_watch',
                                  cover=action == 'friendly_cover_watch')
            return summary
        if action in {'input', 'posted_input'}:
            input_trial(api, baseline, evidence, summary, posted=action == 'posted_input')
            return summary
        if action == 'manual_move':
            manual_move_trial(api, baseline, evidence, summary, screen_point)
            return summary
        if action == 'reject_unavailable':
            row = next((u for u in baseline['units'] if u['id'] == unit_id), None)
            if unit_id is None or (row and (row['eligible'] or not row['nativeDeadPredicate'])):
                raise RuntimeError('Rejection trial needs an explicit absent or natively dead unit ID')
            reply = api.trialstance({'id': unit_id, 'incarnation': row['incarnation'] if row else 1,
                'generation': baseline['generation'], 'revision': baseline['commandRevision'],
                'sequence': 1, 'action': 'stance', 'stance': 0,
                'requireEnrolled': True, 'unitRevision': row['revision'] if row else 0})
            evidence.write({'ack': reply})
            if not reply.get('rejected'):
                raise RuntimeError('Unavailable unit was not rejected')
            summary.update(result='pass', unavailableUnitRejected=unit_id,
                           nativeDeadPredicate=row['nativeDeadPredicate'] if row else None,
                           confirmedDeath=False, ordersIssued=0)
            return summary
        if action in {'purchase', 'purchase_query'}:
            intent = {'generation': baseline['generation'], 'revision': baseline['commandRevision'],
                      'sequence': 1, 'action': action}
            evidence.write({'intent': intent})
            reply = api.trialstance(intent)
            evidence.write({'ack': reply})
            summary['purchase'] = reply
            if reply.get('error'):
                raise RuntimeError(str(reply))
            if action == 'purchase_query':
                summary['result'] = 'observed'
                return summary
            if reply.get('status') != 'submitted_unconfirmed':
                raise RuntimeError('Purchase was not submitted')
            before = {(u['id'], u['incarnation']) for u in baseline['units']}
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                raw = api.snapshot()
                evidence.write({'observation': raw})
                if raw.get('error') or raw.get('fault') or raw['generation'] != baseline['generation']:
                    raise RuntimeError('Match/bridge changed while purchase was pending')
                spawned = [u for u in raw['units'] if (u['id'], u['incarnation']) not in before]
                if spawned:
                    evidence.write({'completed': 'purchase', 'newOwnedUnits': spawned})
                    summary.update(result='pass', newOwnedUnits=spawned,
                                   simulationSeconds=(raw['simulationTicks'] - baseline['simulationTicks']) / 1000,
                                   resourceAccounting='unverified', attribution='new owned infantry after single purchase')
                    return summary
                time.sleep(.2)
            raise RuntimeError('Purchase completion unobserved; request will not be replayed')
        candidates = [u for u in baseline.get('units', []) if u['eligible']
                      and (not u['squadLeader'] or action in {'sensor_query', 'sensor_watch'})
                      and (unit_id is None or u['id'] == unit_id)
                      and not u['controlLockRaw'] and u['stance'] in (0, 1, 2)]
        if not candidates:
            raise RuntimeError('No eligible owned nonleader infantry')
        unit = candidates[0]
        summary['unit'] = unit
        if action in {'weapon_watch', 'attack'}:
            return weapon_trial(api, baseline, unit, evidence, summary, action)
        if action in {'sensor_watch', 'sensor_approach', 'death_approach'}:
            previous, transitions, max_ms, samples = {}, [], 0, 0
            previous_death, death_transitions = {}, []
            sequence = 0
            destination = None
            if action in {'sensor_approach', 'death_approach'}:
                objectives = [o for o in baseline['objectives'] if o['occupant'] != baseline['team']]
                if not objectives:
                    raise RuntimeError('No unowned mapped objective for the approach trial')
                objective = min(objectives, key=lambda o: dist(unit['position'][:2], o['position'][:2]))
                distance = dist(unit['position'][:2], objective['position'][:2])
                if distance <= 1:
                    raise RuntimeError('Observer already at the mapped objective')
                destination = [unit['position'][i] + (objective['position'][i] - unit['position'][i]) *
                               min(1., 600. / distance) for i in range(2)] + [unit['position'][2]]
                sequence += 1
                intent = {'id': unit['id'], 'incarnation': unit['incarnation'],
                    'generation': baseline['generation'], 'revision': baseline['commandRevision'],
                    'sequence': sequence, 'action': 'move', 'destination': destination}
                evidence.write({'intent': intent, 'sceneObjective': objective['key']})
                reply = api.trialstance(intent)
                evidence.write({'ack': reply})
                if reply.get('status') != 'serialized':
                    raise RuntimeError(str(reply))
            deadline = time.monotonic() + 30
            if action == 'death_approach':
                summary.update(samples=0, nativeDeathTransition=False, disappeared=False)
                initial_dead = unit['nativeDeadPredicate']
                while time.monotonic() < deadline:
                    raw = api.snapshot()
                    evidence.write({'observation': raw})
                    if raw.get('error') or raw.get('fault') or raw['generation'] != baseline['generation']:
                        raise RuntimeError('Death observation lost continuity')
                    summary['samples'] += 1
                    current = next((u for u in raw['units'] if u['id'] == unit['id'] and
                                    u['incarnation'] == unit['incarnation']), None)
                    if current is None:
                        summary.update(disappeared=True, disappearanceTicks=raw['simulationTicks'])
                        break
                    summary['finalPosition'] = current['position']
                    if not initial_dead and current['nativeDeadPredicate'] and not summary['nativeDeathTransition']:
                        summary.update(nativeDeathTransition=True, nativeDeathTicks=raw['simulationTicks'])
                    time.sleep(.1)
                summary.update(result='observed',
                               interpretation='Native predicate transition and disappearance are recorded separately')
                return summary
            while time.monotonic() < deadline:
                samples += 1
                sequence += 1
                reply = api.trialstance({'id': unit['id'], 'incarnation': unit['incarnation'],
                    'generation': baseline['generation'], 'revision': baseline['commandRevision'],
                    'sequence': sequence, 'action': 'sensor_query'})
                evidence.write({'query': reply})
                if reply.get('status') != 'queried':
                    raise RuntimeError(str(reply))
                max_ms = max(max_ms, reply['elapsedMs'])
                for contact in reply['records']:
                    identity = contact['identity']
                    if identity is None:
                        continue
                    key = (identity['id'], identity['incarnation'])
                    current = contact['nativeVisualResult']
                    if key in previous and previous[key] != current:
                        transitions.append({'id': identity['id'], 'incarnation': identity['incarnation'],
                            'nativeVisualResult': current, 'simulationTicks': reply['simulationTicks']})
                    previous[key] = current
                    dead = contact.get('nativeDeadPredicate')
                    if dead is not None:
                        if key in previous_death and previous_death[key] != dead:
                            death_transitions.append({'id': identity['id'], 'incarnation': identity['incarnation'],
                                'nativeDeadPredicate': dead, 'simulationTicks': reply['simulationTicks']})
                        previous_death[key] = dead
                time.sleep(.2)
            summary.update(result='observed', samples=samples, nativeVisualTransitions=transitions,
                           nativeDeathTransitions=death_transitions,
                           maxQueryMs=max_ms, finalPosition=reply['observerPosition'],
                           approachArrived=destination is not None and dist(reply['observerPosition'][:2], destination[:2]) <= 40,
                           visibilitySemantics='native flag only; behavioral gate incomplete')
            return summary
        if action == 'enable':
            reply = api.trialstance({'id': unit['id'], 'incarnation': unit['incarnation'],
                'generation': baseline['generation'], 'revision': baseline['commandRevision'],
                'sequence': 1, 'action': 'mode', 'mode': 0})
            evidence.write({'ack': reply})
            if reply.get('status') != 'serialized':
                raise RuntimeError(str(reply))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                raw = api.snapshot()
                evidence.write({'observation': raw})
                if raw.get('error') or raw.get('fault') or raw['generation'] != baseline['generation']:
                    raise RuntimeError('Opt-in setup lost match/observation continuity')
                current = next((u for u in raw['units'] if u['id'] == unit['id'] and
                                u['incarnation'] == unit['incarnation']), None)
                if current and current['movementBits'] == 0:
                    summary.update(result='pass', modeSetup=True, unitId=unit['id'],
                                   reclamation='unverified; this is diagnostic scene setup')
                    return summary
                time.sleep(.1)
            raise RuntimeError('Opt-in setup timeout; no replay')
        if action == 'lifecycle':
            # Exercise actual script loss, without a stop RPC or any property
            # changes. A new attachment must reject all old intent identities.
            native_call(script.unload)
            script = None
            time.sleep(.3)
            script = native_call(session.create_script, (ROOT / 'headless/tactical_bridge.js').read_text())
            script.on('message', lambda message, data: evidence.write({'bridgeMessage': message}))
            native_call(script.load)
            api = NativeCalls(script.exports_sync)
            after = api.snapshot()
            evidence.write({'afterScriptLoss': after})
            if (after.get('error') or after.get('fault') or
                    after['generation'] == baseline['generation'] or
                    after['simulationTicks'] <= baseline['simulationTicks']):
                raise RuntimeError('Script-loss recovery or identity isolation failed')
            rejected = api.trialstance({'id': unit['id'], 'incarnation': unit['incarnation'],
                'generation': baseline['generation'], 'revision': baseline['commandRevision'],
                'sequence': 1, 'stance': unit['stance']})
            evidence.write({'staleIntentAck': rejected})
            if not rejected.get('rejected'):
                raise RuntimeError('Previous attachment intent was not rejected')
            stopped = api.stop()
            evidence.write({'explicitStop': stopped})
            try:
                api.snapshot()
            except Exception as exc:
                if 'Bridge stopped' not in str(exc):
                    raise
            else:
                raise RuntimeError('Stopped bridge accepted another request')
            summary.update(result='pass', scriptLossRecovered=True, simulationContinued=True,
                           staleAttachmentRejected=True, stoppedRequestsRejected=True,
                           ordersIssued=0)
            return summary
        if action == 'handoff':
            handoff_trial(api, baseline, unit, evidence, summary)
            return summary
        if action == 'mode':
            original = unit['movementBits'] >> 12
            if original not in (0, 1):
                raise RuntimeError('Unsupported original movement mode')
            for sequence, mode in enumerate((1, 0, 0, original), 1):
                current = api.snapshot()
                reply = api.trialstance({'id': unit['id'], 'incarnation': unit['incarnation'],
                    'generation': baseline['generation'], 'revision': current['commandRevision'],
                    'sequence': sequence, 'action': 'mode', 'mode': mode, 'asPlayerCommand': True})
                evidence.write({'mode': mode, 'ack': reply})
                if reply.get('status') != 'serialized':
                    raise RuntimeError(str(reply))
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    observed = api.snapshot()
                    evidence.write({'observation': observed})
                    found = next((u for u in observed.get('units', []) if u['id'] == unit['id']
                                  and u['incarnation'] == unit['incarnation']), None)
                    event = any(e['kind'] == 'mode_setter' and e['id'] == unit['id'] and e['mode'] == mode
                                for e in observed.get('events', []))
                    if found and found['movementBits'] == mode << 12 and event and found['enrolled'] == (mode == 0):
                        break
                    time.sleep(.1)
                else:
                    raise RuntimeError('Mode state/event timeout; no replay')
            summary.update(result='pass', restored=True, sameValueModeEvent=True)
            return summary
        if action in {'objective', 'combat_approach', 'attack_approach'}:
            objective_trial(api, baseline, unit, evidence, summary, combat_observation=action != 'objective',
                            attack_on_contact=action == 'attack_approach')
            return summary
        if action == 'squad_advance':
            squad_advance_trial(api, baseline, unit, evidence, summary)
            return summary
        if action in {'barricade', 'barricade_cancel'}:
            barricade_trial(api, baseline, unit, evidence, summary, destination, cancel=action == 'barricade_cancel', direction=direction)
            return summary
        if action == 'path_follow':
            if destination is None:
                raise RuntimeError('Path-follow trial requires an explicit nearby destination')
            identity = dict(id=unit['id'],incarnation=unit['incarnation'],generation=baseline['generation'],
                revision=baseline['commandRevision'],requireEnrolled=True,unitRevision=unit['revision'])
            query = api.trialstance({**identity,'sequence':1,'action':'path_query','destination':destination})
            evidence.write({'pathPreflight':query})
            if query.get('status') != 'queried' or not query.get('vectorReleased'):
                raise RuntimeError('Path preflight unavailable: ' + str(query))
            summary['pathQuery'] = query
            if not query['reachesRequestedPoint']:
                summary.update(result='pass',ordersIssued=0,routeRefused=True,
                    gateScope='Native path did not reach requested endpoint; no move submitted')
                return summary
            reply = api.trialstance({**identity,'sequence':2,'action':'move','destination':destination})
            evidence.write({'ack':reply})
            if reply.get('status') != 'serialized':
                raise RuntimeError('Path follow move unconfirmed; no replay: ' + str(reply))
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                raw = api.snapshot()
                evidence.write({'observation':raw})
                current = next((u for u in raw.get('units',[]) if u['id']==unit['id'] and u['incarnation']==unit['incarnation']),None)
                if (raw.get('error') or raw.get('fault') or raw.get('generation') != baseline['generation'] or
                        not raw.get('playing') or not current or not current['eligible'] or not current['enrolled'] or
                        current['revision'] != unit['revision']):
                    raise RuntimeError('Path follow yielded to identity/authority/match change')
                if dist(current['position'][:2],destination[:2]) <= 40:
                    summary.update(result='pass',ordersIssued=1,routeRefused=False,finalPosition=current['position'],
                        elapsedSimulationSeconds=(raw['simulationTicks']-baseline['simulationTicks'])/1000.,
                        gateScope='Native path query followed by observed owned-unit arrival; no replication claim')
                    return summary
                time.sleep(.2)
            raise RuntimeError('Path follow arrival unobserved; no replay')
        if action == 'path_scan':
            queries = []
            for sequence in range(1,18):
                angle = (sequence - 2) * pi / 8
                point = unit['position'] if sequence == 1 else [unit['position'][0] + 580 * cos(angle),
                    unit['position'][1] + 580 * sin(angle),unit['position'][2]]
                reply = api.trialstance(dict(id=unit['id'],incarnation=unit['incarnation'],
                    generation=baseline['generation'],revision=baseline['commandRevision'],
                    sequence=sequence,action='path_query',destination=point))
                evidence.write({'query':reply})
                if reply.get('status') != 'queried' or not reply.get('vectorReleased'):
                    raise RuntimeError('Path scan query or release unavailable: ' + str(reply))
                queries.append(reply)
            after = api.snapshot()
            evidence.write({'afterPathScan':after})
            if after.get('error') or after.get('fault') or after['generation'] != baseline['generation']:
                raise RuntimeError('Path scan observation continuity lost')
            summary.update(result='observed',queries=queries,
                reachableQueryCount=sum(q['reachesRequestedPoint'] for q in queries),
                nonmatchingQueryCount=sum(not q['reachesRequestedPoint'] for q in queries),
                ordersIssued=0,gateScope='Bounded nearby native path results and cleanup; no travel or blocked-route completion claim')
            return summary
        if action == 'grenade_query':
            queries=[]
            for sequence,kind in enumerate(('fragmentation','smoke','anti_tank'),1):
                query=api.trialstance(dict(id=unit['id'],incarnation=unit['incarnation'],
                    generation=baseline['generation'],revision=baseline['commandRevision'],
                    sequence=sequence,action='grenade_query',grenadeKind=kind))
                evidence.write({'query':query})
                if query.get('status')!='queried' or query.get('grenadeKind')!=kind:
                    raise RuntimeError('Grenade inventory observation failed: '+str(query))
                queries.append(query)
            summary.update(result='observed',grenadeInventory=queries,ordersIssued=0,
                gateScope='Native inventory availability only; throws and effects remain unverified')
            return summary
        if action in {'path_query', 'cover_query', 'cover_scored_query', 'sensor_query', 'attack_query', 'weapon_query', 'barricade_query', 'purchase_query'}:
            reply = api.trialstance({'id': unit['id'], 'incarnation': unit['incarnation'],
                'generation': baseline['generation'], 'revision': baseline['commandRevision'],
                'sequence': 1, 'action': action,
                **({'destination': destination or unit['position']} if action == 'path_query' else {}),
                **({'destination': destination} if action in {'cover_query', 'cover_scored_query'} and destination is not None else {})})
            evidence.write({'query': reply})
            if reply.get('status') != 'queried':
                raise RuntimeError(str(reply))
            summary['query'] = reply
            summary['result'] = 'observed'
            return summary
        native_sequence, selected_cover = 0, None
        if action in {'cover', 'scored_cover'}:
            native_sequence += 1
            query = api.trialstance({'id': unit['id'], 'incarnation': unit['incarnation'],
                'generation': baseline['generation'], 'revision': baseline['commandRevision'],
                'sequence': native_sequence, 'action': 'cover_scored_query' if action == 'scored_cover' else 'cover_query',
                **({'destination': destination} if destination is not None else {})})
            evidence.write({'query': query})
            if query.get('status') != 'queried':
                raise RuntimeError('Cover selection query failed: ' + str(query))
            selected_cover = next((c for c in query['candidates'] if c['found'] and c['sourceIdentity']), None)
            if selected_cover is None:
                raise RuntimeError('No source-identified cover candidate')
            summary['selectedCover'] = selected_cover
            summary['selectionQuery'] = query
            action = 'cover'
        for sequence, stance in ((1, (unit['stance'] + 1) % 3), (2, unit['stance'])):
            current = api.snapshot()
            if current.get('generation') != baseline['generation']:
                raise RuntimeError('Match changed; no further orders')
            native_sequence += 1
            intent = {'id': unit['id'], 'incarnation': unit['incarnation'], 'generation': baseline['generation'],
                      'revision': current['commandRevision'], 'sequence': native_sequence, 'stance': stance,
                      'action': action}
            if action == 'move':
                intent['destination'] = list(unit['position'])
                if sequence == 1:
                    intent['destination'][0] += 15
            if action == 'cover' and sequence == 2:
                intent['action'] = 'move'
                intent['destination'] = list(unit['position'])
            if action == 'cover' and sequence == 1:
                intent['destination'] = selected_cover['position'] + [unit['position'][2]]
                intent['coverSource'] = selected_cover['sourceIdentity']
            evidence.write({'intent': intent})
            reply = api.trialstance(intent)
            evidence.write({'ack': reply})
            if reply.get('error') or reply.get('status') != 'serialized':
                raise RuntimeError('Serialization failed: ' + str(reply))
            deadline = time.monotonic() + 8
            passed = False
            while time.monotonic() < deadline:
                observation = api.snapshot()
                evidence.write({'observation': observation})
                match = observation.get('generation') == baseline['generation']
                observed_unit = next((u for u in observation.get('units', []) if u['id'] == unit['id']
                                      and u['incarnation'] == unit['incarnation']), None)
                if not match or not observed_unit or not observed_unit['eligible']:
                    raise RuntimeError('Unit/match invalidated during trial')
                if action in {'move', 'cover'}:
                    destination = reply['destination']
                    distance = sum((observed_unit['position'][i] - destination[i]) ** 2
                                   for i in range(2)) ** .5
                    complete = distance <= 3
                    if action == 'cover' and sequence == 1:
                        complete = distance <= 30 and observed_unit['coverState'] in (1, 2)
                else:
                    complete = observed_unit['stance'] == stance
                if complete and observation['simulationTicks'] > current['simulationTicks']:
                    passed = True
                    break
                time.sleep(.2)
            if not passed:
                raise RuntimeError(f"{intent['action']} completion timeout; intent will not be replayed")
            summary['restored' if sequence == 2 else 'changed'] = True
        summary['result'] = 'pass'
        if summary['scenario'] == 'serialized_scored_cover':
            summary['gateScope'] = 'Native scored cover selection, arrival and return; suitability and replication unverified'
    except BaseException as exc:
        summary['result'], summary['error'] = 'failed', str(exc)
        raise
    finally:
        if script:
            try:
                summary['stop'] = native_call(script.exports_sync.stop)
            except Exception as exc:
                summary['stopError'] = str(exc)
        if session:
            try:
                native_call(session.detach)
            except Exception as exc:
                summary['detachError'] = str(exc)
        reader = None
        try:
            reader, reference = Reader(pid), Image()
            summary['postDetachCode'] = {}
            for address in (0x7105a0, 0x715c60, 0x715b60, 0x9dacb0, 0x830f90, 0x8e8c80, 0xaaa1a0, 0xaaa6f0, 0xaa9b20, 0x85cc30, 0x794120, 0x9dc350):
                expected = reference.data[reference.offset(address):reference.offset(address) + 16]
                summary['postDetachCode'][hex(address)] = reader.read(address, 16) == expected
            if path_trace:
                for address in (0x8c3c40,0x8b2740):
                    expected = reference.data[reference.offset(address):reference.offset(address) + 16]
                    summary['postDetachCode'][hex(address)] = reader.read(address, 16) == expected
            if action in {'friendly_reload_watch', 'friendly_aim_watch'}:
                for address in (0x845050, 0x8454c0, 0x844650):
                    expected = reference.data[reference.offset(address):reference.offset(address) + 16]
                    summary['postDetachCode'][hex(address)] = reader.read(address, 16) == expected
            if action in {'friendly_aim_watch', 'friendly_cover_watch'}:
                address = 0x851330 if action == 'friendly_aim_watch' else 0x8a75a0
                expected = reference.data[reference.offset(address):reference.offset(address) + 16]
                summary['postDetachCode'][hex(address)] = reader.read(address, 16) == expected
            if action == 'friendly_aim_watch':
                for address in (0x84d8a0, 0x84d0a0):
                    expected = reference.data[reference.offset(address):reference.offset(address) + 16]
                    summary['postDetachCode'][hex(address)] = reader.read(address, 16) == expected
        except Exception as exc:
            summary['postDetachError'] = str(exc)
        finally:
            if reader:
                reader.close()
        evidence.close(summary)
    return summary


def collect_battle_result(pid, output, summary):
    """Use the durable host guard only after the tactical attachment is gone."""
    if summary.get('matchCompleted') is not True:
        return
    restored = summary.get('postDetachCode', {})
    if (summary.get('stop', {}).get('stopped') is not True or
            any(summary.get(key) for key in ('error', 'stopError', 'detachError', 'postDetachError')) or
            len(restored) != 12 or not all(value is True for value in restored.values())):
        summary['resultCollection'] = {'status': 'withheld', 'reason': 'Tactical detach not verified'}
        summary['outcome'] = 'unknown'
        (output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        return
    # finish-ai rechecks the durable process/session/lobby/epoch and terminal UI.
    # Its success alone is not a win; the normalized native score is authoritative.
    try:
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'headless_host.py'),
            'finish-ai', '--pid', str(pid), '--evidence-root', str(output / 'completion')],
            capture_output=True, text=True, timeout=60)
        (output / 'result_collection.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        summary['resultCollection'] = {'status': 'captured' if result.returncode == 0 else 'failed',
            'returncode': result.returncode, 'evidence': str(output / 'completion')}
    except (OSError, subprocess.TimeoutExpired) as exc:
        summary['resultCollection'] = {'status': 'failed', 'error': str(exc), 'replayed': False}
    (output / 'result_collection.json').write_text(json.dumps(summary['resultCollection'], indent=2), encoding='utf-8')
    # A successful CLI exit only establishes collection. Read the guarded
    # native terminal result and retain its durable match identity separately.
    summary['outcome'] = 'unknown'
    candidates = list((output / 'completion').glob('*/completion_normalized.json'))
    if len(candidates) == 1 and summary['resultCollection']['status'] == 'captured':
        try:
            path = candidates[0]
            normalized = json.loads(path.read_text(encoding='utf-8'))
            raw = json.loads(path.with_name('completion_raw.json').read_text(encoding='utf-8'))
            match = json.loads(path.with_name('match_observation.json').read_text(encoding='utf-8'))
            if (not raw.get('match_id') or raw['match_id'] != match.get('match_id') or
                    not raw.get('native_game_start_time') or
                    raw.get('native_game_start_time') != match.get('native_game_start_time')):
                raise ValueError('Completion identity differs from durable match')
            if (summary.get('battleNativeStartTime') is not None and
                    str(raw['native_game_start_time']) != str(summary['battleNativeStartTime'])):
                raise ValueError('Completion identity differs from observed battle')
            winner = normalized.get('engine_outcome', {}).get('winning_team')
            if winner not in {'a', 'b'} or summary.get('localTeam') not in {'a', 'b'}:
                raise ValueError('No supported native winner/local team')
            summary.update(outcome='victory' if winner == summary['localTeam'] else 'defeat',
                matchId=raw['match_id'], terminalScore=normalized,
                terminalScoreEvidence=str(path))
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            summary['outcomeReason'] = str(exc)
    # Persist the verified score before attempting lobby cleanup. Cleanup failure
    # cannot erase a captured outcome or justify replaying an uncertain command.
    (output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    if summary['outcome'] in {'victory', 'defeat'}:
        try:
            cleanup = subprocess.run([sys.executable, '-B', str(ROOT / 'headless_host.py'),
                'save-ai-results', '--pid', str(pid), '--evidence-root', str(output / 'cleanup')],
                capture_output=True, text=True, timeout=60)
            (output / 'result_cleanup.log').write_text(cleanup.stdout + cleanup.stderr, encoding='utf-8')
            summary['resultCleanup'] = {'status': 'saved' if cleanup.returncode == 0 else 'failed',
                'returncode': cleanup.returncode, 'evidence': str(output / 'cleanup')}
        except (OSError, subprocess.TimeoutExpired) as exc:
            summary['resultCleanup'] = {'status': 'failed', 'error': str(exc), 'replayed': False}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', choices=['grenade_query', 'bot_battle', 'performance', 'policy_scale', 'path_follow', 'path_scan', 'path_query', 'path_move', 'path_squad_advance', 'bot_army_setup', 'bot_army_combat', 'army_setup', 'army_objectives', 'stance', 'move', 'cover', 'scored_cover', 'cover_query', 'cover_scored_query', 'sensor_query', 'attack_query', 'attack', 'sensor_watch', 'sensor_approach', 'death_approach', 'weapon_query', 'weapon_watch', 'barricade_query', 'barricade', 'barricade_cancel', 'purchase_query', 'purchase', 'enable', 'objective', 'combat_approach', 'attack_approach', 'squad_advance', 'mode', 'handoff', 'input', 'manual_move', 'posted_input', 'lifecycle', 'reject_unavailable', 'pause', 'pause_watchdog', 'friendly_reload_watch', 'friendly_aim_watch', 'friendly_cover_watch'])
    parser.add_argument('--pid', type=int, help='Required for native trials; unused by policy_scale')
    parser.add_argument('--unit', help='Owned native unit ID; default is first eligible nonleader')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--destination', nargs=3, type=float, help='Nearby path endpoint, barricade placement or cover-query center')
    parser.add_argument('--direction', nargs=2, type=float, help='Barricade direction vector; normalized by the bridge')
    parser.add_argument('--screen-point', nargs=2, type=int, help='Verified visible ground point in game client pixels for manual_move')
    parser.add_argument('--baseline-bridge', type=Path, help='Previous bridge source for performance comparison only')
    parser.add_argument('--battle-seconds', type=float, help='Bound bot_battle wall time (1..1800 seconds); default 1800')
    parser.add_argument('--human-opponents', action='store_true', help='Explicitly authorize control of local host army against human opponents; bot_battle only')
    args = parser.parse_args()
    if args.human_opponents and args.scenario != 'bot_battle':
        parser.error('--human-opponents requires bot_battle')
    if args.battle_seconds is not None and (args.scenario != 'bot_battle' or not 1 <= args.battle_seconds <= 1800):
        parser.error('--battle-seconds requires bot_battle and a duration of 1..1800 seconds')
    if args.baseline_bridge is not None and args.scenario != 'performance':
        parser.error('--baseline-bridge applies only to performance')
    if args.scenario != 'policy_scale' and args.pid is None:
        parser.error('--pid is required for native trials')
    if (args.screen_point is not None) != (args.scenario == 'manual_move'):
        parser.error('--screen-point is required only for manual_move')
    if args.direction is not None and args.scenario not in {'barricade', 'barricade_cancel'}:
        parser.error('--direction applies only to barricade trials')
    if args.destination is not None and args.scenario not in {'path_query', 'path_follow', 'barricade', 'barricade_cancel', 'cover_query', 'cover_scored_query', 'scored_cover'}:
        parser.error('--destination applies only to path, barricade and cover trials')
    output = args.output or ROOT / 'validation' / ('tactical_scenario_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
    try:
        summary = (performance_trial(args.pid, output, args.baseline_bridge) if args.scenario == 'performance' else
            policy_scale_trial(output) if args.scenario == 'policy_scale' else
            stance_trial(args.pid, output, args.scenario, args.unit, args.destination, args.direction, args.screen_point, args.battle_seconds, args.human_opponents))
        if args.scenario == 'bot_battle' and not args.human_opponents:
            collect_battle_result(args.pid, output, summary)
        print(json.dumps(summary))
    except Exception as exc:
        print(str(exc))
        return 1
    finally:
        print('Evidence: ' + str(output))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
