"""Bounded force planning and diagnostics using the controller's observations."""
from collections import Counter
from math import dist

from tactical_policy import Policy


class ForcePlanner:
    def __init__(self):
        self.match = None
        self.armor_until = 0.
        self.next_choice = 0.
        self.choice = 'rifle'
        self.strength = {}
        self.reason = 'establish infantry support'

    def choose(self, snapshot, policy):
        if self.match != snapshot.match:
            self.__init__()
            self.match = snapshot.match
        vehicles = [c for c in snapshot.contacts if c.kind == 'vehicle' and c.enemy is True and
                    c.visible and not c.dead and 0 <= snapshot.time - c.observed_at <= c.fresh_for]
        if vehicles:
            self.armor_until = snapshot.time + 30.
        effective = Counter(rifle=0., assault=0., anti_tank=0.)
        for unit in snapshot.units:
            state = policy.members.get(unit.identity)
            if not unit.alive or unit.owner != snapshot.owner or not state or not state.enrolled:
                continue
            role = ('anti_tank' if Policy._anti_armor(unit) else 'assault' if
                    unit.weapon_model in Policy.SMG_MODELS else 'rifle')
            # Only the currently loaded ammunition is known. Reloading/unknown
            # reserves receive partial weight, never a claim of exhaustion.
            ammo = (1. if unit.ammo is not None and unit.ammo > 0 else
                    .25 if unit.readiness == 'reloading' else .5 if unit.ammo is None else 0.)
            destinations = [v.position for v in vehicles] or [o.position for o in snapshot.objectives]
            distance = min((dist(unit.position, p) for p in destinations), default=0.)
            position = max(.2, 1. - distance / 200.)
            availability = .25 if state.recovery_count or state.wait_reason in {
                'route reassignment cooldown', 'route cooldown'} else 1.
            effective[role] += ammo * position * availability
        self.strength = dict(effective)
        if snapshot.time < self.next_choice:
            return self.choice
        if self.armor_until > snapshot.time and effective['anti_tank'] < 2.:
            self.choice, self.reason = 'anti_tank', 'observed armor with insufficient usable AT'
        elif effective['rifle'] < max(4., effective['anti_tank'] * 2.):
            self.choice, self.reason = 'rifle', 'infantry support shortage'
        elif effective['anti_tank'] < 1.:
            self.choice, self.reason = 'anti_tank', 'maintain a small AT reserve'
        elif effective['assault'] < max(2., effective['rifle'] * .3):
            self.choice, self.reason = 'assault', 'close-range infantry shortage'
        else:
            self.choice, self.reason = 'rifle', 'replace general infantry strength'
        self.next_choice = snapshot.time + 15.
        return self.choice


class TacticalMetrics:
    """Current army metrics plus cumulative outcomes; no unbounded event history."""
    def __init__(self):
        self.match = None
        self.positions = {}
        self.departed = set()
        self.service_wait_max = 0.
        self.vehicle_engagements = {}
        self.vehicle_outcomes = Counter()
        self.waiting = {}

    def sample(self, snapshot, runtime, completions):
        if self.match != snapshot.match:
            self.__init__()
            self.match = snapshot.match
        policy = runtime.policy
        alive = {u.identity for u in snapshot.units if u.alive and u.owner == snapshot.owner}
        self.departed &= alive
        self.positions = {i: p for i, p in self.positions.items() if i in alive}
        self.waiting = {i: value for i, value in self.waiting.items() if i in alive}
        reasons, assignments = Counter(), Counter()
        prolonged, armor_stages = Counter(), Counter()
        cover_occupied = 0
        wait_max = 0.
        for unit in snapshot.units:
            state = policy.members.get(unit.identity)
            if unit.identity not in alive or not state or not state.enrolled:
                continue
            origin = self.positions.setdefault(unit.identity, unit.position)
            if dist(origin, unit.position) >= 15.:
                self.departed.add(unit.identity)
            reasons[state.wait_reason] += 1
            assignments[state.assignment or 'unassigned'] += 1
            cover_occupied += int(unit.in_cover is True)
            previous = self.waiting.get(unit.identity)
            if previous is None or previous[0] != state.wait_reason:
                self.waiting[unit.identity] = (state.wait_reason, snapshot.time)
            duration = snapshot.time - self.waiting[unit.identity][1]
            if duration >= 30.:
                prolonged[state.wait_reason] += 1
            if state.wait_reason == 'awaiting service':
                wait_max = max(wait_max, duration)
            if Policy._anti_armor(unit):
                armor_stages[unit.readiness if unit.readiness in {'aiming', 'firing', 'reloading'} else
                    'loaded ammunition unavailable' if unit.ammo == 0 else
                    state.action.reason if state.action else state.wait_reason] += 1
        self.service_wait_max = max(self.service_wait_max, wait_max)
        contacts = {c.identity: c for c in snapshot.contacts}
        for intent in runtime.inflight.values():
            contact = contacts.get(intent.target)
            if intent.action == 'attack' and contact and contact.kind == 'vehicle':
                if intent.target not in self.vehicle_engagements and len(self.vehicle_engagements) >= Policy.MAX_CONTACTS:
                    oldest = min(self.vehicle_engagements, key=lambda i: self.vehicle_engagements[i]['lastSeen'])
                    self.vehicle_engagements.pop(oldest)
                    self.vehicle_outcomes['unresolvedAtRetentionLimit'] += 1
                entry = self.vehicle_engagements.setdefault(intent.target,
                    dict(firstSeen=snapshot.time, lastSeen=snapshot.time, shotObserved=False))
                entry['lastSeen'] = snapshot.time
        for intent, status, acknowledged in policy.completions:
            if acknowledged and intent.action == 'attack' and status == 'completed' and intent.target in self.vehicle_engagements:
                self.vehicle_engagements[intent.target]['shotObserved'] = True
                self.vehicle_outcomes['shotsObserved'] += 1
        for identity, entry in list(self.vehicle_engagements.items()):
            contact = contacts.get(identity)
            if (contact and contact.dead and contact.visible and contact.enemy is not False and
                    0 <= snapshot.time - contact.observed_at <= contact.fresh_for):
                self.vehicle_outcomes['targetDeathObserved'] += 1
                self.vehicle_outcomes['targetDeathAfterShotObserved'] += int(entry['shotObserved'])
                del self.vehicle_engagements[identity]
            elif snapshot.time - entry['lastSeen'] > 30.:
                self.vehicle_outcomes['unresolvedAfterContactLoss'] += 1
                del self.vehicle_engagements[identity]
        return dict(match=snapshot.match, simulationTime=snapshot.time,
                    assignmentCounts=dict(assignments), waitingReasons=dict(reasons),
                    prolongedWaitingReasons=dict(prolonged), atEngagementStages=dict(armor_stages),
                    recoveryPending=sum(bool(policy.members[i].recovery_count or policy.members[i].blocked_goals)
                        for i in alive if i in policy.members and policy.members[i].enrolled),
                    departedInitialPosition=len(self.departed),
                    departureScope='currently observed soldiers displaced 15 policy units from first observation; first observation need not be spawn',
                    nativeCoverOccupied=cover_occupied, serviceWaitMaxSeconds=self.service_wait_max,
                    failures={key: value for key, value in policy.outcomes.items() if not key.endswith(':completed')},
                    attackOutcomes={key: value for key, value in policy.outcomes.items() if key.startswith('attack:')},
                    movementOutcomes={key: value for key, value in policy.outcomes.items() if key.startswith('move:')},
                    coverOutcomes={key: value for key, value in policy.outcomes.items() if key.startswith('cover:')},
                    timing=runtime.timings,
                    vehicleEngagements=dict(self.vehicle_outcomes, active=len(self.vehicle_engagements)),
                    damageConfirmation='damage amount/kill attribution unavailable; shots and target deaths are separate evidence')
