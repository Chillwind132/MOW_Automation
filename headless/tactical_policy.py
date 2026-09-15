"""Deterministic tactical decisions. Inputs are observations, never native pointers.

An adapter must explicitly verify capabilities before supplying them. Unknown
visibility, ownership, route quality and construction data do not imply success.
All policy times are simulation seconds. No wall clock, I/O or game dependencies.
"""
from dataclasses import dataclass, field
from collections import Counter
from math import cos, dist, hypot, isfinite, sin, sqrt


@dataclass(frozen=True, order=True)
class Identity:
    match: str
    unit: str
    incarnation: int


@dataclass(frozen=True)
class Contact:
    identity: Identity
    position: tuple[float, float]
    observed_at: float
    visible: bool
    enemy: bool | None
    dead: bool = False
    strength: float = 1.0
    urgent: bool = False
    fresh_for: float = .5
    # None preserves callers without per-observer data; native snapshots always
    # provide the bounded set of owned observers that actually saw this contact.
    visible_to: frozenset[Identity] | None = None
    # Separately verified alliance: merely being non-enemy is insufficient.
    allied: bool = False
    kind: str = 'infantry'


@dataclass(frozen=True)
class Unit:
    identity: Identity
    owner: str
    squad: str
    position: tuple[float, float]
    alive: bool = True
    infantry: bool = True
    move_at_will: bool = False
    direct_control: bool = False
    stance: str = 'standing'
    readiness: str = 'unknown'
    ammo: float | None = None
    covering: bool = False
    urgent_danger: bool = False
    reachable: bool | None = None
    weapon_model: str | None = None
    projectile_model: str | None = None
    in_cover: bool | None = None
    squad_leader: bool = False


@dataclass(frozen=True)
class Objective:
    key: str
    position: tuple[float, float]
    owner: str | None
    value: float = 1.0
    reachable: bool | None = None
    capture_radius: float | None = None


@dataclass(frozen=True)
class Cover:
    key: str
    position: tuple[float, float]
    reachable: bool | None = None
    protection: float | None = None
    firing_access: bool | None = None
    escape: bool | None = None
    occupied: bool = False
    destroyed: bool = False
    stance: str = 'crouched'
    build_seconds: float | None = None
    tools: bool | None = None
    terrain: bool | None = None
    safe_seconds: float | None = None
    native_score: float | None = None
    observer: Identity | None = None


@dataclass(frozen=True)
class Event:
    key: str
    kind: str
    units: tuple[Identity, ...] = ()
    origin: str = 'player'
    mode: str | None = None
    position: tuple[float, float] | None = None
    confirmed: bool = False
    observed_at: float | None = None


@dataclass(frozen=True)
class Snapshot:
    match: str
    time: float
    owner: str
    units: tuple[Unit, ...]
    contacts: tuple[Contact, ...] = ()
    objectives: tuple[Objective, ...] = ()
    covers: tuple[Cover, ...] = ()
    events: tuple[Event, ...] = ()
    capabilities: frozenset[str] = frozenset()
    paused: bool = False
    # Complete, validated friendly positions for casualty normalization. None
    # means the denominator is unknown, not that no friendlies were present.
    friendly_presence: tuple[tuple[float, float], ...] | None = None
    # Registry-validated contact identities, including unseen replacements.
    # These invalidate old incarnations without supplying positions or deaths.
    contact_identities: tuple[Identity, ...] = ()


@dataclass(frozen=True)
class Intent:
    identity: Identity
    revision: int
    sequence: int
    action: str
    reason: str
    expires: float
    destination: tuple[float, float] | None = None
    target: Identity | None = None
    stance: str | None = None
    site: str | None = None
    submit_before: float | None = None


@dataclass
class Memory:
    contact: Contact
    velocity: tuple[float, float] = (0., 0.)

    def estimate(self, now):
        age = max(0., now - self.contact.observed_at)
        horizon = min(age, 2.)
        p = self.contact.position
        return ((p[0] + self.velocity[0] * horizon,
                 p[1] + self.velocity[1] * horizon), max(0., 1. - age / 15.))


@dataclass
class Member:
    owner: str
    enrolled: bool
    revision: int = 0
    action: Intent | None = None
    target: Identity | None = None
    next_decision: float = 0.
    travel_posture_after: float = 0.
    failed: dict = field(default_factory=dict)
    blocked_destinations: dict = field(default_factory=dict)
    last_action: Intent | None = None
    cover_visit: tuple[str, float] | None = None
    last_status: str | None = None
    assignment: str | None = None
    wait_reason: str = 'awaiting service'
    serviced_at: float | None = None
    recovery_count: int = 0
    blocked_goals: dict = field(default_factory=dict)
    occupied_cover: str | None = None
    cover_role: str | None = None
    cover_threats: tuple = ()
    armor_wait: tuple | None = None
    armor_target: Identity | None = None
    armor_failures: int = 0
    armor_repositions: int = 0


@dataclass
class Squad:
    goal: str | None = None
    support_goal: Identity | None = None
    support_position: tuple[float, float] | None = None
    state: str = 'choose'
    regroup_until: float = 0.
    next_goal: float = 0.
    moving: set = field(default_factory=set)
    waiting_since: float = 0.
    advance_sequence: int = 0
    individual_until: float = 0.
    reserve: bool = False


class Policy:
    MAX_UNITS = 1024
    MAX_CONTACTS = 256
    MAX_COVERS = 128
    MAX_EVENTS = 2048
    MAX_CELLS = 512
    # Native diagnostic admission allows 30; leave headroom for motion between
    # snapshot, path preflight and submission. Every stage still revalidates.
    MAX_MOVE_LEG = 29.
    MAX_DECISIONS = 64
    SMG_MODELS = frozenset({'thompson', 'thompson_30', 'thompson_m1928'})

    def __init__(self):
        self.match = None
        self.owner = None
        self.now = -1.
        self.members = {}
        self.squads = {}
        self.memory = {}
        self.reservations = {}
        self.casualties = {}
        self.presence = {}
        self.events = {}
        self.sequence = 0
        self.built_sites = set()
        self._danger_cache = {}
        self._boundary_cache = {}
        self._schedule_cursor = 0
        self._issued_this_step = 0
        self.order_budget = 32
        self._threat_samples = ()
        self._support_cells = {}
        self._support_cache = {}
        self._pressure_cache = {}
        self._armor_focus = None
        self._armor_focus_after = 0.
        self.completions = []
        self.outcomes = Counter()
        self.reserve_squad = None

    def _release(self, identity):
        self.reservations = {k: v for k, v in self.reservations.items() if v[0] != identity}

    def _revoke(self, identity):
        state = self.members.get(identity)
        if state:
            state.enrolled = False
            state.revision += 1
            state.action = None
            state.target = None
        self._release(identity)

    def acknowledge(self, intent, status):
        """Accepted is not completion. Uncertain results are never replayed."""
        state = self.members.get(intent.identity)
        if not state or state.action != intent:
            return False
        if status == 'accepted':
            return True
        if status not in {'completed', 'failed', 'cancelled', 'uncertain'}:
            raise ValueError('unknown acknowledgement')
        self.outcomes[intent.action + ':' + status] += 1
        if intent.action == 'attack' and intent.target == state.armor_target:
            if status == 'completed':
                state.armor_failures = state.armor_repositions = 0
            elif status in {'failed', 'uncertain'}:
                state.armor_failures += 1
        if status in {'failed', 'uncertain'}:
            state.failed[(intent.action, intent.destination, intent.site, intent.target)] = self.now + 10.
            if intent.action in {'move', 'cover'} and intent.destination is not None:
                state.blocked_destinations = {p: until for p, until in state.blocked_destinations.items() if until > self.now}
                state.blocked_destinations[intent.destination] = self.now + 60.
                if len(state.blocked_destinations) > 16:
                    state.blocked_destinations.pop(next(iter(state.blocked_destinations)))
            if intent.action in {'move', 'cover'}:
                state.recovery_count += 1
                if state.recovery_count >= 3 and state.assignment:
                    state.blocked_goals[state.assignment] = self.now + 60.
                    state.blocked_goals = dict(list(state.blocked_goals.items())[-8:])
                    state.recovery_count = 0
        if status != 'completed':
            self._release(intent.identity)
        elif intent.action == 'build':
            self.built_sites.add(intent.site)
        elif intent.action == 'cover':
            state.cover_visit = (intent.site, self.now + 2.)
            state.occupied_cover = intent.site
            state.cover_role = 'defensive hold' if intent.reason == 'defensive cover' else (
                'firing position' if intent.reason == 'nearby combat cover' else 'temporary shelter')
        elif intent.action == 'move':
            state.recovery_count = 0
        state.last_action, state.last_status = intent, status
        state.action = None
        state.next_decision = self.now + 1.
        return True

    @staticmethod
    def _anti_armor(unit):
        return unit.weapon_model == 'bazooka' or (
            unit.weapon_model == 'garand_grenade' and unit.projectile_model == 'garand_heat_ammo')

    @staticmethod
    def _can_attack(unit, contact):
        if Policy._anti_armor(unit):
            return contact.kind == 'vehicle' and unit.ammo is not None and unit.ammo > 0
        return contact.kind == 'infantry' and unit.ammo != 0

    def _armor_ready(self, unit, target, group):
        """A brief scheduling window, not a claim of native firing feasibility."""
        state = self.members[unit.identity]
        if (unit.readiness != 'ready' or target.urgent or unit.urgent_danger or
                dist(unit.position, target.position) < 35):
            state.armor_wait = None
            return True
        if state.armor_wait is None or state.armor_wait[0] != target.identity:
            state.armor_wait = (target.identity, self.now)
        peers = [other for other in group if other.identity != unit.identity and
            other.owner == unit.owner and other.alive and other.move_at_will and not other.direct_control and
            self._anti_armor(other) and (other.ammo is not None and other.ammo > 0 or other.readiness == 'reloading') and
            other.readiness in {'ready', 'reloading'} and
            dist(other.position, target.position) <= 100 and
            (target.visible_to is None or other.identity in target.visible_to)]
        # Unknown readiness never promises coordination. One ready launcher
        # may wait for a currently loading partner, but only for 1.5 seconds.
        return (not peers or any(other.readiness == 'ready' for other in peers) or
                self.now - state.armor_wait[1] >= 1.5)

    def _nearby_fire_support(self, unit, goal, units, visible):
        """Temporary observation support for separately purchased SMG troops."""
        if goal is None or unit.weapon_model not in self.SMG_MODELS:
            return False
        for other in units.values():
            member = self.members.get(other.identity)
            if (other.squad == unit.squad or not member or not member.enrolled or
                    not other.alive or other.direct_control or not other.covering or
                    other.readiness not in {'ready', 'firing'} or other.ammo is None or other.ammo <= 0 or
                    self._anti_armor(other) or dist(unit.position, other.position) > 40 or
                    (member.action and member.action.action in {'move', 'cover', 'build'})):
                continue
            if any(c.visible_to is not None and other.identity in c.visible_to and
                   dist(c.position, goal) <= 60 and dist(c.position, unit.position) <= 100
                   for c in visible.values()):
                return True
        return False

    def _observe(self, s):
        visible = {}
        owned = {u.identity for u in s.units if u.owner == s.owner}
        latest = {identity.unit: identity.incarnation for identity in s.contact_identities}
        self.memory = {identity: memory for identity, memory in self.memory.items()
                       if identity not in owned and latest.get(identity.unit, identity.incarnation) <= identity.incarnation}
        for c in s.contacts[:self.MAX_CONTACTS]:
            if c.identity.match != s.match or c.identity in owned:
                continue
            if c.identity.incarnation < latest.get(c.identity.unit, c.identity.incarnation):
                continue
            for identity in list(self.memory):
                if identity.unit == c.identity.unit and identity.incarnation < c.identity.incarnation:
                    del self.memory[identity]
            if c.dead:
                self.memory.pop(c.identity, None)
                continue
            if c.enemy is False and c.visible and 0 <= s.time - c.observed_at <= c.fresh_for:
                self.memory.pop(c.identity, None)
                continue
            if not c.enemy or not c.visible or not 0 <= s.time - c.observed_at <= c.fresh_for:
                continue
            old = self.memory.get(c.identity)
            if old and c.observed_at < old.contact.observed_at:
                continue
            velocity = (0., 0.)
            if old and c.observed_at == old.contact.observed_at:
                # Repeated snapshots are not a new observation of motion.
                if c.position != old.contact.position:
                    raise ValueError('contact position changed without a new observation')
                velocity = old.velocity
            if old and c.observed_at > old.contact.observed_at:
                dt = c.observed_at - old.contact.observed_at
                dx, dy = (c.position[i] - old.contact.position[i] for i in range(2))
                speed = hypot(dx, dy) / dt
                scale = min(1., 12. / speed) if speed else 1.
                velocity = (dx / dt * scale, dy / dt * scale)
            self.memory[c.identity] = Memory(c, velocity)
            visible[c.identity] = c
        self.memory = dict(sorted(
            ((k, v) for k, v in self.memory.items() if s.time - v.contact.observed_at < 15.),
            key=lambda kv: kv[1].contact.observed_at, reverse=True)[:self.MAX_CONTACTS])
        return visible

    @staticmethod
    def _cell(p):
        return (int(p[0] // 30), int(p[1] // 30))

    def danger(self, p):
        key = tuple(p)
        if key in self._danger_cache:
            return self._danger_cache[key]
        threat = sum(weight / (1. + dist(p, q) / 30.) for q, weight in self._threat_samples)
        deaths, stamp = self.casualties.get(self._cell(p), (0., self.now))
        presence, observed = self.presence.get(self._cell(p), (1., self.now))
        denominator = max(1., presence * max(0., 1. - (self.now - observed) / 120.))
        result = threat + deaths * max(0., 1. - (self.now - stamp) / 120.) / denominator
        if len(self._danger_cache) < self.MAX_UNITS + self.MAX_COVERS + 256:
            self._danger_cache[key] = result
        return result

    def _support(self, p):
        """Exact nearby support; conservative aggregation of distant cells.

        The farthest cell member bounds distance, so aggregating a remote cell
        cannot overstate its support. These are policy counts, not engine force.
        """
        if p not in self._support_cache:
            total = 0.
            for center, radius, positions in self._support_cells.values():
                distance = dist(p, center)
                if distance <= 90. + radius:
                    total += sum(1. / (1. + dist(p, q) / 30.) for q in positions)
                else:
                    total += len(positions) / (1. + (distance + radius) / 30.)
            self._support_cache[p] = total
        return self._support_cache[p]

    def pressure(self, p):
        """Conservative ratio; evaluate exact support near decision thresholds."""
        if p not in self._pressure_cache:
            threat = self.danger(p)
            lower_support = sum(len(positions)/(1.+(dist(p,center)+radius)/30.)
                                for center,radius,positions in self._support_cells.values()) if threat else 0.
            upper_ratio = threat/max(1.,lower_support)
            # The lower support bound can only overstate pressure. If even this
            # bound is below the recovery threshold, individual distances cannot
            # change the decision. Sensitive cases retain the original calculation.
            self._pressure_cache[p] = (upper_ratio if upper_ratio < .7 else
                                      threat/max(1.,self._support(p)))
        return self._pressure_cache[p]

    def _goal(self, squad, units, s, assigned):
        center = tuple(sum(u.position[i] for u in units) / len(units) for i in range(2))
        scores = {}
        available = [o for o in s.objectives[:128] if o.reachable is not False]
        hold_majority = sum(o.owner == s.owner for o in available) > len(available) / 2
        for obj in s.objectives[:128]:
            # Unknown routes may be attempted with native navigation; a confirmed
            # unreachable objective is excluded. Never label an attempted route reachable.
            if obj.reachable is False:
                continue
            priority = (2. if obj.owner == s.owner else 1.) if hold_majority else (1. if obj.owner == s.owner else 2.)
            scores[obj.key] = (obj.value * priority
                               - dist(center, obj.position) / 150.
                               - self.pressure(obj.position) * .5 - assigned.get(obj.key, 0))
            if obj.owner == s.owner:
                # Reinforce a deteriorating owned area without dragging every
                # squad away from its current assignment on a brief contact.
                scores[obj.key] += min(2., self.pressure(obj.position))
        current = scores.get(squad.goal)
        if scores and (self.now >= squad.next_goal or current is None):
            best = max(scores, key=lambda k: (scores[k], k))
            if current is None or scores[best] > current + max(.5, abs(current) * .25):
                squad.goal = best
            squad.next_goal = self.now + 2.
        if squad.goal not in scores:
            squad.goal = None
        return next((o for o in s.objectives if o.key == squad.goal), None)

    @staticmethod
    def _objective_position(unit, objective):
        if objective.capture_radius is None:
            return objective.position
        # Stable positions inside the observed capture area avoid funneling the
        # entire army onto a point. These are navigation goals, not cover claims.
        seed = 2166136261
        for character in unit.identity.unit + ':' + str(unit.identity.incarnation):
            seed = ((seed ^ ord(character)) * 16777619) & 0xffffffff
        angle = seed * 2.399963229728653
        radius = objective.capture_radius * (.35 + .4 * ((seed >> 16) / 65535.))
        return (objective.position[0] + cos(angle) * radius,
                objective.position[1] + sin(angle) * radius)

    def _friendly_side(self, position, goal, s):
        """Bounded local support/contact boundaries from confident observations."""
        if goal not in self._boundary_cache:
            friends = [u.position for u in s.units if u.alive and u.owner == s.owner
                       and dist(u.position, goal) <= 120]
            threats = [(m.contact.position, confidence * m.contact.strength)
                       for m in self.memory.values() for _, confidence in [m.estimate(self.now)]
                       if confidence >= .5 and m.contact.strength > 0 and dist(m.contact.position, goal) <= 180]
            boundary = None
            if friends and threats:
                support = tuple(sum(p[i] for p in friends) / len(friends) for i in range(2))
                # Opposing threats must not average into an apparently safe
                # direction. Keep the eight strongest local approaches separate.
                strongest = sorted(threats, key=lambda item: item[1] / (30 + dist(item[0], goal)), reverse=True)[:8]
                boundary = (support, tuple(p for p, _ in strongest))
            self._boundary_cache[goal] = boundary
        boundary = self._boundary_cache[goal]
        if boundary is None:
            return True  # Existing suitability/safe-time gates still apply.
        support, contacts = boundary
        return all(dist(support, contact) >= 10 and
                   sum((position[i] - (support[i] + contact[i]) / 2) *
                       (contact[i] - support[i]) for i in range(2)) <= 0 for contact in contacts)

    def _cover(self, u, goal, s, build=False, defending=False):
        local_memory = [m for m in self.memory.values() if dist(m.contact.position, goal) <= 180]
        if build and local_memory and not any(m.estimate(self.now)[1] >= .5 for m in local_memory):
            return None
        candidates = []
        for c in s.covers[:self.MAX_COVERS]:
            if build and (c.key in self.built_sites or len(self.built_sites) >= self.MAX_CELLS):
                continue
            lease = self.reservations.get(c.key)
            if lease and lease[0] != u.identity:
                continue
            if any(until > self.now and dist(c.position, position) < 3.
                   for position, until in self.members[u.identity].blocked_destinations.items()):
                continue
            native = (not build and 'nativeCover' in s.capabilities and
                      c.native_score is not None and c.observer == u.identity)
            if (c.destroyed or c.occupied or c.reachable is not True or
                    (not native and (c.escape is not True or c.protection is None or
                                     c.protection <= 0 or c.firing_access is not True)) or
                    (dist(c.position, u.position) > self.MAX_MOVE_LEG + 3 if native else dist(c.position, goal) > 60)):
                continue
            if native and c.firing_access is False and (defending or goal == u.position):
                continue
            if native and dist(c.position, goal) > dist(u.position, goal) + 3:
                continue
            visit = self.members[u.identity].cover_visit
            capture_position = any(o.capture_radius is not None and
                dist(goal, o.position) <= o.capture_radius and dist(c.position, o.position) <= o.capture_radius * .9
                for o in s.objectives)
            if (native and not defending and visit and visit[0] == c.key and self.now >= visit[1] and
                    dist(u.position, goal) > 3 and not capture_position):
                continue  # Intermediate cover is a short stop, not a permanent goal.
            if build != (c.build_seconds is not None):
                continue
            if (defending or build) and not self._friendly_side(c.position, goal, s):
                continue
            if build and (c.tools is not True or c.terrain is not True or c.safe_seconds is None
                          or c.build_seconds <= 0 or c.safe_seconds < c.build_seconds + 5
                          or self.danger(c.position) > .5):
                continue
            # Native default preference is not calibrated armor protection.
            # Limit the uncalibrated native preference so a large default score
            # cannot outweigh observed danger and the intended destination.
            preference = c.native_score / (1. + abs(c.native_score)) * 3 if native else c.protection * 3
            midpoint = tuple((u.position[i] + c.position[i]) / 2 for i in range(2))
            score = (preference - dist(u.position, c.position) / 30 - self.danger(c.position)
                     - self.danger(midpoint) * .5 - dist(c.position, goal) / 120.)
            state = self.members[u.identity]
            changed_threat = any(
                all(sum((point[i] - u.position[i]) * (old[i] - u.position[i]) for i in range(2)) <
                    .5 * dist(point, u.position) * dist(old, u.position) for old in state.cover_threats)
                for point, weight in self._threat_samples if weight > 0 and dist(point, u.position) <= 100)
            if c.key == state.occupied_cover and u.in_cover is True and not changed_threat:
                score += 1.5  # Retain a useful occupied site under stable conditions.
            candidates.append((score, c.key, c))
        return max(candidates, key=lambda x: (x[0], x[1]))[2] if candidates else None

    def _advance_destination(self, u, goal, s, stop_distance=0., max_leg=None):
        state = self.members[u.identity]
        if any(signature[0] == 'move' and until > self.now for signature, until in state.failed.items()):
            # A shorter endpoint must not turn the same failed advance into an
            # immediate retry. Urgent withdrawal does not use this helper.
            return None
        distance = dist(u.position, goal)
        travel = min(self.MAX_MOVE_LEG if max_leg is None else max_leg, distance - stop_distance)
        if travel <= 0:
            return None
        reserved, stationary = [], []
        for other in s.units:
            if other.identity == u.identity or not other.alive or other.owner != s.owner:
                continue
            member = self.members.get(other.identity)
            action = member.action if member else None
            if action and action.destination is not None and action.expires > self.now:
                reserved.append(action.destination)
            else:
                stationary.append(other.position)
        # Bounded lateral alternatives let a spawn pile depart concurrently.
        # Native navigation still decides the route; these are endpoint spacing
        # candidates, not claims of cover or obstacle clearance.
        viable = []
        direction = tuple((goal[i]-u.position[i])/distance for i in range(2))
        # Route scoring is a local heuristic. Bound its sample separately from
        # the full pressure model used for withdrawal/objective decisions.
        threats = sorted(((point, weight) for point, weight in self._threat_samples
                          if weight > 0 and dist(point, u.position) <= 120),
                         key=lambda item: item[1] / (30. + dist(item[0], u.position)), reverse=True)[:8]
        def route_danger(position):
            cell = self._cell(position)
            deaths, stamp = self.casualties.get(cell, (0., self.now))
            presence, observed = self.presence.get(cell, (1., self.now))
            denominator = max(1., presence * max(0., 1. - (self.now - observed) / 120.))
            return (sum(weight / (1. + dist(position, point) / 30.) for point, weight in threats) +
                    deaths * max(0., 1. - (self.now - stamp) / 120.) / denominator)
        candidates = []
        for fraction in (1., .75, .5):
            candidates.append(tuple(u.position[i]+direction[i]*travel*fraction for i in range(2)))
        for fraction in (1., .75, .5):
            leg = travel*fraction
            for side in (4., -4., 8., -8., 12., -12., 16., -16., 20., -20.):
                if abs(side) > leg*.75:
                    continue
                forward = sqrt(leg*leg-side*side)
                candidates.append((u.position[0]+direction[0]*forward-direction[1]*side,
                                   u.position[1]+direction[1]*forward+direction[0]*side))
        for destination in candidates:
            if any(until > self.now and dist(destination, position) < 3.
                    for position, until in state.blocked_destinations.items()):
                continue
            if any(dist(destination, position) < 3. for position in reserved):
                continue
            gap = min((dist(destination, position) for position in stationary), default=float('inf'))
            if gap >= 3. and not threats and not self.casualties:
                return destination
            midpoint = tuple((u.position[i] + destination[i]) / 2 for i in range(2))
            exposure = route_danger(destination) + route_danger(midpoint)
            # Favor measurable progress, while observed threat and casualty
            # concentrations can justify a shorter or lateral approach.
            cost = exposure + len(viable) * .005 + dist(destination, goal) / 1000.
            viable.append((gap < 3., cost, -min(gap, 3.), len(viable), destination))
        # Stationary bodies are a preference, not permanent reservations. Native
        # collision/navigation resolves the route; active endpoints stay distinct.
        return min(viable)[-1] if viable else None

    def _issue(self, u, s, action, reason, destination=None, target=None, stance=None, site=None):
        state = self.members[u.identity]
        if action not in s.capabilities or self._issued_this_step >= self.order_budget:
            return None
        signature = (action, destination, site, target)
        if state.failed.get(signature, -1) > self.now:
            return None
        state.failed = {k: v for k, v in state.failed.items() if v > self.now}
        if len(state.failed) > 16:
            state.failed.pop(next(iter(state.failed)))
        self.sequence += 1
        self._issued_this_step += 1
        state.revision += 1
        timeout = 20. if action == 'attack' and self._anti_armor(u) else 8.
        if action in {'move', 'cover'} and destination is not None:
            # Native slow infantry covered about one policy unit per second in
            # recorded trials. Allow slower travel and startup without treating
            # serialization as arrival; stalled orders still expire finitely.
            timeout = min(60., max(8., dist(u.position, destination) / .75 + 5.))
        if action == 'build':
            timeout = next(c.build_seconds + 5. for c in s.covers if c.key == site)
        intent = Intent(u.identity, state.revision, self.sequence, action, reason, self.now + timeout,
                        destination, target, stance, site, self.now + .75)
        self._release(u.identity)
        if site:
            self.reservations[site] = (u.identity, self.now + timeout + 4.)
        state.action = intent
        state.wait_reason = reason
        if action == 'attack' and self._anti_armor(u) and state.armor_target != target:
            state.armor_target = target
            state.armor_failures = state.armor_repositions = 0
        if reason == 'AT firing reposition':
            state.armor_repositions += 1
        if action == 'cover':
            state.cover_threats = tuple(point for point, weight in self._threat_samples
                                       if weight > 0 and dist(point, u.position) <= 100)[:8]
        elif action == 'move':
            state.occupied_cover = None
            state.cover_role = None
        if reason == 'travel posture':
            state.travel_posture_after = self.now + 30.
        state.next_decision = self.now + .2
        return intent

    def step(self, s, completions=()):
        if not isfinite(s.time) or s.time < 0:
            raise ValueError('invalid simulation time')
        if any(u.in_cover is not None and type(u.in_cover) is not bool for u in s.units):
            raise ValueError('invalid cover occupation')
        if any(u.projectile_model is not None and (not isinstance(u.projectile_model, str) or
                not 1 <= len(u.projectile_model) <= 128) for u in s.units):
            raise ValueError('invalid projectile model')
        if (len(s.units) > self.MAX_UNITS or len(s.contacts) > self.MAX_CONTACTS
                or len(s.covers) > self.MAX_COVERS or len(s.objectives) > 128
                or len(s.events) > self.MAX_EVENTS or len(s.contact_identities) > 4096):
            raise ValueError('snapshot exceeds work budget')
        if (len({i.unit for i in s.contact_identities}) != len(s.contact_identities) or
                any(i.match != s.match or not isinstance(i.unit, str) or not i.unit or
                    type(i.incarnation) is not int or i.incarnation < 1 for i in s.contact_identities)):
            raise ValueError('invalid contact identities')
        if s.friendly_presence is not None and (len(s.friendly_presence) > self.MAX_UNITS or
                any(len(p) != 2 or not all(isfinite(v) for v in p) for p in s.friendly_presence)):
            raise ValueError('invalid friendly presence')
        if any(u.weapon_model is not None and (not isinstance(u.weapon_model, str) or
                not 1 <= len(u.weapon_model) <= 128) for u in s.units):
            raise ValueError('invalid weapon model')
        for item in (*s.units, *s.contacts, *s.covers, *s.objectives):
            if len(item.position) != 2 or not all(isfinite(v) for v in item.position):
                raise ValueError('invalid position')
        for contact in s.contacts:
            if contact.kind not in {'infantry', 'vehicle'}:
                raise ValueError('invalid contact kind')
            if type(contact.allied) is not bool or (contact.allied and contact.enemy is not False):
                raise ValueError('invalid contact alliance')
            if contact.visible_to is not None and (not isinstance(contact.visible_to, frozenset) or
                    len(contact.visible_to) > self.MAX_UNITS or any(
                        not isinstance(i, Identity) or i.match != s.match or not isinstance(i.unit, str) or
                        not i.unit or type(i.incarnation) is not int or i.incarnation < 1
                        for i in contact.visible_to)):
                raise ValueError('invalid contact observers')
            if (not isfinite(contact.observed_at) or not isfinite(contact.strength)
                    or contact.strength < 0 or not isfinite(contact.fresh_for) or not 0 < contact.fresh_for <= 2.):
                raise ValueError('invalid contact')
        if len({c.identity.unit for c in s.contacts}) != len(s.contacts):
            raise ValueError('duplicate contact identity/incarnation')
        if len({u.identity.unit for u in s.units}) != len(s.units):
            raise ValueError('duplicate unit identity/incarnation')
        for event in s.events:
            if len(event.units) > self.MAX_UNITS or (event.position is not None and
                    (len(event.position) != 2 or not all(isfinite(v) for v in event.position))):
                raise ValueError('invalid event')
            if event.observed_at is not None and (not isfinite(event.observed_at) or
                    not 0 <= event.observed_at <= s.time):
                raise ValueError('invalid event observation time')
        for cover in s.covers:
            if cover.native_score is not None and (type(cover.native_score) not in (int, float) or
                    not isfinite(cover.native_score) or cover.observer is None or cover.observer.match != s.match):
                raise ValueError('invalid native cover preference')
            if any(v is not None and (not isfinite(v) or v < 0) for v in
                   (cover.protection, cover.build_seconds, cover.safe_seconds)):
                raise ValueError('invalid cover score/time')
        if any(not isfinite(o.value) or o.value < 0 for o in s.objectives):
            raise ValueError('invalid objective value')
        if any(o.capture_radius is not None and (type(o.capture_radius) not in (int, float) or
                not isfinite(o.capture_radius) or o.capture_radius <= 0) for o in s.objectives):
            raise ValueError('invalid objective capture radius')
        if len({c.key for c in s.covers}) != len(s.covers) or len({o.key for o in s.objectives}) != len(s.objectives):
            raise ValueError('duplicate spatial identity')
        if (s.match, s.owner) != (self.match, self.owner):
            order_budget = self.order_budget
            self.__init__()
            self.order_budget = order_budget
            self.match, self.owner = s.match, s.owner
        if s.time < self.now:
            raise ValueError('simulation time reversed without new match')
        self.now = s.time
        self._danger_cache.clear()
        self._pressure_cache.clear()
        self._boundary_cache.clear()
        if s.friendly_presence is not None:
            counts = {}
            for position in s.friendly_presence:
                cell = self._cell(position)
                counts[cell] = counts.get(cell, 0) + 1
            for cell, count in counts.items():
                old, stamp = self.presence.get(cell, (0., self.now))
                self.presence[cell] = (max(count, old * max(0., 1. - (self.now - stamp) / 120.)), self.now)
        self.presence = dict(sorted(((k, v) for k, v in self.presence.items() if self.now - v[1] < 120.),
                                    key=lambda kv: kv[1][1])[-self.MAX_CELLS:])
        identities = [u.identity for u in s.units]
        if len(set(identities)) != len(identities):
            raise ValueError('duplicate unit identity')
        units = {u.identity: u for u in s.units[:self.MAX_UNITS]
                 if u.identity.match == s.match}
        for identity in list(self.members):
            u = units.get(identity)
            if not u or not u.alive or u.owner != s.owner or not u.infantry:
                self._revoke(identity)
                del self.members[identity]
        for u in units.values():
            if not u.alive or u.owner != s.owner or not u.infantry:
                continue
            if u.identity not in self.members:
                self.members[u.identity] = Member(u.owner, u.move_at_will and not u.direct_control,
                                                  serviced_at=self.now)
            if not u.move_at_will or u.direct_control:
                self._revoke(u.identity)
        for event in s.events[:self.MAX_EVENTS]:
            if event.key in self.events:
                continue
            if len(self.events) >= self.MAX_EVENTS:
                raise ValueError('event deduplication budget exhausted; require new match')
            self.events[event.key] = self.now
            if event.kind == 'allied_death' and event.confirmed and event.position is not None:
                cell = self._cell(event.position)
                observed = self.now if event.observed_at is None else event.observed_at
                if self.now - observed < 120.:
                    n, old_stamp = self.casualties.get(cell, (0., observed))
                    stamp = max(old_stamp, observed)
                    self.casualties[cell] = (n * max(0., 1. - (stamp - old_stamp) / 120.) +
                        max(0., 1. - (stamp - observed) / 120.), stamp)
            if event.origin != 'player':
                continue
            for identity in event.units:
                if identity not in self.members:
                    continue
                if event.kind in {'move', 'attack', 'direct_control', 'mode'}:
                    self._revoke(identity)
                if event.kind == 'mode' and event.mode == 'move_at_will':
                    self.members[identity].enrolled = not units[identity].direct_control
        self.casualties = dict(sorted(((k, v) for k, v in self.casualties.items()
                                      if self.now - v[1] < 120.), key=lambda kv: kv[1][1])[-self.MAX_CELLS:])
        # Player events and identity revocations win over a simultaneous arrival.
        # Valid completions then win over action expiry and ammo/target changes.
        self.completions = [(intent, status, self.acknowledge(intent, status))
                            for intent, status in completions]
        self.reservations = {k: v for k, v in self.reservations.items()
                             if v[1] > self.now and v[0] in self.members}
        visible = self._observe(s)
        launchers = [u for u in units.values() if u.identity in self.members and self.members[u.identity].enrolled and
            self._anti_armor(u) and u.ammo is not None and u.ammo > 0 and
            u.readiness not in {'aiming', 'firing', 'reloading'}]
        armor_scores = {}
        for identity, contact in visible.items():
            if contact.kind != 'vehicle':
                continue
            distances = [dist(u.position,contact.position) for u in launchers
                if (contact.visible_to is None or u.identity in contact.visible_to) and dist(u.position,contact.position) <= 100]
            if distances:
                armor_scores[identity] = (len(distances), -sum(distances))
        if self._armor_focus not in armor_scores or self.now >= self._armor_focus_after:
            self._armor_focus = max(armor_scores,key=lambda i:(armor_scores[i],i)) if armor_scores else None
            self._armor_focus_after = self.now + 3.
        self._threat_samples = tuple((position, m.contact.strength * confidence)
            for m in self.memory.values() for position, confidence in [m.estimate(self.now)])
        cells = {}
        for u in units.values():
            if u.alive and u.owner == s.owner:
                cells.setdefault(self._cell(u.position), []).append(u.position)
        known_ids = {u.identity.unit for u in units.values()}
        latest_contacts = {i.unit: i.incarnation for i in s.contact_identities}
        for contact in s.contacts:
            if (contact.allied and not contact.dead and contact.visible and contact.identity.match == s.match
                    and contact.identity.unit not in known_ids
                    and contact.identity.incarnation >= latest_contacts.get(contact.identity.unit, 0)
                    and 0 <= self.now - contact.observed_at <= contact.fresh_for):
                cells.setdefault(self._cell(contact.position), []).append(contact.position)
        self._support_cells = {}
        self._support_cache.clear()
        for cell, positions in cells.items():
            center = tuple(sum(p[i] for p in positions) / len(positions) for i in range(2))
            self._support_cells[cell] = (center, max(dist(center, p) for p in positions), positions)
        available_cover = {c.key: c for c in s.covers}
        for identity, state in self.members.items():
            state.blocked_goals = {key: until for key, until in state.blocked_goals.items() if until > self.now}
            state.wait_reason = ('player control' if not state.enrolled else
                'paused' if s.paused else units[identity].readiness if
                units[identity].readiness in {'aiming', 'firing', 'reloading'} else
                state.action.reason if state.action else 'awaiting service')
            action = state.action
            if not action:
                continue
            unit = units[identity]
            armor_opportunity = (action.action == 'move' and action.reason not in {'withdraw', 'AT firing reposition'} and
                'attack' in s.capabilities and self._anti_armor(unit) and
                unit.readiness not in {'aiming', 'firing', 'reloading'} and
                any(self._can_attack(unit, contact) and dist(unit.position, contact.position) <= 100 and
                    (contact.visible_to is None or identity in contact.visible_to)
                    for contact in visible.values()))
            if armor_opportunity:
                # A short vehicle sighting must not wait for a travel leg's
                # completion/timeout. Native preflight still rechecks the shot;
                # urgent withdrawal below keeps priority over this opportunity.
                self.acknowledge(action, 'cancelled')
                state.revision += 1
                state.next_decision = self.now
                continue
            invalid_target = action.target is not None and (action.target not in visible or
                not self._can_attack(units[identity], visible[action.target]) or
                (visible[action.target].visible_to is not None and identity not in visible[action.target].visible_to))
            cover = available_cover.get(action.site)
            invalid_site = action.site is not None and (cover is None or cover.destroyed or
                cover.reachable is not True or (cover.occupied and action.action != 'stance'))
            if cover is not None and action.reason in {'defensive cover', 'safe defensive site'}:
                squad = self.squads.get(units[identity].squad)
                objective = next((o for o in s.objectives if squad and o.key == squad.goal), None)
                invalid_site = invalid_site or objective is None or not self._friendly_side(cover.position, objective.position, s)
            if action.action == 'build' and cover is not None:
                invalid_site = invalid_site or cover.tools is not True or cover.terrain is not True or (
                    cover.safe_seconds is None or cover.safe_seconds < action.expires - self.now
                    or self.danger(cover.position) > .5)
            if invalid_target or invalid_site:
                self.acknowledge(action, 'cancelled')
                state.revision += 1
        if s.paused:
            return []
        self._issued_this_step = 0
        self._decisions_this_step = 0
        groups = {}
        for identity, member in self.members.items():
            if member.enrolled:
                groups.setdefault(units[identity].squad, []).append(units[identity])
        self.squads = {k: v for k, v in self.squads.items() if k in groups}
        owned_objectives = [o for o in s.objectives if o.owner == s.owner and o.reachable is not False]
        threatened_objectives = [o for o in owned_objectives if self.pressure(o.position) >= .7 or
            any(c.enemy is True and dist(c.position, o.position) <= (o.capture_radius or 15.) + 15.
                for c in visible.values())]
        if len(groups) >= 4 and owned_objectives:
            if self.reserve_squad not in groups:
                # One small intact group is sufficient; retain its identity
                # until losses remove it instead of rotating the whole army.
                self.reserve_squad = min(groups, key=lambda k: (len(groups[k]), k))
        else:
            self.reserve_squad = None
        intents, assigned = [], {}
        valid_objectives = {o.key for o in s.objectives}
        for key, squad in self.squads.items():
            if squad.goal in valid_objectives:
                assigned[squad.goal] = assigned.get(squad.goal, 0) + len(groups[key]) / 12.
        scheduled = sorted(groups.items())
        # Rotate both squad and member priority. All identities are observed
        # every tick; at most 32 new orders can compete for the bounded queue.
        offset = self._schedule_cursor % max(1, len(scheduled))
        scheduled = scheduled[offset:] + scheduled[:offset]
        pressure = {}
        urgent_contacts = tuple(c for c in visible.values() if c.urgent)
        for key, group in scheduled:
            urgent = {u.identity for u in group if u.urgent_danger or
                any(dist(c.position, u.position) < 30 for c in urgent_contacts)}
            ratio = max(self.pressure(u.position) for u in group)
            pressure[key] = (urgent, ratio)
        # Give threats a head start, not an unlimited monopoly on service.
        # All safety invalidation still runs even after the dispatch budget is
        # spent. Busy soldiers do not keep their group ahead of waiting groups.
        def service_age(unit):
            member = self.members[unit.identity]
            if member.action or self.now < member.next_decision:
                return -1.
            return self.now - (member.serviced_at if member.serviced_at is not None else self.now)
        scheduled.sort(key=lambda item: -(max(service_age(u) for u in item[1]) +
            (5. if pressure[item[0]][0] or pressure[item[0]][1] > 1.6 or
             (item[0] in self.squads and self.squads[item[0]].state == 'withdraw') else 0.)))
        for key, group in scheduled:
            group.sort(key=lambda u: u.identity)
            offset = (self._schedule_cursor * 32) % len(group)
            group[:] = group[offset:] + group[:offset]
            group.sort(key=lambda u: -(service_age(u) + (5. if u.identity in pressure[key][0] else 0.)))
            squad = self.squads.setdefault(key, Squad())
            previous_goal = squad.goal
            if previous_goal in assigned:
                assigned[previous_goal] -= len(group) / 12.  # Count living soldiers, excluding self.
            objective = self._goal(squad, group, s, assigned)
            squad.reserve = key == self.reserve_squad and not threatened_objectives
            if key == self.reserve_squad:
                center = tuple(sum(u.position[i] for u in group) / len(group) for i in range(2))
                choices = threatened_objectives or owned_objectives
                objective = min(choices, key=lambda o: (dist(center, o.position), o.key))
                squad.goal = objective.key
            previous_support = (squad.support_goal, squad.support_position)
            # In objective-free scenes, rally toward observed stationary owned
            # support. Moving squads must not chase each other indefinitely.
            anchors = {}
            if objective is None and not self.memory:
                support_danger_limit = min(self.danger(u.position) for u in group) + .1
                anchors = {f.identity: f for f in units.values() if f.alive and f.owner == s.owner
                           and (f.reachable is True or (f.reachable is None and 'path' in s.capabilities)) and f.squad != key
                           and not f.direct_control and (not f.move_at_will or f.covering)
                           and self.danger(f.position) <= support_danger_limit}
            if objective is not None or self.memory or not anchors:
                squad.support_goal, squad.support_position = None, None
            else:
                if squad.support_goal not in anchors:
                    center = tuple(sum(u.position[i] for u in group) / len(group) for i in range(2))
                    squad.support_goal = min(anchors, key=lambda identity:
                        (dist(center, anchors[identity].position) + 30 * self.danger(anchors[identity].position), identity))
                position = anchors[squad.support_goal].position
                if (previous_support[0] != squad.support_goal or squad.support_position is None or
                        dist(squad.support_position, position) > 5):
                    squad.support_position = position
            support_changed = (previous_support[0] != squad.support_goal or
                (previous_support[1] is not None and squad.support_position is not None and
                 dist(previous_support[1], squad.support_position) > 5))
            if support_changed:
                for u in group:
                    state = self.members[u.identity]
                    if state.action and state.action.reason == 'friendly support':
                        self.acknowledge(state.action, 'cancelled')
                        state.revision += 1
                        state.next_decision = self.now
            if previous_goal is not None and previous_goal != squad.goal:
                for u in group:
                    state = self.members[u.identity]
                    if state.action and state.action.reason == 'objective':
                        self.acknowledge(state.action, 'cancelled')
                        state.revision += 1
                        state.next_decision = self.now
            if objective:
                assigned[objective.key] = assigned.get(objective.key, 0) + len(group) / 12.
            # Evaluate danger once for the entire squad. Iteration order must not
            # let a safe member undo another member's withdrawal decision.
            urgent_members, ratio = pressure[key]
            if ratio > 1.6 or urgent_members:
                squad.state = 'withdraw'
                squad.regroup_until = self.now + 5.
            elif squad.state == 'withdraw' and ratio < .7 and self.now >= squad.regroup_until:
                squad.state = 'regroup'
                squad.regroup_until = self.now + 3.
            # Pick moving members once per step, leaving at least one verified
            # ready coverer stationary. Missing readiness never implies cover.
            live = {f.identity for f in group}
            squad.moving &= live
            coverers = {f.identity for f in group if f.covering and f.readiness in {'ready', 'firing'}
                        and f.ammo is not None and f.ammo > 0 and
                        not self._anti_armor(f) and any(
                            c.visible_to is not None and f.identity in c.visible_to and
                            (objective is None or dist(c.position, objective.position) <= 100)
                            for c in visible.values()) and
                        not (self.members[f.identity].action and
                             self.members[f.identity].action.action in {'move', 'cover', 'build'})}
            alternating = (len(group) > 1 and bool(coverers) and not urgent_members
                           and self.now >= squad.individual_until)
            if alternating:
                outcomes = [self.members[i] for i in squad.moving]
                relevant = lambda member: (member.last_action is not None and
                    member.last_action.sequence > squad.advance_sequence and
                    member.last_action.action in {'move', 'cover'})
                failed = any(relevant(m) and m.last_status in {'failed', 'uncertain', 'cancelled'} for m in outcomes)
                arrived = bool(outcomes) and all(relevant(m) and m.last_status == 'completed' and
                                                m.action is None for m in outcomes)
                if failed or (squad.moving and self.now - squad.waiting_since > 30):
                    # Abandon coordination on failure; a timeout is not arrival.
                    # Individual tactics still retain their action backoffs.
                    alternating = False
                    squad.individual_until = self.now + 10.
                    squad.moving.clear()
                elif not squad.moving or arrived:
                    # Preserve alternation first; use verified model identity
                    # to prefer an MG coverer and SMG movers within that wave.
                    stationary = min(coverers, key=lambda i: (i not in squad.moving,
                        units[i].weapon_model != 'bar', i))
                    candidates = sorted(live - {stationary}, key=lambda i: (i in squad.moving,
                        units[i].weapon_model not in {'thompson','thompson_30','thompson_m1928'}, i))
                    squad.moving = set(candidates[:max(1, len(group) // 2)])
                    squad.waiting_since = self.now
                    squad.advance_sequence = self.sequence
                if not coverers - squad.moving:
                    # Loss of covering access ends the coordinated wait.
                    alternating = False
            else:
                squad.moving.clear()
            for u in group:
                state = self.members[u.identity]
                urgent = u.identity in urgent_members
                if state.action:
                    if state.action.expires <= self.now:
                        self.acknowledge(state.action, 'uncertain')
                    elif not urgent and squad.state != 'withdraw':
                        continue
                    elif not urgent and state.action.reason == 'anti-armor response':
                        continue  # Fresh target/ammunition invalidation already ran above.
                    elif (state.action.reason == 'withdraw' and state.action.destination is not None
                          and self.danger(state.action.destination) < self.danger(u.position)):
                        continue
                    else:
                        # Invalidate queued ordinary work even when no verified
                        # fallback exists. Native urgent responses keep control.
                        self.acknowledge(state.action, 'cancelled')
                        state.revision += 1
                if self.now < state.next_decision and not urgent:
                    state.wait_reason = 'order cooldown'
                    continue
                if self._issued_this_step >= self.order_budget or self._decisions_this_step >= self.MAX_DECISIONS:
                    state.wait_reason = 'awaiting service'
                    continue  # Safety invalidation above still runs for every unit.
                self._decisions_this_step += 1
                state.serviced_at = self.now
                assigned_objective = objective
                if objective and objective.key in state.blocked_goals:
                    alternatives = [o for o in s.objectives if o.reachable is not False and
                                    o.key not in state.blocked_goals]
                    assigned_objective = min(alternatives, key=lambda o:
                        (dist(u.position, o.position) + 30 * self.danger(o.position), o.key), default=None)
                state.assignment = assigned_objective.key if assigned_objective else None
                goal = assigned_objective.position if assigned_objective else None
                if squad.state == 'withdraw':
                    if (not urgent and self._anti_armor(u) and
                            u.readiness not in {'aiming', 'firing', 'reloading'}):
                        vehicles = [c for c in visible.values() if self._can_attack(u, c) and
                            dist(u.position, c.position) <= 100 and
                            (c.visible_to is None or u.identity in c.visible_to)]
                        if vehicles:
                            target = min(vehicles, key=lambda c: (c.identity != self._armor_focus,
                                dist(u.position, c.position), c.identity))
                            intent = self._issue(u, s, 'attack', 'anti-armor response', target=target.identity)
                            if intent:
                                intents.append(intent)
                                continue
                    fallback = [f.position for f in units.values() if f.alive and f.owner == s.owner
                        and (f.reachable is True or (f.reachable is None and 'path' in s.capabilities)) and dist(u.position, f.position) > 5
                                and self.danger(f.position) + .1 < self.danger(u.position)]
                    fallback += [c.position for c in s.covers[:self.MAX_COVERS]
                                 if c.reachable is True and c.escape is True and not c.destroyed
                                 and not c.occupied and c.protection is not None and c.protection > 0
                                 and self.danger(c.position) + .1 < self.danger(u.position)]
                    # A failed best route must not hide other usable anchors.
                    # Bound intermediate-point evaluation as well as submissions.
                    candidates = sorted(set(fallback), key=lambda p: (self.danger(p) + dist(p, u.position) / 100., p))[:8]
                    for goal in candidates:
                        # Preflight and execute only a bounded local leg. A safe
                        # distant anchor does not prove this intermediate point safer.
                        distance = dist(u.position, goal)
                        destination = tuple(u.position[i] + (goal[i] - u.position[i]) *
                                            min(self.MAX_MOVE_LEG, distance) / distance for i in range(2))
                        intent = (self._issue(u, s, 'move', 'withdraw', destination)
                                  if self.danger(destination) < self.danger(u.position) else None)
                        if intent:
                            intents.append(intent)
                            break
                    continue
                if squad.state == 'regroup' and self.now < squad.regroup_until:
                    state.wait_reason = 'regrouping'
                    continue
                targets = {k: c for k, c in visible.items() if self._can_attack(u,c) and dist(c.position, u.position) <= 100
                           and (c.visible_to is None or u.identity in c.visible_to)}
                supported_advance = (((alternating and u.identity in squad.moving) or
                    self._nearby_fire_support(u, goal, units, visible)) and
                    not self._anti_armor(u) and goal is not None and dist(u.position, goal) > 15 and
                    all(dist(u.position, c.position) > 35 and not c.urgent for c in targets.values()))
                if targets and not supported_advance:
                    if (not u.in_cover and 'nativeCover' in s.capabilities and
                            u.readiness not in {'aiming', 'firing', 'reloading'}):
                        shelter = self._cover(u, u.position, s)
                        if shelter and shelter.native_score is not None and dist(u.position, shelter.position) <= 3:
                            intent = self._issue(u, s, 'cover', 'nearby combat cover', shelter.position, site=shelter.key)
                            if intent:
                                intents.append(intent)
                                continue
                    score = lambda c: c.strength / (1. + dist(c.position, u.position)) + (10 if c.urgent else 0) + (
                        2. if self._anti_armor(u) and c.identity == self._armor_focus else 0.)
                    target = max(targets.values(), key=score)
                    previous = targets.get(state.target)
                    if previous and score(target) <= score(previous) * 1.4:
                        target = previous
                    state.target = target.identity
                    squad.state = 'engage'
                    if u.readiness in {'aiming', 'firing', 'reloading'} and not urgent:
                        continue
                    if (self._anti_armor(u) and state.armor_target == target.identity and
                            state.armor_repositions < min(2, state.armor_failures) and
                            not urgent and not target.urgent and dist(u.position, target.position) > 35 and
                            not any(c.kind == 'infantry' and dist(u.position, c.position) <= 35
                                    for c in visible.values())):
                        # A timed-out attack is not a range measurement. Try at
                        # most two short, path-checked approaches, only after
                        # native aiming/reloading has stopped and without a
                        # nearby infantry threat. Preserve each movement leg.
                        destination = self._advance_destination(u, target.position, s, max_leg=8.)
                        if destination is not None and self.danger(destination) <= self.danger(u.position) + .15:
                            intent = self._issue(u, s, 'move', 'AT firing reposition', destination)
                            if intent:
                                intents.append(intent)
                                continue
                    if self._anti_armor(u) and not self._armor_ready(u, target, list(units.values())):
                        state.wait_reason = 'AT readiness window'
                        continue
                    intent = self._issue(u, s, 'attack', 'visible target', target=target.identity)
                    if intent:
                        intents.append(intent)
                    else:
                        state.wait_reason = 'attack retry cooldown'
                    continue
                state.target = None
                state.armor_wait = None
                # Losing visual contact does not finish an observed reload or
                # burst. Preserve native weapon work before ordinary movement,
                # cover/stance changes or construction; withdrawal ran above.
                if u.readiness in {'aiming', 'firing', 'reloading'} and not urgent:
                    continue
                if self._anti_armor(u) and u.ammo == 0:
                    # Loaded ammunition alone cannot establish that reserves are
                    # exhausted. Protect an empty specialist near owned support
                    # while native reload can resume; never invent a resupply RPC.
                    anchors = [f.position for f in units.values() if f.identity != u.identity and
                               f.alive and f.owner == s.owner and not self._anti_armor(f) and
                               dist(f.position, u.position) <= 60 and
                               self.danger(f.position) + .1 < self.danger(u.position)]
                    state.wait_reason = 'AT ammunition unavailable'
                    if anchors:
                        anchor = min(anchors, key=lambda p: (self.danger(p), dist(u.position, p), p))
                        destination = self._advance_destination(u, anchor, s, stop_distance=5.)
                        if destination is not None:
                            intent = self._issue(u, s, 'move', 'friendly support', destination)
                            if intent:
                                intents.append(intent)
                    continue
                if goal is None and self.memory:
                    goal = min((m.estimate(self.now)[0] for m in self.memory.values()),
                               key=lambda p: dist(u.position, p))
                support_goal = goal is None and squad.support_position is not None
                if support_goal:
                    goal = squad.support_position
                if goal is None:
                    state.wait_reason = 'route reassignment cooldown' if state.blocked_goals else 'no observed objective or support'
                    continue
                defending = assigned_objective is not None and assigned_objective.owner == s.owner
                if assigned_objective is not None:
                    goal = self._objective_position(u, assigned_objective)
                    if squad.reserve:
                        # Hold a dispersed ring inside the owned area. These
                        # are native navigation endpoints, not claimed cover.
                        dx, dy = goal[0] - assigned_objective.position[0], goal[1] - assigned_objective.position[1]
                        radius = hypot(dx, dy)
                        if radius > 0:
                            scale = min(12., (assigned_objective.capture_radius or 15.) * .8) / radius
                            goal = (assigned_objective.position[0] + dx * scale,
                                    assigned_objective.position[1] + dy * scale)
                if u.squad_leader and len(group) > 1:
                    peers = [f for f in group if f.identity != u.identity]
                    # A medoid follows an actual nearby subgroup, avoiding a
                    # centroid inside a wall or between separated squad halves.
                    anchor = min(peers, key=lambda f: (sum(dist(f.position, p.position) for p in peers), f.identity))
                    if dist(u.position, anchor.position) > 15:
                        goal = anchor.position
                squad.state = 'defend' if defending else 'travel'
                if alternating and u.identity not in squad.moving:
                    state.wait_reason = 'supporting advance'
                    continue
                state.wait_reason = 'holding objective' if dist(u.position, goal) <= 3 else 'route cooldown'
                if squad.reserve and dist(u.position, goal) <= 3:
                    state.wait_reason = 'local reserve'
                cover = self._cover(u, goal, s, defending=defending)
                if supported_advance and cover and dist(u.position, cover.position) > 10:
                    cover = None  # Cover selection must respect the same short stage.
                site = None
                if not cover and defending and 'build' in s.capabilities and len(groups) > 1 and key == sorted(groups)[0]:
                    active_build = any(self.members[f.identity].action and
                                       self.members[f.identity].action.action == 'build' for f in group)
                    site = None if active_build else self._cover(u, goal, s, build=True)
                if cover:
                    if dist(u.position, cover.position) <= 1.5 and u.in_cover is True:
                        state.wait_reason = state.cover_role or ('defensive hold' if defending else 'temporary shelter')
                        self.reservations[cover.key] = (u.identity, self.now + 12.)
                        intent = (self._issue(u, s, 'stance', 'settle in cover', stance=cover.stance,
                                              site=cover.key) if cover.native_score is None and u.stance != cover.stance else None)
                    else:
                        intent = self._issue(u, s, 'cover', 'friendly support' if support_goal else
                                             'defensive cover' if defending else 'advance via cover',
                                             cover.position, stance=cover.stance, site=cover.key)
                elif site:
                    intent = self._issue(u, s, 'build', 'safe defensive site', site.position, site=site.key)
                elif dist(u.position, goal) > (10 if support_goal else 3):
                    # Native navigation handles the route; short legs limit commitment.
                    destination = self._advance_destination(u, goal, s, 10. if support_goal else 0.,
                                                           10. if supported_advance else None)
                    reason = ('supported advance' if supported_advance else 'friendly support' if support_goal else
                              'objective' if objective else 'last observed contact')
                    intent = None
                    if (destination is not None and u.stance != 'standing' and self.now >= state.travel_posture_after
                            and dist(u.position, goal) > 25
                            and not any(weight > 0 and dist(u.position, point) <= 90
                                        for point, weight in self._threat_samples)
                            and self._cell(u.position) not in self.casualties):
                        # Recover travel speed after combat leaves a soldier prone.
                        # No known nearby threat is a posture heuristic, not proof
                        # of safety. Native urgent responses can still interrupt.
                        intent = self._issue(u, s, 'stance', 'travel posture', stance='standing')
                    if intent is None and destination is not None:
                        intent = self._issue(u, s, 'move', reason, destination)
                else:
                    intent = None
                if intent:
                    intents.append(intent)
        self._schedule_cursor += 1
        return intents
