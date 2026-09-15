"""Standalone tactical observation CLI and bounded intent lifecycle.

Run mode fails closed until the native adapter's validation gates pass.
"""
import argparse
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from math import dist, isfinite
from pathlib import Path
import threading
import time

from tactical_policy import Contact, Cover, Event, Identity, Objective, Policy, Snapshot, Unit

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_EXECUTABLE = '3bc956732844aab0f4028cafecc74a9c0fc73abd6afc618bad5c4e9de537e64f'


def native_call(function, *args, timeout=5.):
    """Cancel blocked transport calls; an expired action must never be replayed."""
    import frida
    cancellation = frida.Cancellable()
    timer = threading.Timer(timeout, cancellation.cancel)
    timer.daemon = True
    timer.start()
    try:
        with cancellation:
            return function(*args)
    except frida.OperationCancelledError as error:
        raise TimeoutError('Tactical native call timed out; outcome uncertain, no replay') from error
    finally:
        timer.cancel()


class NativeCalls:
    def __init__(self, api):
        self.api = api

    def __getattr__(self, name):
        function = getattr(self.api, name)
        return lambda *args: native_call(function, *args)


class NativeAdapter:
    """Translate verified native fields; unsupported tactical capabilities stay off.

    Move/stance have observed completion contracts; attack serialization is
    separate from completion. This
    adapter does not promote bridge capability gates or decode raw sensor flags.
    """
    def __init__(self, api, evidence):
        self.api, self.evidence = api, evidence
        self.raw = None
        self.rows, self.previous = {}, {}
        self.contacts = ()
        self.events = []
        self.last_shots = {}
        self.contact_samples = {}
        self.sequence = 0
        self.cover_candidates = {}
        self.cover_after = {}
        self.cover_query_after = 0.
        self.leader_follow_after = {}
        self.move_progress = {}

    def snapshot(self, raw):
        if raw.get('error') or raw.get('fault'):
            raise RuntimeError(raw.get('error') or raw['fault'])
        if raw.get('playing') is not True:
            raise RuntimeError('Supported match is not active')
        match, owner, ticks = raw['generation'], raw['owner'], raw['simulationTicks']
        if not isinstance(match, str) or not match or not isinstance(owner, str) or not owner:
            raise ValueError('Invalid native authority identity')
        if type(ticks) is not int or ticks < 0 or type(raw['paused']) is not bool:
            raise ValueError('Invalid native simulation state')
        if len(raw['units']) > Policy.MAX_UNITS or len(raw['events']) + len(self.events) > 4096:
            raise ValueError('Native observation budget exceeded')
        if self.raw and self.raw['generation'] != match:
            self.previous.clear()
            self.events.clear()
            self.last_shots.clear()
            self.contact_samples.clear()
            self.cover_candidates.clear()
            self.cover_after.clear()
            self.cover_query_after = 0.
            self.leader_follow_after.clear()
            self.move_progress.clear()
        rows, units, events, previous = {}, [], [], {}
        caps = raw['capabilities']
        shots = dict(self.last_shots) if caps.get('shotEvents') is True else {}
        if caps.get('shotEvents') is True:
            for event in self.events + raw['events']:
                if event['kind'] != 'bullet_created':
                    continue
                stamp = event['simulationTicks']
                if (type(stamp) is not int or not 0 <= stamp <= ticks or
                        not isinstance(event.get('id'), str) or not event['id'] or
                        type(event.get('incarnation')) is not int or event['incarnation'] < 1):
                    raise ValueError('Invalid native shot timestamp')
                identity = Identity(match, event['id'], event['incarnation'])
                if ticks - stamp <= 1000:
                    shots[identity] = max(stamp, shots.get(identity, -1))
        for row in raw['units']:
            identity = Identity(match, row['id'], row['incarnation'])
            if row['owner'] != owner or identity in rows:
                raise ValueError('Foreign or duplicate native unit')
            if type(row['eligible']) is not bool or type(row['enrolled']) is not bool:
                raise ValueError('Invalid native enrollment state')
            if type(row['revision']) is not int or row['revision'] < 0:
                raise ValueError('Invalid native unit revision')
            rows[identity] = row
            if not row['eligible']:
                continue  # Ineligibility is not itself a death event.
            if row['nativeDeadPredicate'] is not False:
                raise ValueError('Eligible native unit has ambiguous death state')
            if (type(row['stance']) is not int or not 0 <= row['stance'] <= 255 or
                    len(row['position']) != 3 or not all(isfinite(v) for v in row['position'])):
                raise ValueError('Invalid native stance/position')
            stance = {0: 'standing', 1: 'crouched', 2: 'prone'}.get(row['stance'])
            if stance is None:
                # An unmapped posture is a per-unit limitation, not evidence of
                # death or a reason to stop unrelated squads. Omit it from policy
                # control until a supported state is observed again.
                continue
            members = row['squadMembers']
            if len(members) > 128:
                raise ValueError('Native squad budget exceeded')
            squad = min(members, key=int) if members else row['id']
            individual = row.get('individualOrder', not row['squadLeader'])
            if type(individual) is not bool:
                raise ValueError('Invalid native command scope')
            if type(row.get('controllerGroup', False)) is not bool:
                raise ValueError('Invalid controller group provenance')
            opted = row['enrolled'] and (row['movementBits'] == 0 or self._controller_group(row, caps)) and individual
            ammo, readiness = self.ammunition(row, caps, ticks)
            cover_state = row.get('coverState')
            if cover_state is not None and (type(cover_state) is not int or not 0 <= cover_state <= 0xffffffff):
                raise ValueError('Invalid native cover state')
            # Only states exercised by the native cover arrival trial are
            # interpreted. Distance or a prone posture alone is not occupation.
            in_cover = True if cover_state in (1, 2) else False if cover_state == 0 else None
            weapon_model = (row.get('ammunition') or {}).get('weaponModel') if caps.get('ammoLoading') is True else None
            projectile_model = (row.get('ammunition') or {}).get('projectileModel') if caps.get('ammoLoading') is True else None
            if projectile_model is not None and (not isinstance(projectile_model, str) or not 1 <= len(projectile_model) <= 128):
                raise ValueError('Invalid native projectile model')
            if weapon_model is not None and (not isinstance(weapon_model, str) or not 1 <= len(weapon_model) <= 128):
                raise ValueError('Invalid native weapon model')
            # An attributed projectile is evidence of recent firing, not settled
            # aim or readiness. Preserve one conservative second of native work;
            # mapped reloading and urgent policy withdrawal still take priority.
            if readiness in {'unknown', 'ready'} and identity in shots and 0 <= ticks - shots[identity] <= 1000:
                readiness = 'firing'
            units.append(Unit(identity, owner, squad, tuple(v / 20. for v in row['position'][:2]),
                move_at_will=opted, direct_control=bool(row['controlLockRaw']), stance=stance,
                ammo=ammo, readiness=readiness, weapon_model=weapon_model, projectile_model=projectile_model,
                in_cover=in_cover, squad_leader=row['squadLeader']))
            current = (row['revision'], opted)
            old = self.previous.get(identity)
            if old is not None and current != old and opted:
                # A same-value explicit reenable must cancel stale policy work.
                events.append(Event(f'enrollment:{identity.unit}:{identity.incarnation}:{row["revision"]}',
                    'mode', (identity,), mode='move_at_will'))
            previous[identity] = current
        if caps.get('death') is True:
            for event in self.events + raw['events']:
                if event['kind'] == 'owned_death':
                    identity = Identity(match, event['id'], event['incarnation'])
                    events.append(Event(f'native:{event["key"]}', 'allied_death', (identity,),
                        origin='native', position=tuple(v / 20. for v in event['position'][:2]), confirmed=True,
                        observed_at=event['simulationTicks'] / 1000.))
        objectives = ()
        if caps.get('objectives') is True:
            if not raw['team'] or len(raw['objectives']) > 128:
                raise ValueError('Invalid native objectives/team')
            for objective in raw['objectives']:
                radius = objective.get('captureRadius')
                if radius is not None and (type(radius) not in (int, float) or not isfinite(radius) or radius <= 0):
                    raise ValueError('Invalid native capture radius')
            objectives = tuple(Objective(o['key'], tuple(v / 20. for v in o['position'][:2]),
                owner if o['occupant'] == raw['team'] else (o['occupant'] or None), reachable=o['reachable'],
                capture_radius=o['captureRadius']/20. if o.get('captureRadius') is not None else None)
                for o in raw['objectives'])
        contacts, contact_identities = (self._contacts(raw, rows)
            if caps.get('contacts') is True and caps.get('death') is True else ((), ()))
        units = [replace(unit, covering=(unit.readiness in {'ready', 'firing'} and
            unit.ammo is not None and unit.ammo > 0 and not Policy._anti_armor(unit) and
            any(contact.enemy is True and not contact.dead and contact.visible and
                0 <= ticks / 1000. - contact.observed_at <= contact.fresh_for and
                contact.visible_to is not None and unit.identity in contact.visible_to and
                dist(unit.position, contact.position) <= 100 for contact in contacts))) for unit in units]
        self.cover_candidates = {key: item for key, item in self.cover_candidates.items()
            if item['observer'] in rows and rows[item['observer']]['eligible'] and
            rows[item['observer']]['enrolled'] and rows[item['observer']]['revision'] == item['revision'] and
            ticks / 1000. <= item['expires'] and not any(event.get('kind') == 'cover_source_invalidated' and
                event.get('entityId') == item['source']['entityId'] for event in self.events + raw['events'])}
        covers = tuple(Cover(key, item['position'], reachable=True,
            occupied=any(other.identity != item['observer'] and dist(other.position, item['position']) < 3
                         for other in units), native_score=item['score'], observer=item['observer'])
            for key, item in self.cover_candidates.items()) if caps.get('nativeCover') is True else ()
        snapshot = Snapshot(match, ticks / 1000., owner, tuple(units), objectives=objectives, covers=covers,
            contacts=contacts, contact_identities=contact_identities,
            events=tuple(events), paused=raw['paused'],
            capabilities=frozenset(action for action in ('move', 'stance', 'attack') if caps.get(action) is True
                and (action != 'attack' or caps.get('contacts') is True and caps.get('death') is True)) |
                (frozenset({'path'}) if caps.get('pathQuery') is True else frozenset()) |
                (frozenset({'cover', 'nativeCover'}) if caps.get('nativeCover') is True else frozenset()))
        self.raw, self.rows, self.previous, self.events = raw, rows, previous, []
        self.last_shots = {identity: stamp for identity, stamp in shots.items()
            if identity in rows and rows[identity]['eligible'] and 0 <= ticks - stamp <= 1000}
        self.contacts = contacts
        self.leader_follow_after = {identity: until for identity, until in self.leader_follow_after.items() if identity in rows}
        return snapshot

    def prepare_cover(self, snapshot, policy):
        """One bounded native selection/path probe; results enter the next snapshot."""
        if (self.raw['capabilities'].get('nativeCover') is not True or snapshot.paused or
                snapshot.time < self.cover_query_after):
            return
        self.cover_query_after = snapshot.time + 1.
        self.cover_after = {identity: stamp for identity, stamp in self.cover_after.items() if identity in self.rows}
        choices = []
        for unit in snapshot.units:
            member = policy.members.get(unit.identity)
            if (not member or not member.enrolled or unit.direct_control or
                    self.cover_after.get(unit.identity, 0) > snapshot.time):
                continue
            if not (any(dist(unit.position, objective.position) <= 60 for objective in snapshot.objectives) or
                    any(contact.enemy is True and not contact.dead and
                        0 <= snapshot.time - contact.observed_at <= contact.fresh_for and
                        dist(unit.position, contact.position) <= 90 for contact in snapshot.contacts)):
                continue  # Spend the query budget near fighting/objectives, not at spawn.
            action = member.action
            if action and (action.action not in {'move', 'attack'} or action.reason == 'withdraw'):
                continue
            destination = action.destination if action and action.action == 'move' else unit.position
            if destination is not None:
                choices.append((self.cover_after.get(unit.identity, 0), unit.identity, destination))
        if not choices:
            return
        _, identity, destination = min(choices)
        self.cover_after[identity] = snapshot.time + 15.
        row = self.rows[identity]
        options = dict(id=identity.unit, incarnation=identity.incarnation, generation=identity.match,
            revision=self.raw['commandRevision'], requireEnrolled=True, unitRevision=row['revision'],
            submitBeforeTicks=(snapshot.time + .75) * 1000.)
        def query(action, point):
            self.sequence += 1
            result = self.api.trialstance(dict(options, sequence=self.sequence, action=action, destination=point))
            self.evidence.write({'nativeCoverProbe': action, 'observer': asdict(identity), 'query': result})
            self._submission_events(result)
            if result.get('status') != 'queried':
                if result.get('rejected') is True:
                    return None
                raise RuntimeError('Uncertain native cover query')
            observer = result.get('observerIdentity', {})
            stamp = result.get('simulationTicks')
            if (result.get('generation') != identity.match or observer.get('id') != identity.unit or
                    observer.get('incarnation') != identity.incarnation or observer.get('owner') != row['owner'] or
                    type(stamp) is not int or stamp < self.raw['simulationTicks']):
                raise RuntimeError('Invalid native cover query authority/clock')
            return result if stamp < options['submitBeforeTicks'] else None
        center = [v * 20. for v in destination] + [row['position'][2]]
        report = query('cover_scored_query', center)
        if report is None:
            return
        if (report.get('requestVectorReleased') is not True or
                report.get('ranking') != 'native-weighted-score-descending' or
                not isinstance(report.get('candidates'), list) or len(report['candidates']) > 8):
            raise RuntimeError('Invalid native cover ranking/release')
        candidate = next((c for c in report['candidates'] if c.get('sourceIdentity')), None)
        if candidate is None:
            return
        position, source = candidate.get('position'), candidate['sourceIdentity']
        score = candidate.get('nativeAssessment', {}).get('weightedScore')
        if (not isinstance(position, list) or len(position) != 2 or not all(isfinite(v) for v in position) or
                type(score) not in (int, float) or not isfinite(score) or source.get('generation') != identity.match or
                type(source.get('entityId')) is not int or not 0 <= source['entityId'] < 0xffff or
                type(source.get('incarnation')) is not int or source['incarnation'] < 1):
            raise RuntimeError('Invalid native cover candidate')
        if dist(position, row['position'][:2]) > (Policy.MAX_MOVE_LEG + 3) * 20:
            return
        path = query('path_query', position + [row['position'][2]])
        if path is None:
            return
        if path.get('vectorReleased') is not True:
            raise RuntimeError('Native cover path vector not released')
        if path.get('reachesRequestedPoint') is not True:
            return
        points = [path.get(key) for key in ('destination', 'origin', 'endpoint', 'startpoint')]
        if (path.get('nativeSucceeded') is not True or path.get('partial') is not False or
                any(not isinstance(p, (list, tuple)) or len(p) != 2 or not all(isfinite(v) for v in p) for p in points) or
                dist(points[0], position) > .01 or dist(points[2], position) > 3 or dist(points[3], points[1]) > 3):
            raise RuntimeError('Invalid native cover path endpoints')
        key = f"{source['entityId']}:{source['incarnation']}:{position[0]:.1f}:{position[1]:.1f}"
        if key not in self.cover_candidates and len(self.cover_candidates) >= Policy.MAX_COVERS:
            return
        if key in self.cover_candidates and self.cover_candidates[key]['observer'] != identity:
            return
        self.cover_candidates[key] = dict(observer=identity, revision=row['revision'], source=source,
            position=tuple(v / 20. for v in position), score=score, expires=snapshot.time + 65.)

    def control_coverage(self):
        """Explain native eligibility gaps without calling them player actions."""
        outside = Counter()
        eligible = controlled = 0
        for row in self.rows.values():
            if not row['eligible']:
                continue
            eligible += 1
            if row['controlLockRaw']:
                outside['direct control'] += 1
            elif not row.get('individualOrder', not row['squadLeader']):
                outside['native group scope'] += 1
            elif row['stance'] not in (0, 1, 2):
                outside['unmapped posture'] += 1
            elif row['movementBits'] and not self._controller_group(row, self.raw['capabilities']):
                outside[{0x1000: 'hold position', 0x2000: 'native group movement mode'}.get(
                    row['movementBits'], 'unmapped movement mode')] += 1
            elif not row['enrolled']:
                outside['not enrolled'] += 1
            else:
                controlled += 1
        return dict(eligibleOwned=eligible, individualControl=controlled, outsideIndividualControl=dict(outside))

    @staticmethod
    def _controller_group(row, caps):
        return (caps.get('leaderFollow') is True and row.get('controllerGroup') is True and
                row['movementBits'] == 0x2000)

    @staticmethod
    def ammunition(row, caps, ticks):
        ammo, readiness = None, 'unknown'
        ammunition = row.get('ammunition') if caps.get('ammoLoading') is True else None
        if ammunition is not None:
            if (type(ammunition.get('simulationTicks')) is not int or ammunition['simulationTicks'] != ticks or
                    type(ammunition.get('ammoCount')) is not int or not 0 <= ammunition['ammoCount'] <= 10000 or
                    type(ammunition.get('nativeLoading')) is not bool):
                raise ValueError('Invalid or stale native ammunition observation')
            ammo = ammunition['ammoCount']
            if ammunition['nativeLoading']:
                readiness = 'reloading'
            fire = ammunition.get('fireState') if caps.get('weaponReadiness') is True else None
            if fire is not None:
                if (type(fire.get('nativeFirePredicate')) is not bool or
                        type(fire.get('placementStateRaw')) is not int or not 0 <= fire['placementStateRaw'] <= 255 or
                        type(fire.get('readinessCandidate')) is not bool or fire['readinessCandidate'] !=
                        (fire['nativeFirePredicate'] and fire['placementStateRaw'] in (3, 4)) or
                        fire['nativeFirePredicate'] and (ammo == 0 or ammunition['nativeLoading'])):
                    raise ValueError('Invalid native firing readiness')
                if fire['readinessCandidate']:
                    readiness = 'ready'
        return ammo, readiness

    def _contacts(self, raw, rows):
        reports = raw.get('perception', ())
        encoding = raw.get('perceptionEncoding')
        if encoding not in (None, 'tuple-v1'):
            raise ValueError('Unsupported native perception encoding')
        fields = ('identity', 'visible', 'enemy', 'nativeDeadPredicate', 'nativeOwnerRelation',
                  'visualObservedPosition', 'visualObservedAtTicks', 'positionUpdateTicks')
        if len(reports) > 128 or sum(len(r['records']) for r in reports) > 4096:
            raise ValueError('Native perception budget exceeded')
        candidates, latest, observers = [], {}, {}
        for report in reports:
            if report['generation'] != raw['generation'] or report.get('status') != 'queried':
                raise ValueError('Invalid native perception generation/status')
            observer = report['observerIdentity']
            if observer['owner'] != raw['owner']:
                raise ValueError('Foreign perception observer')
            observer_id = Identity(raw['generation'], observer['id'], observer['incarnation'])
            if observer_id not in rows or not rows[observer_id]['eligible']:
                continue
            for record in report['records']:
                if encoding == 'tuple-v1':
                    if not isinstance(record, (list, tuple)) or len(record) != len(fields):
                        raise ValueError('Invalid compact native perception record')
                    record = dict(zip(fields, record))
                native = record['identity']
                if native is None:
                    continue
                kind = native.get('kind', 'infantry')
                if kind not in {'infantry', 'vehicle'}:
                    raise ValueError('Unsupported native contact kind')
                if type(native['incarnation']) is not int or native['incarnation'] < 1:
                    raise ValueError('Invalid contact incarnation')
                key = native['id']
                latest[key] = max(latest.get(key, 0), native['incarnation'])
                if record['visible'] is not True:
                    continue
                if type(record['enemy']) is not bool and not (
                        record['enemy'] is None and record['nativeDeadPredicate'] is True):
                    continue
                if record['enemy'] and native['owner'] == raw['owner']:
                    raise ValueError('Owned contact classified as enemy')
                position, stamp = record['visualObservedPosition'], record['visualObservedAtTicks']
                if (not isinstance(stamp, int) or stamp <= 0 or stamp != report['visualUpdateTicks'] or
                        stamp != record['positionUpdateTicks'] or not isinstance(position, (list, tuple)) or
                        len(position) != 3 or not all(isfinite(v) for v in position)):
                    raise ValueError('Inconsistent native visual observation')
                age = raw['simulationTicks'] - stamp
                if age < 0:
                    raise ValueError('Future native visual observation')
                if age > 2000 or type(record['nativeDeadPredicate']) is not bool:
                    continue
                candidates.append(Contact(Identity(raw['generation'], key, native['incarnation']),
                    tuple(v / 20. for v in position[:2]), stamp / 1000., True, record['enemy'],
                    dead=record['nativeDeadPredicate'], fresh_for=2., kind=kind,
                    strength=4. if kind == 'vehicle' else 1.,
                    allied=(record['enemy'] is False and record.get('nativeOwnerRelation') == 2
                            and raw.get('team') in ('a', 'b') and native.get('team') == raw['team'])))
                if record['enemy'] is True and record['nativeDeadPredicate'] is False:
                    observers.setdefault(candidates[-1].identity, set()).add(observer_id)
        # Different native sensors can sample a moving actor at different points
        # within one simulation tick. Do not average those into an invented
        # position, or stop the entire army. Quarantine that identity/timestamp
        # until a newer observation arrives, including across cached snapshots.
        self.contact_samples = {identity: sample for identity, sample in self.contact_samples.items()
            if 0 <= raw['simulationTicks'] / 1000. - sample[0] <= 2. and
               identity.incarnation >= latest.get(identity.unit, identity.incarnation)}
        present, relationships = set(), {}
        for contact in candidates:
            if contact.identity.incarnation != latest[contact.identity.unit]:
                continue
            present.add(contact.identity)
            relation = (contact.observed_at, contact.dead, contact.enemy, contact.allied)
            previous_relation = relationships.get(contact.identity)
            if previous_relation and previous_relation[0] == relation[0] and previous_relation != relation:
                raise ValueError('Conflicting native contact relationships')
            if previous_relation is None or relation[0] >= previous_relation[0]:
                relationships[contact.identity] = relation
            old = self.contact_samples.get(contact.identity)
            if old is None or contact.observed_at > old[0]:
                self.contact_samples[contact.identity] = (contact.observed_at, contact)
            elif contact.observed_at == old[0]:
                self.contact_samples[contact.identity] = (contact.observed_at,
                    contact if old[1] is not None and old[1].position == contact.position else None)
        if len(self.contact_samples) > 4096:
            raise ValueError('Native contact sample budget exceeded')
        contacts = {identity: replace(self.contact_samples[identity][1],
                    visible_to=frozenset(observers.get(identity, ()))) for identity in present
                    if self.contact_samples[identity][1] is not None}
        return (tuple(sorted(contacts.values(), key=lambda c: (not c.dead, not c.enemy,
            -c.observed_at, c.identity))[:256]),
            tuple(Identity(raw['generation'], key, incarnation) for key, incarnation in sorted(latest.items())))

    def submit(self, intent):
        row = self.rows.get(intent.identity)
        if not row or intent.action not in {'move', 'stance', 'attack', 'cover'} or self.raw['capabilities'].get(
                'nativeCover' if intent.action == 'cover' else intent.action) is not True:
            return 'rejected'
        deadline = intent.submit_before if intent.submit_before is not None else intent.expires
        if deadline <= self.raw['simulationTicks'] / 1000.:
            return 'rejected'
        self.sequence += 1
        options = dict(id=intent.identity.unit, incarnation=intent.identity.incarnation,
            generation=intent.identity.match, revision=self.raw['commandRevision'], sequence=self.sequence,
            action=intent.action, requireEnrolled=True, unitRevision=row['revision'],
            submitBeforeTicks=deadline * 1000.)
        if intent.action == 'attack':
            ammunition = row.get('ammunition') or {}
            bazooka = ammunition.get('weaponModel') == 'bazooka'
            heat_launcher = bazooka or (ammunition.get('weaponModel') == 'garand_grenade' and
                ammunition.get('projectileModel') == 'garand_heat_ammo')
            anti_armor = heat_launcher and ammunition.get('ammoCount',0) > 0 and ammunition.get('nativeLoading') is False
            contact = next((c for c in self.contacts if c.identity == intent.target and c.visible and
                c.enemy is True and (anti_armor if c.kind == 'vehicle' else not heat_launcher) and not c.dead and c.visible_to is not None and intent.identity in c.visible_to and
                0 <= self.raw['simulationTicks'] / 1000. - c.observed_at <= c.fresh_for), None)
            if contact is None:
                return 'cancelled'
            query = self.api.trialstance({**options, 'action': 'attack_query', 'targetId': intent.target.unit})
            self.evidence.write({'nativePreflight': options, 'query': query})
            self._submission_events(query)
            if query.get('status') != 'queried':
                return 'cancelled' if query.get('rejected') is True else 'uncertain'
            observer = query.get('observerIdentity', {})
            if (query.get('generation') != intent.identity.match or observer.get('id') != intent.identity.unit or
                    observer.get('incarnation') != intent.identity.incarnation or observer.get('owner') != row['owner']):
                raise RuntimeError('Attack preflight authority changed')
            query_ticks = query.get('simulationTicks')
            if type(query_ticks) is not int or query_ticks < self.raw['simulationTicks']:
                raise RuntimeError('Attack preflight simulation time invalid')
            if query_ticks / 1000. >= deadline:
                return 'cancelled'
            targets = query.get('targets', ())
            if len(targets) > 32:
                raise RuntimeError('Attack preflight budget exceeded')
            target = next((t for t in targets if t['identity']['id'] == intent.target.unit and
                           t['identity']['incarnation'] == intent.target.incarnation), None)
            if target is None:
                return 'cancelled'
            options['target'] = {**target['identity'], 'generation': intent.target.match, 'entityId': target['entityId']}
            self.sequence += 1
            options['sequence'] = self.sequence
        elif intent.action == 'cover':
            candidate = self.cover_candidates.get(intent.site)
            if (not candidate or candidate['observer'] != intent.identity or candidate['revision'] != row['revision'] or
                    candidate['position'] != intent.destination or candidate['expires'] <= self.raw['simulationTicks'] / 1000.):
                return 'cancelled'
            options['destination'] = [v * 20. for v in intent.destination] + [row['position'][2]]
            options['coverSource'] = candidate['source']
        elif intent.action == 'move':
            options['destination'] = [v * 20. for v in intent.destination] + [row['position'][2]]
            if (self.raw['capabilities'].get('leaderFollow') is True and intent.reason == 'objective'
                    and not row['squadLeader']):
                for identity, leader in self.rows.items():
                    ammunition = leader.get('ammunition') or {}
                    if (leader['squadLeader'] and not leader.get('individualOrder', False) and leader['eligible'] and
                            leader['revision'] == 0 and not leader['controlLockRaw'] and leader.get('coverState') == 0 and
                            (leader['movementBits'] in (0, 0x1000) or
                             self._controller_group(leader, self.raw['capabilities'])) and leader['stance'] in (0, 1, 2) and
                            leader['id'] in row['squadMembers'] and row['id'] in leader['squadMembers'] and
                            ammunition.get('nativeLoading') is not True and identity not in self.last_shots and
                            self.leader_follow_after.get(identity, 0) <= self.raw['simulationTicks'] / 1000. and
                            dist(leader['position'][:2], options['destination'][:2]) >
                                dist(row['position'][:2], options['destination'][:2]) + 200):
                        options['followLeader'] = dict(id=identity.unit, incarnation=identity.incarnation, revision=0)
                        break
            if intent.reason in {'withdraw','friendly support','AT firing reposition','supported advance'}:
                if self.raw['capabilities'].get('pathQuery') is not True:
                    return 'cancelled'
                query = self.api.trialstance({**options,'action':'path_query'})
                self.evidence.write({'nativePathPreflight':options,'query':query})
                self._submission_events(query)
                if query.get('status') != 'queried':
                    return 'cancelled' if query.get('rejected') is True else 'uncertain'
                observer = query.get('observerIdentity', {})
                stamp = query.get('simulationTicks')
                if (query.get('generation') != intent.identity.match or observer.get('id') != intent.identity.unit or
                        observer.get('incarnation') != intent.identity.incarnation or observer.get('owner') != row['owner'] or
                        type(stamp) is not int or stamp < self.raw['simulationTicks'] or query.get('vectorReleased') is not True):
                    raise RuntimeError('Invalid native path preflight identity/clock/release')
                if stamp >= options['submitBeforeTicks']:
                    return 'cancelled'
                points = [query.get(key) for key in ('destination','origin','endpoint','startpoint')]
                if query.get('reachesRequestedPoint') is not True:
                    return 'rejected'  # Known unusable route: policy applies route backoff.
                if (query.get('nativeSucceeded') is not True or query.get('partial') is not False or
                        any(not isinstance(p,(list,tuple)) or len(p)!=2 or not all(isfinite(v) for v in p) for p in points) or
                        dist(points[0],options['destination'][:2]) > .01 or
                        dist(points[2],points[0]) > 3 or dist(points[3],points[1]) > 3):
                    raise RuntimeError('Inconsistent native path preflight endpoints')
                self.sequence += 1
                options['sequence'] = self.sequence
        else:
            options['stance'] = {'standing': 0, 'crouched': 1, 'prone': 2}[intent.stance]
        reply = self.api.submit(options)
        self.evidence.write({'nativeSubmission': options, 'ack': reply})
        self._submission_events(reply)
        if reply.get('status') == 'serialized':
            if 'followLeader' in options:
                leader = options['followLeader']
                self.leader_follow_after[Identity(intent.identity.match, leader['id'], leader['incarnation'])] = self.raw['simulationTicks'] / 1000. + 10.
            return 'accepted'
        # Native admission rejection proves no execution began. Do not label it
        # a failed route or penalize another unit for a changed global revision.
        return 'cancelled' if reply.get('rejected') is True else 'uncertain'

    def _submission_events(self, reply):
        self.events.extend(reply.get('observedEvents', []))
        if len(self.events) > 2048:
            raise RuntimeError('Native submission event budget exceeded')

    def completions(self, snapshot, inflight):
        result = []
        self.move_progress = {identity: progress for identity, progress in self.move_progress.items()
            if identity in inflight and progress[0] == inflight[identity].sequence}
        units = {unit.identity: unit for unit in snapshot.units}
        for identity, intent in inflight.items():
            row = self.rows.get(identity)
            if (not row or not row['eligible'] or not row['enrolled'] or row['controlLockRaw'] or
                    (row['movementBits'] != 0 and not self._controller_group(row, self.raw['capabilities'])) or
                    intent.expires <= snapshot.time):
                continue
            arrived = intent.action == 'move' and dist(row['position'][:2],
                tuple(v * 20. for v in intent.destination)) <= 40.
            settled = intent.action == 'stance' and row['stance'] == {'standing': 0, 'crouched': 1, 'prone': 2}[intent.stance]
            occupied = (intent.action == 'cover' and row.get('coverState') in (1, 2) and
                dist(row['position'][:2], tuple(v * 20. for v in intent.destination)) <= 30.)
            shot = (intent.action == 'attack' and intent.submit_before is not None and
                    self.last_shots.get(identity, -1) / 1000. >= intent.submit_before - .75)
            if arrived or settled or occupied or shot:
                result.append((intent, 'completed'))
                if shot:
                    self.evidence.write({'attackShotObserved': asdict(intent), 'simulationTime': snapshot.time,
                                         'damageConfirmed': False})
                self.move_progress.pop(identity, None)
            elif intent.action in {'move', 'cover'} and intent.destination is not None:
                unit = units.get(identity)
                position = tuple(row['position'][:2])
                progress = self.move_progress.get(identity)
                distance = dist(position, tuple(v * 20. for v in intent.destination))
                # Displacement, not distance to destination: valid native routes
                # may initially lead away from the endpoint. Combat and pauses
                # are legitimate waits, not path failures.
                waiting = snapshot.paused or unit is None or unit.readiness in {'aiming', 'firing', 'reloading'}
                if progress is None or waiting:
                    self.move_progress[identity] = (intent.sequence, position, snapshot.time, distance, snapshot.time)
                    continue
                moved = dist(position, progress[1]) >= 20.
                improved = distance <= progress[3] - 20.
                progress = (intent.sequence, position if moved else progress[1],
                            snapshot.time if moved else progress[2], distance if improved else progress[3],
                            snapshot.time if improved else progress[4])
                self.move_progress[identity] = progress
                if snapshot.time - progress[2] >= 12. or snapshot.time - progress[4] >= 24.:
                    result.append((intent, 'failed'))
                    self.evidence.write({'movementStalled': asdict(intent),
                        'simulationTime': snapshot.time, 'stationarySeconds': snapshot.time - progress[2],
                        'noEndpointProgressSeconds': snapshot.time - progress[4],
                        'reason': 'stationary' if snapshot.time - progress[2] >= 12. else 'no endpoint progress'})
                    self.move_progress.pop(identity, None)
        return result


class IntentQueue:
    """One queued intent per identity; never retry a possibly submitted intent."""
    MAX_IDENTITIES = 4096
    def __init__(self, capacity=128):
        if not 1 <= capacity <= 128:
            raise ValueError('capacity must be 1..128')
        self.capacity = capacity
        self.pending = {}
        self.revisions = {}
        self.match = None
        self.sequence = 0

    def reset(self, match):
        self.pending.clear()
        self.revisions.clear()
        self.match = match
        self.sequence = 0

    def cancel(self, identity, revision):
        if identity.match != self.match:
            return
        self._admit_identity(identity)
        self.revisions[identity] = max(revision, self.revisions.get(identity, -1))
        self.pending.pop(identity, None)

    def _admit_identity(self, identity):
        # Never evict a cancellation tombstone and accidentally accept its old
        # revision. A match with this many incarnations must stop and reattach.
        if identity not in self.revisions and len(self.revisions) >= self.MAX_IDENTITIES:
            raise RuntimeError('Intent identity budget exhausted; stop controller')

    def enqueue(self, intent, now):
        deadline = intent.submit_before if intent.submit_before is not None else intent.expires
        if (intent.identity.match != self.match or deadline <= now
                or intent.sequence <= self.sequence
                or intent.revision <= self.revisions.get(intent.identity, -1)):
            return False
        if intent.identity not in self.pending and len(self.pending) >= self.capacity:
            return False
        self._admit_identity(intent.identity)
        self.pending[intent.identity] = intent
        self.revisions[intent.identity] = intent.revision
        self.sequence = intent.sequence
        return True

    def drain(self, snapshot, members, limit=8):
        if snapshot.match != self.match:
            self.reset(snapshot.match)
            return []
        units = {u.identity: u for u in snapshot.units}
        result = []
        for identity, intent in list(self.pending.items()):
            unit, state = units.get(identity), members.get(identity)
            eligible = (unit and state and state.enrolled and unit.alive and unit.infantry
                        and unit.owner == snapshot.owner and unit.move_at_will
                        and not unit.direct_control and state.revision == intent.revision
                        and (intent.submit_before if intent.submit_before is not None else intent.expires) > snapshot.time)
            if (unit and unit.readiness in {'aiming', 'firing', 'reloading'} and
                    intent.action in {'move', 'stance', 'cover', 'build'} and intent.reason != 'withdraw'):
                eligible = False  # Readiness may change after policy queued this order.
            if not eligible:
                del self.pending[identity]
                continue
            if snapshot.paused or len(result) >= limit:
                continue
            del self.pending[identity]  # removed before crossing the RPC boundary
            result.append(intent)
        return result


class Runtime:
    """Bounded policy/queue runner over an explicitly validated adapter contract.

    submit returns 'accepted', 'rejected' (failed action), or 'cancelled'
    (known unexecuted admission refusal); any other result is uncertain.
    Completion is supplied separately as (the exact Intent, terminal status).
    This does not enable the live bridge or infer completion from serialization.
    """
    def __init__(self, submit, evidence, limit=8):
        if not 1 <= limit <= 128:
            raise ValueError('submission limit must be 1..128')
        self.submit, self.evidence, self.limit = submit, evidence, limit
        self.policy, self.queue = Policy(), IntentQueue()
        self.inflight = {}
        self.stopped = False
        self.owner = None
        self.timings = dict(policyMaxMs=0., commandMaxMs=0., commandTotalMs=0., commands=0)

    def step(self, snapshot, completions=()):
        if self.stopped:
            raise RuntimeError('Runtime stopped')
        if len(completions) > Policy.MAX_UNITS:
            raise ValueError('completion budget exceeded')
        try:
            if self.owner is not None and self.owner != snapshot.owner:
                raise RuntimeError('Local authority changed; reattach required')
            self.owner = snapshot.owner
            eligible_completions = []
            for intent, status in completions:
                if status not in {'completed', 'failed', 'cancelled', 'uncertain'}:
                    raise ValueError('invalid terminal acknowledgement')
                if self.inflight.get(intent.identity) == intent:
                    eligible_completions.append((intent, status))
                else:
                    self.evidence.write({'ignoredCompletion': asdict(intent), 'status': status})
            # Generate only what this step can dispatch. Even one waiting wave
            # outlived the short submission deadline in a native 88-unit trial.
            self.policy.order_budget = max(0, min(32, self.limit - len(self.queue.pending)))
            policy_start = time.perf_counter()
            intents = self.policy.step(snapshot, eligible_completions)
            self.timings['policyMaxMs'] = max(self.timings['policyMaxMs'], (time.perf_counter() - policy_start) * 1000.)
            for intent, status, acknowledged in self.policy.completions:
                self.evidence.write({'terminal' if acknowledged else 'ignoredCompletion': asdict(intent),
                                     'status': status, 'simulationTime': snapshot.time})
                if acknowledged:
                    self.inflight.pop(intent.identity, None)
            if self.queue.match != snapshot.match:
                self.queue.reset(snapshot.match)
                self.inflight.clear()
            for identity, intent in list(self.inflight.items()):
                member = self.policy.members.get(identity)
                if member is None or member.action != intent:
                    reason = ('identity or authority changed' if member is None or not member.enrolled else
                              'deadline elapsed without observed completion' if intent.expires <= snapshot.time else
                              'target, site or tactical assignment changed')
                    self.evidence.write({'retired': asdict(intent), 'simulationTime': snapshot.time,
                                         'reason': reason,
                                         'shotNotObserved': intent.action == 'attack'})
                    del self.inflight[identity]
            for intent in intents:
                if not self.queue.enqueue(intent, snapshot.time):
                    self.policy.acknowledge(intent, 'cancelled')
                    self.evidence.write({'queueRejected': asdict(intent)})
            sent = []
            queued = dict(self.queue.pending)
            dispatches = self.queue.drain(snapshot, self.policy.members, self.limit)
            dispatched = {intent.identity for intent in dispatches}
            for identity, intent in queued.items():
                if identity not in self.queue.pending and identity not in dispatched:
                    self.policy.acknowledge(intent, 'cancelled')
                    self.evidence.write({'queueDiscarded': asdict(intent), 'simulationTime': snapshot.time})
            for intent in dispatches:
                self.evidence.write({'intent': asdict(intent), 'simulationTime': snapshot.time})
                try:
                    command_start = time.perf_counter()
                    status = self.submit(intent)
                except BaseException:
                    self.policy.acknowledge(intent, 'uncertain')
                    raise
                finally:
                    elapsed = (time.perf_counter() - command_start) * 1000.
                    self.timings['commandMaxMs'] = max(self.timings['commandMaxMs'], elapsed)
                    self.timings['commandTotalMs'] += elapsed
                    self.timings['commands'] += 1
                if status not in {'accepted', 'rejected', 'cancelled'}:
                    self.policy.acknowledge(intent, 'uncertain')
                    raise RuntimeError('Uncertain submission; stopping without replay')
                self.evidence.write({'submission': asdict(intent), 'status': status})
                if status == 'accepted':
                    self.inflight[intent.identity] = intent
                    sent.append(intent)
                else:
                    self.policy.acknowledge(intent, 'cancelled' if status == 'cancelled' else 'failed')
            return sent
        except BaseException:
            self.stop()
            raise

    def stop(self):
        self.stopped = True
        self.queue.pending.clear()
        for member in self.policy.members.values():
            if member.action is not None:
                self.policy.acknowledge(member.action, 'uncertain')
        self.inflight.clear()


class Evidence:
    def __init__(self, directory, limit=16 * 1024 * 1024, retained_files=1):
        if type(limit) is not int or limit < 1 or type(retained_files) is not int or not 1 <= retained_files <= 4:
            raise ValueError('Invalid evidence retention budget')
        directory.mkdir(parents=True, exist_ok=False)
        self.path = directory
        self.file = (directory / 'observations.jsonl').open('x', encoding='utf-8', newline='\n')
        self.limit, self.size, self.count = limit, 0, 0
        self.retained_files, self.archives, self.rotations = retained_files, [], 0
        self.current_count = self.discarded_count = self.discarded_bytes = 0

    def retention(self):
        return dict(files=self.retained_files, bytesPerFile=self.limit, rotations=self.rotations,
                    discardedRecords=self.discarded_count, discardedBytes=self.discarded_bytes,
                    recordsWritten=self.count, retainedRecords=self.count - self.discarded_count)

    def _save_retention(self):
        temporary = self.path / 'retention.json.tmp'
        temporary.write_text(json.dumps(self.retention(), indent=2), encoding='utf-8')
        temporary.replace(self.path / 'retention.json')

    def _rotate(self):
        self.file.close()
        if len(self.archives) >= self.retained_files - 1:
            expired, records, size = self.archives[0]
            expired.unlink()
            self.archives.pop(0)
            self.discarded_count += records
            self.discarded_bytes += size
        self.rotations += 1
        archive = self.path / f'observations.{self.rotations:06d}.jsonl'
        (self.path / 'observations.jsonl').rename(archive)
        self.archives.append((archive, self.current_count, self.size))
        self.file = (self.path / 'observations.jsonl').open('x', encoding='utf-8', newline='\n')
        self.current_count = self.size = 0
        self._save_retention()

    def write(self, record):
        line = json.dumps(record, allow_nan=False, separators=(',', ':')) + '\n'
        size = len(line.encode('utf-8'))
        if size > self.limit or (self.retained_files == 1 and self.size + size > self.limit):
            raise RuntimeError('Evidence size limit reached; stopping')
        if self.size + size > self.limit:
            self._rotate()
        self.file.write(line)
        self.file.flush()
        self.size += size
        self.count += 1
        self.current_count += 1

    def close(self, summary):
        self.file.close()
        summary['evidenceRetention'] = self.retention()
        if self.retained_files > 1:
            self._save_retention()
        (self.path / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')


def source_hashes():
    return {name: hashlib.sha256((ROOT / 'headless' / name).read_bytes()).hexdigest()
            for name in ('tactical_bridge.js', 'tactical_controller.py', 'tactical_policy.py', 'tactical_operations.py', 'tactical_sync.py')}


def executable_identity(api):
    identity = api.identity()
    identity['sha256'] = hashlib.sha256(Path(identity['executable']).read_bytes()).hexdigest()
    if identity['sha256'] != SUPPORTED_EXECUTABLE:
        raise RuntimeError('Unsupported executable hash; native tactical actions disabled')
    return identity


def observe(pid, duration, directory, mode='observe', stop_event=None):
    import frida
    stop_event = stop_event or threading.Event()
    evidence = Evidence(directory, retained_files=4 if mode == 'run' else 1)
    session = script = None
    runtime = adapter = None
    summary = {'pid': pid, 'mode': mode, 'sourceHashes': source_hashes(),
               'startedUtc': datetime.now(timezone.utc).isoformat(), 'ordersIssued': 0,
               'liveBehaviorValidated': False, 'synchronization': 'unverified'}
    start = time.monotonic()
    try:
        session = native_call(frida.attach, pid)
        script = native_call(session.create_script, (ROOT / 'headless/tactical_bridge.js').read_text(encoding='utf-8'))
        errors = []
        def on_message(message, data):
            if message.get('type') == 'error':
                errors.append(message)
                stop_event.set()
        script.on('message', on_message)
        native_call(script.load)
        api = NativeCalls(script.exports_sync)
        summary['executableIdentity'] = executable_identity(api)
        summary['configuration'] = {'duration': duration, 'mode': mode, 'pollSeconds': .2}
        capabilities = api.capabilities()
        summary['capabilities'] = capabilities
        if mode == 'run':
            missing = [key for key in ('identityLifecycle', 'simulationClock', 'death',
                       'commandAuthority', 'synchronization', 'move') if not capabilities.get(key)]
            if missing:
                raise RuntimeError('Run disabled; unverified gates: ' + ', '.join(missing))
            adapter = NativeAdapter(api, evidence)
            runtime = Runtime(adapter.submit, evidence)
        while (duration is None or time.monotonic() - start < duration) and not stop_event.is_set():
            observed = api.snapshot()
            if observed.get('error') or observed.get('fault'):
                raise RuntimeError(observed.get('error') or observed['fault'])
            evidence.write(observed)
            summary.setdefault('first', observed)
            summary['last'] = observed
            if runtime:
                snapshot = adapter.snapshot(observed)
                submitted = runtime.step(snapshot, adapter.completions(snapshot, runtime.inflight))
                summary['ordersIssued'] += len(submitted)
            stop_event.wait(.2)
        if errors:
            raise RuntimeError(str(errors[0]))
        summary['result'] = 'observed'
    except BaseException as error:
        summary['result'], summary['error'] = 'failed', str(error)
        raise
    finally:
        if runtime:
            runtime.stop()
        if script:
            try:
                summary['stop'] = native_call(script.exports_sync.stop)
            except Exception as error:
                summary['stopError'] = str(error)
        if session:
            try:
                native_call(session.detach)
            except Exception as error:
                summary['detachError'] = str(error)
        summary['elapsedSeconds'] = time.monotonic() - start
        summary['samples'] = evidence.count
        evidence.close(summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['observe', 'run'])
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--duration', type=float, help='Seconds to run; default: observe 30 seconds, run until stopped')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.duration is not None and not 0 < args.duration <= 3600:
        parser.error('duration must be 0..3600 seconds')
    output = args.output or ROOT / 'validation' / ('tactical_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
    try:
        duration = args.duration if args.duration is not None else (30 if args.mode == 'observe' else None)
        result = observe(args.pid, duration, output, args.mode)
    except KeyboardInterrupt:
        print('Stopped; game remains open. Evidence: ' + str(output))
        return 130
    except Exception as error:
        print(str(error) + '\nEvidence: ' + str(output))
        return 1
    print(json.dumps({'result': result['result'], 'samples': result['samples'], 'evidence': str(output)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
