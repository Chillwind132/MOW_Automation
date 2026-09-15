# Army operations implementation

Objective source: `goal-objective.md`, supplied September 7, 2026.
This work changes `headless/tactical_policy.py`, `headless/tactical_controller.py`,
`headless/tactical_operations.py` and the closed-bot scenario runner. The standalone
production admission gate remains unchanged. A controller already running retains
its earlier code until restarted.

## Implemented behavior

| Priority | Current behavior | Evidence still needed |
| --- | --- | --- |
| Utilization | Per-soldier assignment, service timestamp, waiting reason, bounded failed endpoints, cooldown and individual objective reassignment after three movement/cover failures. Individually controllable leaders follow a real squad subgroup. | Army-wide departure/stall rates in a fresh run. Group-only leaders retain the existing native paired-order restriction. |
| Cover | Actual native occupation remains required. Failed entry is monitored for stalls. Selection includes objective distance, sampled route danger, occupancy, bounded native preference, and retention hysteresis that is removed after a changed threat direction. Temporary shelter permits onward movement. | Native protection and outgoing firing access remain unverified; preference scores do not establish either. |
| AT | Loaded bazooka/verified HEAT selection, own current sighting and native target preflight. Shared targets, a maximum 1.5-second readiness window, nearby defensive bypass and longer bounded native attack commitment. Actual attributed projectile creation completes a firing attempt; aiming/reloading guards remain. | Repeatable vehicle damage/destruction, actual weapon range and different ammunition/weapon switching. An attack order is not proof of a feasible shot. |
| Purchasing | Observed armor pressure retained for 30 simulation seconds; choices held for 15 seconds. Effective rifle/assault/AT strength uses survivors, loaded ammunition, distance and recovery state. One purchase remains in flight until newly spawned infantry are observed. | Improved battlefield composition and resource utilization in live games. Unknown reserve ammunition is not exhaustion. |
| Fire and movement | Native support requires positive ready/recent-firing evidence, loaded ammunition and a current personal sighting. Current movement excludes a soldier from support. Relevant support can allow a complementary group to advance at most ten policy units per leg. Existing alternation/failure timeouts remain. | Covering observation is distinct from confirmed suppression; facing, outgoing obstruction and successful protected crossings still need trials. |
| Urban approaches | Bounded lateral/shorter endpoints, active endpoint separation, stationary-body preference, failed endpoint avoidance and observed danger/casualty cost. | Doorway capacity and validated passage waypoints are not mapped. Native navigation still owns routes. |
| Defense | Owned-objective pressure influences reinforcement. With at least four groups, one small stable reserve holds an owned area and responds to observed local threats. | Retention rates and counterattack performance. |
| Ammunition | Empty weapons are excluded from attacks requiring loaded rounds. Empty AT soldiers stop ordinary advances and can seek nearby safer infantry support. Native reload is protected. | Reserve inventory, switching and resupply actions are not verified or invoked. |

## Diagnostics and results

The bot battle saves `progress.json` atomically every ten wall-clock seconds.
Its `tactics` section includes assignment counts, waiting reasons, observed cover
occupation, service waits, action outcomes, policy/command timing and vehicle
engagement observations. Displacement is measured from the first observation,
which need not be spawn, and counts only currently observed soldiers.

Native observation maximum time remains separate from policy time and command
time. Offline policy timings do not measure engine stutter or frame rate.

Completion processing validates the snapshot and applies player reclamation before
accepting arrivals/shots; accepted completions precede timeout and ammunition
invalidation. Failed movements no longer inflate arrival counts.

Terminal collection retains the ordinary durable `finish-ai` identity checks and
requires clean tactical detachment. A zero CLI exit status alone never establishes
victory. The runner reads the captured native winner and matching durable match
identity to record `victory` or `defeat`; missing/conflicting evidence remains
`unknown`. An early stopped battle is `interrupted`. The final summary retains the
terminal score and its evidence path. Observed projectile creation and subsequent
target death are separate facts; damage amount and shooter kill attribution remain
unavailable.

## Remaining native work

The subsequent authorized [human-opponent trial](TACTICAL_HUMAN_TRIAL.md) produced
a confirmed native synchronization error. The first cover-scoring query occurred
inside the first divergent checksum interval; causation remains unresolved. The
controller was stopped and its hooks restored. The next-run German purchase
mapping selects a nine-person squad instead of one rifleman, and native cover
queries/actions are withheld in the explicit human-opponent diagnostic scope.

Grenade/smoke inventory queries exist, but the bridge explicitly reports
`throwSupported: false`. Purposeful throws still require verified trajectory,
friendly clearance, ordinary serialization, animation completion, consumption and
effect observations. No speculative throw command is enabled by this change.
The [grenade execution trace](TACTICAL_GRENADE_NATIVE.md) now maps equipment
selection, automatic approach and recovery inside the native weapon order. These
are static findings, not evidence of a successful or safe throw.

AT rifles, additional rifle grenades, armor orientation and precise aiming remain
unverified. No long flank, roof shot or weak-point aim is inferred from model names
or configuration. These require separate native trials before implementation can
honestly claim the requested behavior.

The previously running `movement_recovery_battle_20260907_1` started with earlier
source. It cannot validate these changes. The later victory and its source-version
limitations are recorded below.

## Offline verification

Run `py -B tests/run.py` and `node --check headless/tactical_bridge.js`.
New operation regressions cover route reassignment, leader following, AT timing,
completion/reclamation precedence, empty launchers, cover retention, adaptive
purchases, reserve response, supported movement and durable outcome identity.

The final route-scoring scale sample is under
`validation/local_archive/new_runs/operations_policy_scale_20260907_3`.
Median continuing policy times were 13.6, 20.5, 34.8 and 69.0 ms for 128, 256,
512 and 1,024 soldiers respectively, with 256 contacts and five repetitions.
The earlier unrestricted route scoring sample (`..._2`) regressed to about
157 ms at 1,024 soldiers. The final heuristic samples at most eight nearby threats
per movement decision; the full objective/withdrawal pressure model is preserved.
These results measure offline policy CPU, not native performance or frame rate.

The full suite before the final route-cost bound passed 389 tests, with both
JavaScript syntax checks passing. Its log is
`validation/local_archive/operations_suite_20260907_1.log`.

## September 7 follow-up and native findings

- Movement now detects 24 simulation seconds without net endpoint progress,
  in addition to 12 seconds stationary. Small sideways loops no longer reset
  both checks. Initial detours and observed pause/weapon work receive time.
- Defensive cover no longer inherits the two-second temporary-shelter expiry.
  Known obstructed firing access excludes combat/defensive candidates; unknown
  native firing access is still reported as unknown.
- After an AT attack fails without an observed shot, a loaded soldier may try
  up to two eight-unit, path-checked approaches. The policy preserves each leg,
  protects weapon work and refuses this approach near observed enemy infantry.
  Failure is not treated as a range measurement or damage evidence.
- Supporting soldiers require a current, relevant personal sighting. Tests that
  previously supplied only a `covering` flag now include actual contacts.
- Reports include prolonged waiting reasons, AT stages and pending recoveries.
  Service delay counts time awaiting service, excluding previous holding time.
- Result capture now compares the durable native start identity to the battle
  observed by the tactical runner. Missing start identity, failed collection or
  unverified detachment cannot produce a victory. Withheld collection is saved.

The first live attachment exposed a diagnostic authority bug: lobby member 4
and native player 2 represented the same local host. The guard now checks lobby
host membership in its own namespace and freezes both identities in the roster
signature. Remote humans and changed native ownership are still rejected.
The native-memory harness tests these cases; no production admission gate changed.

Live purchasing also exposed two composition mistakes. In the installed Robz
mod, `smgs(usa)` contains ten riflemen, a rifle-grenadier and a leader. Assault
requests now use catalog 879, `smgs2(usa)`, the single Thompson soldier. The
two-man `bazookers(usa)` team makes the launcher a group-only leader, excluded
from individual controller actions. AT requests now use catalog 855,
`riflemans_bar(usa)`, whose bazooka carrier is an individually controllable
member alongside rifle and BAR support. This costs more than the two-man team;
group-only launcher control remains unverified. The planner establishes a small
AT reserve before continuing to fill an SMG shortage.

The selected native catalog records and installed squad/breed definitions are
recorded in `validation/local_archive/operations_assault_template_20260907.json`.
An initial suspicion about the purchase handler's pointer argument was disproved:
the catalog's embedded name has the expected layout. That native call was not
changed. `operations_purchase_mapping_20260907.json` records the name comparison.

Live evidence is under
`validation/local_archive/new_runs/operations_followup_battle_20260907_*`.
Run 1 refused attachment without tactical orders; runs 2 and 3 were deliberately
interrupted to address the purchasing findings and have no terminal outcome.
Run 3 observed two owned objectives and native cover occupation. These runs
continued an already-started match; they are not controlled superiority trials.
Run 4 first used the corrected AT template; observed weapon snapshots include
bazookas. It was interrupted to fix rejected leader-follow orders. Run 5 reached
a verified **Team A 200–Team B 110 victory against three Heroic bots**. Its
`completion/run_20260907_215032_421715/completion_normalized.json` preserves the
native terminal score for match `959b6d23-fc09-4b3e-a27b-fdef16680b19`, native start
`0x6a9f61e5`. All 12 tactical hooks were verified restored before capture.
The match included several controller restarts with different source versions;
this establishes the outcome, not an uninterrupted fixed-build superiority trial.

The final segment observed three AT projectiles and 40 soldiers occupying native
cover at its last sample. AT target destruction was not confirmed by the tactical
metrics. Service wait reached 22.187 seconds, compared with 78.104 in an earlier
segment; changing battlefield conditions prevent a controlled performance claim.
Native command cost still reached 158.702 ms, so stutter remains unresolved.

Subsequent changes add age-based service priority, short supported advances for
single purchased SMG soldiers, and explicit control-coverage exclusions. Native
tracing showed that a serialized paired move sets group mode 2. A new proof record
retains control only for the exact two controller-commanded soldiers, validated
against current group membership, ownership, incarnations and enrollment revisions.
Manual reclamation or direct control invalidates that proof. Group-only leaders
are still excluded from independent orders. Native evidence is in
`operations_native_group_mode2_20260907.json` and
`operations_native_group_mode2_context_20260907.json` in the validation archive.
This continuation fix passed the native-memory harness, but its fresh live trial
was blocked by the previous match's durable recovery state before tactical orders.

The completed match remained `results_available` after `finish-ai`; by the next
attachment its statistics dialog was hidden. The journal has not been forced
forward or edited to bypass recovery. Future battle collection now immediately
attempts guarded `save-ai-results` after verifying the captured outcome, and
records cleanup failure separately without losing the score or replaying an
uncertain command. This follow-up cleanup is offline-tested, not live-validated.
`--battle-seconds` permits bounded 1–1800 second bot trials; early stops remain
interrupted and cannot establish a terminal outcome.

Later recovery resolved the hidden-dialog case through durable evidence. The
explicit `save-ai-results` action can now use journaled statistics only when the
same process/session/native match remains in the lobby, there are no unresolved
commands, and the journal proves terminal capture followed by successful normal
exit and statistics capture. The archived participant set, all score fields and
winner must agree with the saved completion. The live identity and absent dialog
are rechecked after saving; this branch performs no native dismissal or command
replay. Failed or incomplete proof leaves the match unresolved.

Live `run_20260907_222054_751097` saved the prior results and reached
`lobby_returned` using this recovery. The statistics dialog no longer needs to be
reopened. The full recovery suite passed **405 tests**, including changed identity,
winner, scores, missing participants, failed commands and a post-save identity
change. Log: `validation/local_archive/operations_recovery_suite_20260907.log`.
The next AI-only test setup was refused because two remote humans had joined the
open lobby; no tactical trial started and no players were removed. Read-only
roster evidence: `run_20260907_222149_597240`.

The full follow-up suite passed **402 tests**, with both JavaScript syntax checks
passing. The log is
`validation/local_archive/operations_followup_suite_20260907.log`.
The subsequent cleanup regression matrix covers success, rejection and timeout,
and preserves unknown outcomes for missing or mismatched match identity. The final
402-test suite and both syntax checks also passed; its log is
`validation/local_archive/operations_final_suite_20260907.log`.

The follow-up offline scale sample is `.../new_runs/operations_followup_scale_20260907`:
median continuing policy times were 15.0, 19.9, 34.9 and 73.2 ms for 128, 256,
512 and 1,024 soldiers. It does not measure native stutter.
