# Autonomous Move at will: implementation plan

Status: implementation in progress, acceptance gates incomplete. September 7, 2026 UTC.
See [current implementation and saved-trial findings](TACTICAL_AI_PROGRESS.md).
Basis: [live mapping and evidence](TACTICAL_AI_MAPPING.md).

**Architecture update, September 7:** the user selected AI acting through ordinary
player commands, with joining-client support required. Follow the
[player-command migration and validation plan](TACTICAL_PLAYER_COMMAND_MIGRATION_PLAN.md).
It supersedes native-query and brain-property-edit implementation suggestions below;
the tactical behavior requirements remain. Synchronization is an acceptance gate,
not an established property of the current implementation.

## Intended behavior

Enable the tactical controller for the local player's infantry. Setting a squad
to Move at will hands it over: it chooses useful objectives, moves, fights, takes
cover, withdraws, and establishes defensible positions without further commands.
Deselecting the squad does not stop it. The ordinary workflow needs no repeated
waypoints, confirmations, target assignments, or manual babysitting.

The initial scope is owned, opted-in infantry in the user's multiplayer-versus-bot
test. Do not control allied players' troops or silently replace the opponent AI.
When attaching, adopt eligible owned infantry already in Move at will; observe
subsequent mode commands and spawns. Validate ownership before adopting any unit.
Vehicles and specialist construction are later extensions, not implicit support.

September 7 follow-up: utilize stranded owned infantry, including squad leaders.
Leaders should initially follow their squad; distinguish an individual command
from native leader commands that expand to the whole squad. Sole survivors must
not remain excluded merely because they retain leader status. Preserve manual
reclamation. Implement actual cover occupation, not just posture changes.

Enemy vehicles require infantry anti-tank responses: coordinate suitable loaded
launchers against observed targets, then extend to validated AT rifles and rifle
grenades. Timed AT hand grenades are a last resort. Armor-facing and weak-point
selection require verified weapon/armor and geometry data; do not invent
penetration or assume every vehicle is vulnerable to the same weapon.

Clarification, September 7: deployment is fully autonomous and headless, controlling
hundreds of individual infantry concurrently. Enumeration, spatial relationships,
decisions and command submission must not depend on camera position, selection,
input focus or screen coordinates. UI input is only a diagnostic for player
reclamation. Validate bounded work and fair service at 128, 256, 512 and 1024
units; distinguish offline scale tests from measured native throughput.

Clarification, September 7: concurrent movement is required. Eligible squads and
individual soldiers should start and continue moving together where practical;
do not wait for one soldier to arrive before allowing the next to move. A bounded
submission budget is an implementation constraint, not a reason to turn army
movement into a single-file sequence. Optimize observation, decision and native
submission throughput where they prevent useful concurrent movement.

Disperse troops from spawn onward, before enemies are locally visible. The user
reports that artillery can reach from roughly half the map away, and that dense
groups are especially vulnerable near the combat line to grenades, other area
effects and directly controlled high-capacity machine guns (including a 250-round
MG). Treat these as explicit gameplay requirements: avoid dense spawn piles and
crowded approaches/objective centers. Do not require detecting an unseen gun or
inventing its position before applying ordinary spacing. Exact safe distances
depend on validated unit geometry, routes and weapon effects; spacing is risk
reduction, not immunity to artillery or machine guns.

Hold position relinquishes controller ownership. A manual move/attack or direct
control suspends autonomous orders for the affected units. Remain suspended until
the player explicitly re-enables Move at will; a mode-command event must work even
when its numeric value is already unchanged. Selection alone is not a takeover.
One soldier's takeover must not disable unrelated squads. Squad-wide commands
apply to the addressed members. Controller-issued commands must not trigger the
manual-takeover detector or revoke their own enrollment.

## Smallest robust design

Use native navigation, collision, ballistics, animation, targeting and order
execution. Add a compact rule-based policy with scored choices and short state
memory. No LLM in the real-time loop, training pipeline, new navigation mesh,
general-purpose behavior-tree framework, or separate database service.

Start with three production modules under `headless/`, independent of the lobby
host and record-only recorder:

| Module | Responsibility |
|---|---|
| `tactical_bridge.js` | Validated game-thread observations, native command submission, ownership/generation checks, cancellation and acknowledgements |
| `tactical_policy.py` | Pure decisions over snapshots: contacts, goals, retreat, cover, firing, formations and fortification |
| `tactical_controller.py` | Standalone attach/run/stop CLI, bounded queues, configuration, logs and bridge lifecycle |

Keep all authoritative runtime pointers inside the bridge. Policy intents use a
verified unit ID plus match generation and an order revision. Raw heap pointers
are not durable identities. Add more files only when a concrete need warrants it.

Prefer one authoritative decision maker and the game's synchronized order path.
The observed actor-order entry is an execution primitive, not proof of network
replication. Establish authority and serialization before multiplayer deployment.
If native property changes cannot replicate, use synchronized move/cover orders
to implement withdrawal; do not depend on divergent client-side brain edits.

Initial scheduling targets, subject to profiling: local decisions up to 5 Hz,
squad decisions around 1 Hz, objective/fortification evaluation every 2 seconds.
Use simulation time, dirty events and staggered units. Cap work and queued intents;
discard obsolete ones. Native execution continues between policy updates.

One current action per unit, completion/failure tracking, target commitment and
minimum improvement before switching prevent order spam. Immediate danger can
interrupt ordinary commitment. An action is not complete merely because a native
function returned a pointer.

## Implementation sequence and acceptance gates

Each phase produces code, a repeatable test, saved evidence and a short result.
Only enabled features must have passed their dependencies. An unmapped capability
stays disabled with a stated limitation; it must not be replaced with guessed data.

### 0. Establish reliable observations and command execution

Extend the existing probes instead of building a second discovery framework.
Resolve unit identity/reuse, ownership, match generation, selection-independent
enumeration, objective ownership/locations, and the correct simulation callback.
Decode per-unit contact visibility, team, death and last-observed time. Map weapon
loaded/reloading/aiming state. Treat health and suppression as unknown until mapped.

Trace normal player commands through serialization, execution and cancellation.
Validate the native factories, calling conventions, argument lifetimes and
allocator/destructor ownership. Implement a single-unit stance action, then a short
move, then cover placement. Add a finite timeout and one acknowledgement per intent.
Never replay an action after an uncertain acknowledgement; inspect current state.

**Self-validation:** capture baseline; issue each small test action through the
bridge in the bot test; verify actual stance/position/cover changes and continued
game ticks. Exercise unselected units, death, ID reuse, manual orders, direct
control, mode changes and match exit. Restore test state where possible. Offline
fixtures must reject stale generation, ownership changes and cancelled revisions.
Use a small manual scene only when a native setup primitive is not yet verified.

**Pass:** a persistent owned unit can be addressed without selection, a real action
completes, manual reclamation invalidates pending orders before submission, and
stale identities never receive commands. Stop rather than guess on an unknown build.

### 1. Handoff, useful goals and retreat

Introduce a small squad state machine: choose objective, travel, engage, defend,
withdraw, regroup. Score existing map objectives by value/ownership, distance,
local support, threat and other squads already assigned. Preserve a goal until
captured, invalid, too dangerous, or substantially less useful than an alternative.
In objective-free modes, use validated friendly positions and observed contacts;
do not invent unseen enemy destinations.

Use the engine's force estimates once their friendly/enemy meanings are verified.
Test clearing `no_retreat` for enrolled units and tune the two ratios one at a
time. The value 10 is a threshold, not proof of aggressive behavior. Store original
properties and restore only on the same live unit generation, without overwriting
subsequent legitimate changes. Never patch global human/weapon archives for opt-in AI.

Choose a reachable fallback toward friendly support or useful rear cover, away
from the strongest observed threat. Use different enter/exit thresholds and a
regroup interval to avoid repeated advance/retreat switches. Native grenade escape
and other urgent responses remain able to interrupt policy actions.

**Self-validation:** unattended opt-in squad captures or defends a useful objective;
stronger opposition triggers withdrawal, weaker opposition does not cause permanent
flight, and removal of danger allows recovery. Repeat after deselection and with
two independently assigned squads. Compare against unmodified settings in matched
scenes; record losses, exposure, objective progress and direction reversals.

**Pass:** useful autonomous progress, repeatable withdrawal/recovery, no oscillation
or global side effects. If ratio changes do not improve behavior, retain the native
settings and implement explicit withdrawal using the validated order path.

### 2. Cover-aware movement and stance

Query native cover candidates near the next short movement goal. Rank reachable
candidates by protection from the known threat direction, native firing access,
friendly support, distance and occupancy. Prefer existing native cover suitability
queries; if exposure or firing access cannot be established, mark it unknown and
do not claim the score measures protection. Sample only a bounded number of
candidates. Reserve chosen slots and release reservations on arrival failure,
death, abandonment or lease expiry.

Select standing/crouched/prone according to cover and firing needs. Advance between
nearby useful positions. Retry a failed route only after circumstances change or
a bounded backoff. Exclude destroyed, occupied or unreachable cover.

**Self-validation:** wall facing toward/away from threat; partial cover; blocked
route; two units competing for one slot; cover destroyed during approach; grenade
danger while settled. Verify arrival and actual stance, not just accepted orders.

**Pass:** avoids known-exposed/unreachable choices when valid alternatives exist,
does not crowd reserved cover, and recovers without repeated identical orders.

### 3. Stop, settle and fire

During a viable engagement, let the native attack order work. Avoid movement and
stance changes while the soldier is settling aim, firing a useful burst or
reloading unless danger warrants it. Use native readiness/aim state if available;
otherwise validate a conservative settling interval for the supported weapons.
Do not modify spread or damage, and do not place soldiers into shared direct control.

**Self-validation:** same weapon, veterancy, range, stance, target and cover, with
and without the policy. Record actual shots, hits, damage, time to first shot and
unnecessary order replacements. If shot/hit telemetry is missing, build a bounded
fire-event probe and verify event attribution before reporting accuracy benefits.
Also test a threat that requires interrupting the firing position.

**Pass:** reduces movement-induced interruptions without freezing units under
danger. Claim accuracy improvement only when paired measurements support it.

### 4. Threat memory and target commitment

Reuse native perception records where verified. Retain a small bounded history per
contact: last observed position/time, observed motion, confidence and threat class.
Confidence decays with simulation time. Forget confirmed deaths and expired records.
Do not refresh remembered positions from an unseen actor's current world transform.

Project observed motion only a short distance/time, clamped to plausible movement;
stationary or ambiguous contacts yield a wider uncertainty region rather than a
precise prediction. Keep a viable target until lost, invalid or significantly less
dangerous than a new threat. Last-seen positions guide movement/defense, not perfect
tracking or automatic fire at unobserved actors.

**Self-validation:** enemy visible, moves behind obstruction, changes direction while
unseen, returns, dies, or is replaced at a reused address. Two similar targets
must not cause continuous retargeting; an urgent close threat must interrupt.

**Pass:** decisions use only validated observations, memory expires, and target
stability improves without ignoring emergencies.

### 5. Squad spacing and alternating advances

Concurrent army movement and dispersion take priority over optional alternating
advances. Maintain spacing both within and between squads, including immediately
after spawn and while approaching or occupying objectives. Give multiple soldiers
distinct useful destinations with enough lateral spread where native navigation
permits it; collinear endpoint reservations must not create a one-at-a-time queue.
Avoid sending every soldier to the same objective center. Preserve useful spacing
near contact without forcing a rigid formation through a narrow route.

Maintain a small shared squad record: goal, members, assigned cover slots and
moving/covering group. Split by current weapon capability and readiness, with a
simple balanced fallback. Move one group while the other has a viable covering
position; switch after arrival. One-survivor and low-ammunition cases fall back to
individual tactics. Do not require regrouping in exposed ground merely to preserve
a formation. Avoid fixed formations through narrow routes.

**Self-validation:** mass spawn and simultaneous departure, open approach, narrow gate, casualties in either group, blocked
arrival, loss of the covering group's firing access and one soldier reclaimed by
the player. Observe real spacing, simultaneous exposure, idle time and progress.

**Pass:** no reservation deadlock, endless wait for a dead member or unnecessary
whole-squad exposure; still reaches or sensibly abandons its objective.

Measure physical concurrent movement rather than counting accepted orders: first
movement latency per soldier, start-time spread, moving-unit fraction over time,
nearest-neighbor distances and local crowd counts at spawn, on approach and near
contact. Observe whether formation changes reduce concentrated exposure to MGs,
grenades and artillery in controlled scenes. Record native and policy processing
cost separately. Fix performance or reservation bottlenecks that serialize troop
movement; do not call throughput validated merely because all units eventually
receive an order or eventually arrive. Tactical covering groups may deliberately
hold when they have a verified useful covering role, but must not impose global
one-soldier-at-a-time movement.

### 6. Autonomous defensive positions and fortification

Implement this in two stages. First occupy existing defensible positions. Then
build physical defenses only after the native construction path is understood.
An observed `FortifySequence` class is not proof of digging or placing sandbags.
Map its factory and lifecycle, plus tool/item requirements, terrain restrictions,
build progress, resource consumption, cancellation and multiplayer replication.

Use a sparse, bounded spatial grid shared by controlled squads. Maintain decaying
observed threat, friendly support and confirmed allied-death counts, plus validated
objectives and routes. A unit disappearing from a sensor is not a confirmed death.
Use only team-visible information and confirmed events. Start within the current
match; do not carry stale casualty maps between maps or assume knowledge of allied
players' hidden plans.

Estimate a **local contact boundary** from threat and support around each objective,
not one straight line across the whole map. Consider defensive candidates on its
friendly side and near useful approaches, with an escape route and weapon-appropriate
range. Reject exposed, unreachable, obstructive or unsupported placements.

Repeated allied deaths increase the danger penalty. They may justify covering an
approach from an offset position, changing routes, or retreating—not constructing
at the death location. Avoid double-counting events and normalize casualty weight
by observed friendly presence when that denominator is reliable.

Short-lived motion projections can suggest an anticipated boundary only after
phase 4 passes. Low confidence means reuse existing cover or wait; do not start
slow construction based solely on a speculative enemy position. Require enough
estimated safe time to finish. Initially allow one active construction job per
squad and one reservation per site; interrupt for danger and suppress duplicate
building. Retain the defense while useful and re-evaluate when the objective or
contact direction changes. Keep some squads mobile rather than fortifying all units.

**Self-validation:** defend an objective behind contact; contact shifts; repeated
casualties occur on an exposed approach; enemy feints/reverses; insufficient tools;
invalid ground; blocked retreat path; threat arrives during construction; two
squads select the same site. Measure completed usable defenses, builder losses,
construction waste, objective retention and delay to reinforcement.

**Pass:** defensible positions are selected without manual designation; no repeated
construction at invalid/dangerous sites; correct resource use and interruption.
If building is unavailable, retain autonomous occupation of existing cover and
explicitly mark physical fortification unsupported rather than simulate success.

## Validation tooling and responsibility

Codex should run validation itself wherever the game exposes a verified mechanism.
Do not repeatedly ask the user to toggle states or report whether units moved.
Build only the tools required by the next failing gate:

| Tool | Minimal scope |
|---|---|
| Existing observer/trace extensions | Identity, visibility, readiness, death events, order origin and construction observations |
| One scenario runner under `diagnostics/` | Capture setup, run baseline/treatment, observe outcomes, stop on failures; verified native setup or a saved test scene |
| One result summarizer | JSON evidence plus readable pass/fail/unverified report and paired metrics |
| Focused tests under `tests/` | Pure decision cases, stale/duplicate intents, identity reuse, cancellation, memory expiry and reservation release |

Use controlled bot-only scenarios for mutations. Do not silently reset or terminate
an unrelated active match to prepare a test. Reuse small fixtures for policy tests;
add live cases only for actual engine behavior. Test each feature alone, then its
interaction with existing features. Keep previous features fixed while tuning one.

Every run records executable/mod identity, config/source hashes, scene conditions,
simulation timestamps, enrolled unit generations, observations used, decision
reasons, issued/accepted/completed/failed/cancelled orders, casualties and resource
changes where relevant. Bound log size and flush summaries outside hot callbacks.

Use repeated matched baseline/treatment trials and report sample counts and spread;
a single favorable battle is not evidence of better AI. Set concrete scenario
thresholds after baseline capture and before examining treatment results. Hard
requirements include zero orders to the wrong/dead generation, no replay of stale
intents and no duplicate construction for an occupied reservation. Profile increasing
unit counts against the same baseline and reduce update work if simulation cost grows.

## Integration and release gates

Ship progressively: goal selection/retreat, then cover/firing, then memory/squad
coordination, then defensive occupation and construction. All six requested feature
areas remain in scope; unfinished later phases are reported, not called complete.

Before multiplayer use, verify actual command authority and replication with an
independent client: unit positions, orders, inventory/construction outcomes and
match state must agree. If no second client is available, complete all useful local
work and label synchronization unverified; do not claim bot-only tests prove it.

Validate deselection, controller stop/loss, game pause, unit death, ownership change
and a new match. On a stalled controller, expire pending intents and yield to native
AI. Property restoration must be scoped to live matching identities; a bridge
watchdog handles recoverable disconnects. Unexpected injected-script loss may need
a reload to restore temporary properties, so prefer designs that minimize such
changes and document the demonstrated recovery behavior.

Completion means autonomous objective pursuit, all enabled tactical/fortification
behaviors demonstrated, bounded resource use, reclamation/recovery tested and
multiplayer synchronization verified for the supported deployment. No delivery
estimate is assigned until the remaining native interfaces pass phase 0.
