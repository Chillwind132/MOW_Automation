# Tactical implementation and evidence

In progress, September 7, 2026 UTC. This does **not** complete the
[implementation plan](TACTICAL_AI_IMPLEMENTATION_PLAN.md) or enable multiplayer release.

Current user-assisted test instructions and next-session status are in
[player handoff verification](TACTICAL_AI_HANDOFF_TEST.md). This document is a
chronological record: older test counts and outstanding-check lists below are
superseded by later entries. The latest full suite checkpoint passed 374 tests. Automated
direct-control suspension, explicit re-enrollment and deselection transitions now
have live evidence; see the handoff document for scope and remaining checks.

Live paired-follow checkpoint: after 69,307,226 complete evidence bytes, 62
accepted paired moves addressed 62 distinct leaders. All 62 later displaced by
more than 20 native world units from their submission positions (including those
that may subsequently have died). This proves displacement, not arrival, survival
or that every idle leader is now covered. Simulation time was 835.421 seconds.
Evidence: `paired_leader_follow_checkpoint_20260907.json`. The controller remains
live and the match outcome remains unverified.

## September 7: movement stall recovery and terminal capture follow-up

The native adapter now detects ordinary moves with less than one policy unit
of displacement over 12 simulation seconds. It uses existing snapshots, not
additional native calls. Aiming, firing, reloading and pause observations reset
the stationary window; detours count as progress even when moving away from
the goal. Stalls produce a failed acknowledgement and explicit evidence.
After the existing 10-second failure cooldown, ordinary advances avoid the
failed endpoint's three-unit neighborhood for 60 seconds and select another
bounded endpoint. Each soldier retains at most 16 such endpoints.

374 offline tests passed in 7.165 seconds, including stalled moves, detours,
combat waits, pauses and alternate endpoint selection. Evidence:
`full_suite_movement_recovery_20260907.log` in the external evidence root.
These tests do not establish native recovery success or a stutter improvement.

The sixth fair match remains outcome-unknown. Its controller observed gameplay
stop, but the native terminal result was not captured before the manager vanished.
The old game process later exited; this is not proof of a crash. The replacement
process was observed on the replay browser. No win has been inferred from flags.
The runner now distinguishes manager state 3 from other gameplay stops and
invokes guarded finish-ai immediately after all 12 tactical hooks are verified
restored. Result collection remains separately evidenced and needs live testing.

## September 7: snapshot model-name reuse and controlled observation profile

Weapon and loaded-projectile definitions are shared by many soldiers. The bridge
now decodes their bounded names once per locked inspection, keyed by pointer and
expected native type. The cache is local to that inspection; command preflight
and the next snapshot read fresh identities. A twelve-soldier native fixture
checks one decode per shared name, unchanged model values, and refreshed values
on the next snapshot. The exact previous source is saved as
`bridge_before_snapshot_model_cache_20260907.js` in the external evidence root.
346 tests passed in 5.852 seconds (`full_suite_snapshot_model_cache_20260907.log`),
and native syntax checking passed.

Controlled profile `snapshot_model_cache_profile_20260907_1` completed six
8-second windows: uninstrumented/current/previous/previous/current/uninstrumented.
Each instrumented window had 16 observations at absolute 2 Hz with no missed
slots. All hook sites were restored between windows. The previous native median
observation times were 45/49 ms; current medians were 49/47.5 ms. There is no
consistent native-time reduction in this sample. Previous RPC medians were
153.40/143.40 ms versus current 137.53/135.50 ms. Simulation-progress p95 gaps
were previous 156.15/125.29 ms and current 138.05/108.45 ms; uninstrumented gaps
were 77.79/62.04 ms. Simulation/wall ratios were previous .683/.872, current
.847/.904 and uninstrumented .978/1.005. Combat load changed over these successive
windows, and these are not render-FPS measurements or a proven stutter cure.
Only native observation was profiled; policy, supply and cover RPC cost were
not exercised by the performance scenario.

The previous heat controller stopped deliberately after 350 samples with no
error and all 12 hook sites restored. After profiling, the same sixth match
resumed automatically under `optimized_heat_battle_20260907_1` (PID 41952 at the
last process check). No match reset, unit or economy edits were made.

A separate read-only unlocked capture audit confirmed all five objectives had
capture-progress field 1.0: four identified team A, one team B, with 5,000-tick
reward intervals. Saved as `capture_progress_audit_20260907.json`. This supports
full capture rather than merely transient presence; it is not a final score or
victory. The installed Robz battle-zones definition uses a graduated points table,
so flag ownership alone must not substitute for the native terminal result.
The fair victory, remaining tactical features and production release gates are
still unfinished.

## September 7: loaded HEAT identity, close AT response and cover capacity

Mapped current filling identity: 843e50 returns inventory item +28; 818530 writes
that pointer with its round count at +2c. Bullet construction receives the filling
through the eStuffBullet RTTI cast at 863bc0. Constructor 863aa0 identifies vtable
df61d0 and the shared base entity-name string at +10. The bridge now exports the
bounded optional projectileModel, and the adapter preserves it without inferring
ammo type from weapon name. Mapping is saved in loaded_ammunition_identity.txt
and loaded_ammunition_constructor.txt under the usual mapping directory.

Installed Robz 1.30.10 definitions distinguish m1garand_grenade FG, WP and AP;
the AP entity is garand_heat_ammo, while FG is em_mk3_ammo. The read-only unlocked
sample confirmed current launcher fillings (not an atomic game snapshot):
`loaded_at_ammunition_verified_sample_20260907.json`. An initial diagnostic used
an incorrect slot offset and is retained as failed evidence in
`loaded_at_ammunition_sample_20260907.json`; the corrected read follows the
existing bridge's verified slot+1a8/fallback path. Exact archive entries and hashes
are saved in `loaded_ammunition_mod_definitions_20260907.json`.

Garand rifle grenades can now target vehicles only with known loaded
`garand_heat_ammo`; FG/WP/unknown fillings do not grant AT capability. Native
preflight rechecks the filling and rejects changed/unknown types or reloads.
Loaded HEAT is reserved from ordinary infantry targets and participates in the
existing shared target preference/travel interruption. No ammo switch, inventory
edit, penetration claim or armor weakpoint targeting is implemented by this step.

A loaded AT soldier can now respond to a freshly visible vehicle despite the
ordinary squad pressure withdrawal state, while explicit urgent danger and active
weapon work keep priority. The bounded response is not cancelled every tick merely
because the squad remains withdrawing. Loss of this soldier's own sighting cancels
its attack even if a teammate still sees the target. These are normal native attack
orders, with neither synchronized-impact nor actual vehicle destruction claimed.

Controller cover_leader_follow_battle_20260907_1 failed after 1,065 samples because
cover source tracking reached its old 256-identity bound. This happened before the
requested STOP was consumed. All 12 hook sites were restored; the native match
remained active. Capacity is now bounded at 4,096 distinct sources, and saturation
returns no identity for untracked candidates instead of halting unrelated unit
control. Tracked incarnations are retained. The latest full suite passed 346 tests
in 6.061 seconds (`full_suite_heat_and_cover_capacity_20260907.log`); native syntax
checking also passed. Tests include HEAT/FG changes, unknown native filling type,
reload rejection, adapter cancellation after filling changes, close AT response,
urgent danger and per-observer target loss.

The same sixth match now runs heat_response_battle_20260907_1 with these changes.
The last pre-stop sample at 1,346.839 simulated seconds held four of five flags;
that is not a victory result. Live HEAT firing and the final match outcome remain
unverified. Production release gates remain closed and the full goal is active.

## September 7: intact squad-leader follow through ordinary paired moves

The latest live checkpoint still had 27 intact squad leaders outside individual
control. Native helper aa3d50 expands a singleton leader order to its full squad;
its mapped multi-actor branch copies the explicitly selected recipients. The new
bot-only `leaderFollow` behavior adds a stranded, untouched leader to an already
planned objective move for one of its members. The primary member retains its
intended destination. Both actual actors are serialized, with no dummy actor,
duplicate recipient, membership edit, unit creation or altered movement statistic.

Native preflight observes details for both recipients, revalidates leader role,
shared native squad, eligible ownership, incarnation, zero manual revision,
control/cover/movement state and primary enrollment. A reclaimed leader, changed
role, foreign squad or direct control rejects the pair before submission. Python
selects only leaders more than 200 native units farther from the planned endpoint
than the moving member, skips observed reload/recent firing/cover, and limits
accepted follow inclusion to once per leader per ten simulated seconds. Leaders
remain outside individual tactical control while their intact squad scope would
expand a singleton order. Following depends on a member having a planned move;
this does not yet guarantee every idle squad leader is utilized.

343 tests passed in 5.886 seconds (`full_suite_leader_follow_20260907.log`), with
180 production-native and 200 combined-friendly harness cases. Expanded native
assertions verify an exact two-recipient vector, unchanged destination and
rejection after role/control/incarnation changes. Adapter tests check manual
reclamation, reload, cover, other squads, leader already ahead and cooldown. Native
syntax checking passed. These prove mocked admission/serialization; actual paired
movement still needs live observation.

`native_cover_battle_20260907_2` stopped deliberately after 906 samples. All 12
hook sites were restored; no terminal match was reported. Its cover-probe maximum
was 95.430 ms, not an FPS measurement. The same sixth native match continues under
`cover_leader_follow_battle_20260907_1`, loading paired follow and existing cover/AT
logic. No fair 1-vs-3 victory has been established; the full plan remains active.

## September 7: live cover occupation and combat-flow follow-up

The first integrated cover controller produced actual native occupation in the
sixth guarded match (`run_20260907_165743_240368`). Completed-run analysis of
`native_cover_battle_20260907_1` found 40 distinct soldiers observed in cover,
peak ten simultaneously, and 286 completed cover visits by 39 distinct soldiers.
One soldier had 24 visits: repeated completions do not establish sustained cover
or independent successes. Evidence: `native_cover_completed_checkpoint_20260907.json`.
The earlier partial checkpoint had 316 serialized cover orders and 261 completed
visits, 135 scored queries and 72 successful path queries. Source and position
checks were retained. This establishes occupation, not calibrated protection or
combat superiority.

Fixed follow-up policy gaps: native cover occupation retains the native-selected
posture instead of issuing a generic crouch order afterward. Intermediate cover
has a two-second stop after completed arrival, then permits continued advance;
cover inside the relevant objective capture area may remain useful. Read-only
cover probes now also run while a soldier has an active attack or observed weapon
work. Actual entry into nearby combat cover (within three policy units) still
waits for firing, aiming and reloading to finish. Urgent withdrawal remains prior
to ordinary combat decisions. The change does not invent firing access or claim
that the current native cover score measures protection.

151 policy, adapter and scenario tests passed in 0.848 seconds
(`cover_combat_flow_20260907.log`), including intermediate-cover departure, nearby
combat cover, preservation of active weapon work and attacking from existing
cover. An initial dataclass field-order error was corrected before this passing
run and before deployment. The latest full-suite checkpoint remains 340 tests;
these additional changes have the narrower relevant-suite result above.

The first controller stopped deliberately after 883 samples; all 12 hook sites
were restored. Maximum measured cover-probe call-chain cost was 96.131 ms and
native observation maximum 34 ms in that run. These maxima are not a controlled
FPS/stutter comparison. The same match now runs `native_cover_battle_20260907_2`,
loading the posture/combat-flow changes. No match reset, resource edits or victory
claim accompanies this update. Intact squad leaders and broader AT behavior
remain outstanding.

## September 7: bounded native cover integration enabled in bot trial

Implemented a complete initial local cover path in the existing adapter/policy.
The bot trial explicitly enables `nativeCover`; production gates and ordinary
army trials remain unchanged. At most one soldier is probed per simulated second,
with a 15-second per-soldier cooldown, at most eight ranked native candidates and
one path query for the selected candidate. Probing is limited to the vicinity of
objectives or fresh enemy contacts. Native query events enter the next snapshot.
Candidate storage is bounded to 128 slots and 65 simulated seconds, with owner,
revision, source identity and destruction checks. Native cover command preflight
rechecks the actual slot/source identity before serialization. Occupied positions
are excluded and existing policy reservations/backoff apply. Completion requires
arrival within 30 native world units plus observed native cover state 1 or 2.

Native weighted scores are kept separate from calibrated protection: protection,
firing access and escape remain unknown. This mode chooses a native-preferred,
path-checked position; it does not prove wall-facing quality, firing superiority,
escape safety or replication. It does not yet interrupt active combat to occupy
cover, and later performance evidence must assess the added RPC cost.

The full suite passed 340 tests in 6.312 seconds
(`full_suite_native_cover_20260907.log`). Integration fixtures cover query cadence,
path success versus blocked/expired/malformed results, authority mismatch, vector
release, source-bound submission, invalidation after revision changes, actual
occupation versus proximity, and unknown protection/firing access. These are
mocked checks, not live cover performance proof.

The fifth requested match ended naturally during
`bazooka_opportunity_battle_20260907_1`: B 200, A 0. Official result:
`run_20260907_165629_613359/completion_normalized.json`; saved normally in
`run_20260907_165712_027058`. Its controller completed 661 samples, 2,580 moves,
451 stances and 168 attack orders, then restored all 12 hook sites. No victory
or AT destruction success is inferred. The sixth guarded match and immediate
cover controller were launched through the normal CLI; controller destination
is `native_cover_battle_20260907_1`. Launch and live outcome still need checking.
No MP, unit-count or damage modifications were made.

## September 7: corrected vehicle audit and travel interruption

Audit correction: the earlier ad-hoc report used compact sensor field 2 (enemy)
as death; field 3 is nativeDeadPredicate. Its claim of zero enemy vehicle
sightings is invalid and the JSON checkpoint is marked superseded. A corrected
read at 20:46 UTC found 6,206 fresh enemy vehicle reports across 2,342 snapshots,
including 53 reports from bazooka observers and four enemy vehicle identities.
These include repeated cached sightings, not 6,206 distinct encounters. Evidence:
`bazooka_live_contact_checkpoint_corrected_20260907.json`. No serialized vehicle
attack was found in that prefix. Cover and objective counts were unaffected.

Of the 53 bazooka reports, 48 had a loaded, non-reloading, enrolled launcher
within the policy's 100-unit target-selection limit; five had an empty weapon
reloading. Unit 236 continued a travel leg during sightings; its later vehicle
attack attempt at 564.646 seconds was cancelled when fresh native preflight
returned no targets. This demonstrates a missed reaction opportunity, not a
reason to relax the visibility check or proof that every missed shot had the
same cause.

Loaded bazookas now cancel ordinary travel on a usable fresh local vehicle
sighting, allowing attack selection before the leg completes. Firing, aiming,
reloading and urgent withdrawal retain priority. Target preflight and authority
checks remain unchanged. Shared target preference also permits a loaded launcher
whose settled readiness is unknown; this prioritizes targets without asserting
that the weapon is ready to fire. Tests cover stale move completion after
replacement, missing local visibility, infantry contacts, empty/reloading/firing
weapons and out-of-range targets. 125 policy/adapter tests passed in 0.939 seconds
(`bazooka_travel_interrupt_20260907.log`). The shared-focus fixture was then
strengthened to exercise unknown readiness, with its rerun recorded separately.

Controller `bazooka_leader_battle_20260907_4` stopped cleanly after 2,601 samples,
81 normal purchases, 7,452 move orders, 757 stance orders and 671 infantry attack
orders. All 12 native hook sites were verified restored. The same native match
continues under `bazooka_opportunity_battle_20260907_1`, loading this fix and the
cover occupation contract. The match was not restarted or altered economically.
No qualifying win is established. Cover integration remains unfinished.

## September 7: cover occupation contract and fifth-match checkpoint

The running fifth match controller remains PID 33340, with its actual command
line verified before editing loaded source. Start evidence is
`run_20260907_163038_430374`; controller evidence is
`bazooka_leader_battle_20260907_4`. The previous continuation made code changes
and produced validation evidence, so it was progress rather than an idle wait.

At 20:45 UTC, a bounded read of 694,249,742 complete evidence bytes contained
2,202 observations. The latest simulation time was 815.482 seconds, playing and
unpaused, with A holding two flags and B three. All 171 eligible soldiers had
native cover state zero. No fresh enemy vehicle reports or serialized vehicle
attacks occurred in this evidence prefix. This cannot validate bazooka combat;
neutral vehicle records are not enemy sightings. The initial paused observation
and later unpaused activity verify that the paused-start admission fix allowed
this run to proceed. Saved checkpoint: `bazooka_live_contact_checkpoint_20260907.json`.

Fixed a separate policy defect: proximity to a selected cover point no longer
suffices to settle posture. Settling requires observed occupation and distance
within 30 native world units (1.5 policy units), matching the existing native
arrival trial. Otherwise the policy requests actual cover occupation. The
adapter maps exercised cover states 1/2 to occupied, zero to unoccupied, and
other integer states to unknown; invalid types/ranges are rejected. This does
not imply firing access, protection, or successful approach. Tests cover prone
soldiers at the point without occupation, unknown state, actual occupation,
occupation outside arrival tolerance, and malformed native state.

123 policy/adapter tests passed in 1.631 seconds:
`cover_occupation_contract_20260907.log`. These source changes are not loaded by
the current controller. Native candidate collection, cover submission integration,
intact squad-leader following, broader AT weapons and armor targeting remain
unfinished. No qualifying victory or release-gate promotion is claimed.

## September 7: requested 1-vs-3 Heroic validation and performance work

The full goal remains incomplete. No qualifying victory, complete urban
cover/fire integration, grenade/smoke behavior, or independent-client
synchronization has been established. Production run gates remain closed.
New evidence is under `validation/local_archive/new_runs`.

Current offline checkpoint: **320 tests passed in 7.934 seconds**
(`full_suite_owned_sensor_20260907.log`). Native harness counts are 163 production,
183 combined friendly, 10 bot roster/adoption and 4 path-watch cases. These are
mocked native checks, not proof of live stability.

Implemented:

- AI start admits the exact one-local-human versus three opposing Heroic-bot
  profile, retaining local hosting, readiness, exact settings, durable journal
  and native admission checks. Duplicate members/slots are rejected.
- Continuous `bot_battle` retains the runtime for up to 30 minutes and replenishes
  through ordinary native rifle purchases. No MP, unit-count or combat-stat hacks
  were used. One purchase is observed before another is attempted. Only observed
  recruits receive native Move-at-will orders, and enrollment waits for the mode
  change. Manual revisions, direct control and expiry cancel adoption.
- Supply RPC events are consumed by the following snapshot, preventing future
  shot timestamps from being applied to older observations. Death accounting
  deduplicates deaths rather than every bullet. Purchasing reserves observer
  capacity headroom. A STOP file in the run directory stops the controller before
  another observation/order without finishing the native match.
- Commands refresh complete registry identity/ownership but detailed eligibility,
  modes and revision only for the addressed soldier. Scheduled observations still
  read all owned infantry. Shared squad membership is read once per inspection;
  command preflight omits unrelated weapon inventories. A 12-soldier fixture
  verifies other enrollment survives and memory reads fall by at least 25%.
- Routine perception uses validated tuple-v1 fields and bounded rotating sensor
  pages (256 records/read, 4096-record structural limit). Attack preflight finds
  its selected target beyond the current page. Routine sensor decoding now skips
  owned soldiers already present in the full snapshot; explicit sensor queries
  remain detailed. Foreign tuple fields and omission of owned sensor position
  reads are tested. Newly owned identities invalidate former enemy memory.
- Dense-spawn movement tries bounded lateral endpoints as well as shorter straight
  legs. A 32-soldier fixture gets 25 separated destinations instead of three.
  Validated native capture radii provide stable individual destinations inside
  75% of the horizontal radius; unknown radii retain center targets. These goals
  do not establish cover, obstacle clearance or actual capture.
- Objective scoring uses relative threat/support. Allocation counts living
  soldiers, normalized to twelve soldiers per score unit, rather than treating
  every depleted squad as a full squad. A regression checks twelve one-soldier
  remnants count like one twelve-soldier squad. Pressure calculation uses a
  conservative support bound below decision thresholds and the original exact
  calculation near thresholds.
- Unmapped numeric postures quarantine that unit until a supported posture is
  observed, preserving identity. Invalid types/positions still stop observation.
- Transport calls include five-second cancellation deadlines for attach, script
  creation/load/unload, RPC and detach. Expiry while a native job is still pending
  now explicitly reports unexecuted rejection; a late callback cannot execute it.
  True uncertain outcomes are not replayed. Diagnostics check x86 memory headroom
  before injection (128 MiB total free, 8 MiB largest region; not a guarantee).

Live evidence and limits:

- The saved first fresh match is a **LOSS**, B Team 200-0:
  `run_20260907_135700_362616/completion_normalized.json`.
- Continuous runs `_1` and `_2` adopted 143 and 154 recruits but stopped on the
  timestamp-ordering and old sensor-limit defects. Their fixes have later live
  execution, not a completed-match stability result.
- **Audit correction:** `_3` was incorrectly described as stalled before baseline.
  Windows directory metadata reported zero bytes while its open evidence file
  actually held 52,515,408 bytes: 72 observations and 575 native submissions.
  The controller was interrupted unnecessarily. Its summary is corrected; the
  last in-flight outcome is unknown. Inspect active logs using seek-to-end on an
  open file handle, not directory length metadata. No crash is inferred here.
- `_4` was deliberately interrupted to load scoring/preflight fixes. `_5` briefly
  held three flags, later lost one, and stopped on a known-unexecuted callback
  timeout formerly classified as uncertain. Neither is a completed match.
- `_6` stopped cleanly through STOP: 271 observations, 218.797 simulation seconds,
  19 normal purchases, 205 adopted recruits, 180 deaths, 2158 moves and 3 attacks.
  All twelve checked hook sites were restored. At this larger army size, maximum
  native observation time was 348 ms and runtime step time 1613 ms: stutter is
  **not established as fixed**. Background workload and differing combat scenes
  prevent treating these runs as controlled performance comparisons.
- `_7` is the subsequent running validation, with living-strength allocation and
  timeout classification. It does not include the later owned-sensor omission;
  restart is required to validate that change. Read its eventual summary for its
  outcome. No resource changes were made between controller restarts.
- The earlier PID 41072 crash is separate and confirmed by the native 13:23:14
  crash log, predating controller termination. The faulting IP was inside Frida;
  free x86 address space was about 42 MiB, largest region about 3.4 MiB. This
  supports memory-pressure investigation, not a proven sole cause. A fresh game
  was launched with the existing -no_reload_caching option. Evidence includes
  `heroic_crash_20260907_132314.log` and `heroic_crash_20260907/threads.dmp`.

Earlier performance checkpoints: a 340-observation encoding replay produced
identical adapter snapshots with 72.16% fewer bytes before the later owned-contact
omission (`perception_encoding_replay_20260907.json`). Continuing offline policy
medians at 128/256/512/1024 units with 256 contacts changed from
12.86/23.93/51.44/108.16 ms to 10.25/16.50/31.75/69.28 ms. These are transport and
Python results, not FPS or current native throughput. Forward/reverse external
simulation timing diagnostics are available through the performance scenario;
matched polling cadence and controlled workload still need attention.

Later checkpoint: `_7` stopped cleanly through STOP after 313 observations and
255.956 simulation seconds, with no reported error. Maximum native observation
time remained 319 ms and runtime step 1458.649 ms. Its exact bridge source was
reconstructed and hash-matched for `owned_sensor_profile_20260907_1`; that
comparison uses fixed 0.5-second snapshot slots and records missed slots, then
resumes control as `_8`. Its eventual evidence determines the measured result.

CQC mapping progressed read-only: shipped action definitions and native identities
for fragmentation, anti-tank and smoke grenades are saved in
`cqc_shipped_actions_20260907.json` and `cqc_native_action_identity_20260907.json`.
Action IDs 23/24/25, factories and shared execution methods are mapped in
`validation/tactical_mapping_20260907/cqc_throw_actions.txt` and
`cqc_throw_execution.txt`. No grenade action is enabled or validated by this mapping.

### Later results: mixed supply, vehicle contacts and measured overhead

The second requested match ended naturally in `continuous_heroic_battle_20260907_8`:
**LOSS, B 200 - A 47**, saved by the ordinary finish/results workflow in
`run_20260907_151209_870560/completion_normalized.json`. Run `_8` recorded 747
snapshots, 589.126 simulation seconds, 57 purchases and 616 adopted recruits.
All five flags were B at completion. Run `_9` correctly refused the ended match.
The third match started through native guards in `run_20260907_151847_228121`.
`mixed_heroic_battle_20260907_2` is still running at this checkpoint; a two-flag
observation is progress, not a match result. No economy or combat values were patched.

Supply now cycles verified native rifle, SMG and bazooker templates (854, 853,
881), each through its normal availability and purchase functions. Query and
purchase use the same validated template. Fixtures reject mismatched template
identity/name and unsupported keys. Vehicles are recognized through verified
vehicle-brain identity/owner binding, and only observed sensor positions enter
policy. Vehicle threat strength four is a policy heuristic. Manual infantry
attack orders exclude vehicles until weapon suitability is established; native
auto-targeting remains available. This does not establish anti-armor effectiveness.

Routine sensor decoding now bulk-reads each selected record and caches native
death results only within the locked observation. The fixed-cadence profile
`owned_sensor_profile_20260907_1` predates these bulk reads and vehicle additions:
previous native observation medians were 111/112.5 ms, versus 49.5/46.5 ms after
omitting owned sensor records. All instrumented phases made 16 polls at 2 Hz,
with zero missed slots. External simulation-progress gap p95 fell from about
232 ms to 125 ms. Uninstrumented phases measured 77/108 ms. Combat/background
load varied; these are not FPS measurements or proof that stutter is eliminated.

`grenade_query` validates the fragmentation, smoke and anti-tank native action
identities and shares the existing inventory/held-item counter. It submits no
orders. Live `grenade_inventory_live_20260907_1` observed two fragmentation
grenades and no smoke or AT grenades on one soldier; availability agreed and all
12 hook sites restored. Throws, trajectories, effects and policy remain disabled.

Cover mapping now establishes that default requests score at 0x8a75a0 and sort
by descending candidate +0x7c through 0x8a9670/0x8a8a60. The insertion-sort path
0x8a8cc0 confirms comparator direction. Diagnostic output names weightedScore
and checks the returned prefix is descending; it still leaves protection, firing
access and reachability unknown. Decompilations: cover_native_rank.txt and
cover_rank_order.txt. The subsequent focused suite passed 25 tests in 1.905 s
(`cover_rank_tests_20260907.log`); this diagnostic change is not loaded in the
already-running mixed battle and has no live query evidence yet.

### Travel posture and further policy work

`mixed_heroic_battle_20260907_2` stopped cleanly after 1483 observations, 64
normal purchases and 494 adopted recruits. A held four of five flags; no final
result had occurred. Maximum native observation was 120 ms and runtime step
883.379 ms. All 12 hook sites restored. The diagnostic purchase ceiling is now
256 per controller, retaining five-second availability checks, one pending
purchase, recruit observation and registry headroom. This is a controller budget,
not a change to native MP or purchase limits.

The unused rally-anchor search now runs only when there is no objective or
remembered threat. `unused_anchor_replay_20260907.json` compares prior/current
code at 128/256/512/1024 soldiers in objective/contact/support scenes. Intents and
squad states matched in every case. The 1024-soldier objective median was
74.40 versus 61.56 ms; smaller/support-scene timing varied. This is offline CPU
evidence under a changing background workload, not a native FPS comparison.

Longer travel can request standing from crouched/prone if there is no remembered
threat within 90 policy units and no recent casualty in the current grid cell.
These distances are policy heuristics, not guaranteed safe weapon ranges. Actual
stance completion precedes movement. Reloading, aiming and firing remain
protected, and missing stance capability falls back to ordinary movement.
Live run `_3` verified posture completion for 63 distinct soldiers and subsequent
move arrivals for 56 at its partial checkpoint. The checkpoint also exposed
repeated stand requests when native behavior returned some soldiers to prone.
A per-soldier 30-second cooldown now prevents immediate posture contention;
regression tests simulate native reversion. Run `_3` stopped cleanly (454 samples,
290 stance orders, 2426 moves, 18 attacks); all 12 hooks restored. Run `_4` is
validating the cooldown in the same uninterrupted native match.

`cover_rank_live_20260907_1` returned a source-identified candidate at native
score 15.25509 with two raw input records, released its vector and restored all
12 hook sites. One candidate cannot exercise a multi-candidate sorting comparison.
Protection, outgoing firing access and reachability remain unknown. Further
read-only geometry decompilation confirms segment-intersection arithmetic but
does not establish ballistic protection or a complete cover acceptance gate.

### User-reported spawn backlog and anti-tank gaps

The third requested match is a verified **LOSS, B 200 - A 157**. Native result:
`run_20260907_162104_355202/completion_normalized.json`; normal save/cleanup:
`run_20260907_162134_060916`. It ended during `orphan_leader_battle_20260907_1`
(494 samples, 2953 moves, 655 stance orders, 72 attacks, 12 purchases). The
following bazooka run `_1` correctly refused the already completed match and
restored its hooks. No qualifying win has occurred.

The user's screenshots led to a direct scope audit: 202 eligible leaders, 161
with exactly one native squad member, were stranded by blanket leader exclusion.
The bridge now exposes individualOrder from the full native membership vector,
not its owned-only projection. A leader whose full vector is exactly itself may
receive an individual order; intact leaders remain excluded pending a follow
path that does not unexpectedly command the entire squad. Native 0xaa3d50 is
why this distinction matters: a singleton actor list containing a leader expands
to squad membership. Command preflight rechecks scope. Fixtures include empty
membership, a foreign member, and scope expansion after observation.

BotSupply also adopts untouched eligible individual-scope survivors already in
the scene. The user explicitly requested utilizing the stranded force. Native
Move-at-will plus observed enrollment remain required; manual revisions and
direct control prevent adoption. Live checkpoint: 181 leaders enrolled, 116
physically displaced over 20 native units and 99 completed movement legs.
`orphan_leader_movement_checkpoint_20260907.json` is a partial running checkpoint,
not a finished coverage or combat result. Intact leaders are still outstanding.

Owned weapon definitions expose their bounded model string. External read-only
sample `owned_weapon_definition_names_20260907.json` found Garand, Thompson,
BAR, bazooka and garand_grenade models without sample errors. In the later locked
bridge observations the model is included with ammunition. Policy prefers SMG
movers and an MG coverer within a verified covering wave, preserving alternation;
unknown models keep the balanced fallback. Native covering access is still not
supplied, so this does not establish live alternating fire-and-movement.

Loaded bazookas can now target visible living enemy vehicles through the existing
native target serialization. Empty/loading/changed weapons are rejected again
at native preflight and submission. Rifles remain excluded from vehicle orders;
bazooka rounds are reserved from ordinary infantry targets. Ready launchers
prefer a shared visible vehicle with a three-second focus reevaluation interval.
This is target coordination, not synchronized impact timing or penetration proof.
AT rifles, rifle-grenade ammunition selection, timed AT grenades and armor weak
points remain unimplemented. No vehicle is controlled and no combat stats changed.

Majority objective ownership now raises retention priority instead of continually
rewarding further expansion. This preserves existing goal hysteresis and resumes
capture priority after the majority is lost. It is a tested policy heuristic,
not an established improvement in matched battles.

The fourth match started normally in `run_20260907_162227_032657`. Initial battle
`bazooka_leader_battle_20260907_2` attached at simulation tick 112 while paused
and refused admission. A subsequent external read confirmed the game resumed
normally; no pause memory or pause command was changed. Battle admission now
allows a paused start and waits through the ordinary no-action paused runtime.
A resume fixture verifies no order on the paused sample (22 scenario tests pass,
`paused_start_resume_verified_20260907.log`). Current live controller is
`bazooka_leader_battle_20260907_3`; its eventual summary determines AT evidence
and outcome. The delayed successful attachment gave the bots an early start.

The earlier mixed4 completion watcher exited without issuing finish commands
when that controller was deliberately stopped. No watcher is currently scheduled
for the fourth match. Cover integration and intact-leader following are the next
user priorities; do not describe either as solved by the survivor or posture fixes.

The fourth match was deliberately aborted after the startup admission defect
left control absent during its opening. `bazooka_leader_battle_20260907_3` stopped
cleanly after 486 samples with all hooks restored. At the prior checkpoint no
vehicle attack had serialized. `run_20260907_162947_436373` preserves the ordinary
controlled abort and raw statistics; this is not a natural finish or victory.
The normal save/start sequence is launching a fifth attempt with paused-start
handling already loaded, output `bazooka_leader_battle_20260907_4`.

## September 7 resumed implementation: headless scale and automated handoff

### Successful native dispatch at 144 observed infantry

The closed 200-point match `run_20260907_124152_335885` admitted twelve verified
rifle purchases, producing 144 eligible infantry. `scale_144_setup_20260907`
prepared their native modes. `scale_144_current_wave_20260907` then controlled all
132 eligible nonleaders with the current-wave scheduler and allied-support changes.
Over its 120-second wall-clock window, it observed 105.842 simulation seconds and
175 snapshots, serialized 1,064 moves and recorded 971 completed movement legs.
Every controlled soldier recorded an arrival. There were zero rejections, errors,
retirements or recorded casualties. All 12 hooks restored, with all 4,339 records
retained (412,535,876 bytes). The summary is `scale_144_report_20260907.json` and
its Markdown companion in the D: archive.

This establishes local movement/dispatch integration at 132 controlled soldiers,
including the correction for the prior waiting-wave deadline failure. It is not
a full scale or combat pass: there were no enemy contacts, native observation
peaked at 56 ms, and runtime steps at 285.19 ms. Simulation advanced slower than
wall time in this run. Performance at larger sizes and under contact still needs
measurement; no combat benefit or independent-client replication is inferred.

### Verified observed allied support

Support previously counted only owned infantry, ignoring allied bots even when
their fresh positions and relationship were observed. Contacts now carry a
separate alliance flag, admitted only when the native owner relationship is
friendly, the sensor reports non-enemy, and a known team matches the local team.
Perceived ownership alone is insufficient. The policy adds fresh visible living
allies to its existing bounded support cells; it excludes all identities already
represented by unit rows, stale/reused contacts and other match generations.
This adds support estimates, not authority over allied troops or unseen positions.
Counts remain policy weights, not native combat-force estimates.

All 304 tests pass, including support expiry, no double counting, alliance
admission and a supported squad avoiding an otherwise triggered withdrawal.
Replay of 116 observations from the prior 96-infantry trial found 955 non-owned
allied contact samples, peaking at 16 allies. Evidence and source hashes are in
`allied_support_replay_20260907.json` in the D: archive. No native orders were
issued by the replay; live behavioral benefit remains unverified. The long-match
army preparation continues independently through admitted native purchases.

### Longer native test profile

The native lobby advertises a 75..200 victory-point range. `configure-ai` and
`start-ai` now accept the explicit option `--ai-victory-points 200`, preserving
75 as the default and 10000 manpower. Configuration checks native range and
observes the exact result; start requires the explicitly requested score to match
the approved lobby and records it in the durable match metadata. Existing host,
roster, opposing-bot, readiness and approval-token checks remain in place. Native
configuration passed in `run_20260907_124133_178253`. All 301 tests pass, including
default/long profiles and rejection of stale approval, wrong score/resources,
remote humans, foreign host, unready player and missing opposing team.

### Native army submission backlog failure and correction

Normal admitted purchases in closed bot match `run_20260907_122536_720360` produced
96 eligible owned infantry. `scale_96_bot_setup_20260907` prepared their native
modes. `scale_96_bot_combat_20260907` addressed all 88 nonleaders but serialized
only 15 moves: the extra waiting dispatch wave exceeded its 0.75-second submission
deadline under native load, producing repeated admission rejections. The run
stopped at its 256 MiB evidence limit after 70.539 simulation seconds and 116
snapshots. Fourteen units had observed arrivals. Native observation peaked at
29 ms and runtime steps at 216.48 ms. All 12 hooks restored; retained evidence
contains all 2,916 written records. This is a failed scale trial, not a pass.

Runtime now generates at most the current dispatch capacity, subtracting any
existing pending orders, instead of retaining an extra wave. A 256-unit fixture
at 0.6-second observation intervals verifies fair service with no residual queue;
explicit pre-existing-queue fixtures preserve expiry and weapon-state invalidation
coverage. All 300 tests pass. The bot diagnostic has a finite, lossless 2 GiB
budget for its 120-second sensor-heavy trial. No production log limit changed.

The immediate retest `scale_96_current_wave_20260907` was refused because native
`playing` was already false at tick 653931; all 96 infantry remained eligible.
The scheduling correction still needs a new live trial. Evidence summary:
`scale_96_failure_report_20260907.json` and its readable companion in the D: archive.

### Army outcome reporting

The existing `tactical_results.py` summarizer now retains army counts, arrivals,
contacts, casualties, withdrawal metrics and peak observation/runtime costs. It
separates explicit failed/cancelled/uncertain terminal records from retirement at
or after a deadline, before a deadline, or without sufficient timing. Retirement
does not prove native cancellation. Elapsed army simulation time is preserved,
and the readable report includes the key counts. The regression suite passes 300
tests, including mixed retirement/terminal records without promoting an observed
trial to a release pass.

`movement_timeout_report_20260907.json` and its Markdown companion in the D:
archive summarize the two timeout trials: 25 deadline retirements before the
correction and zero afterward, with ten and 36 completion records respectively.
These are different successive scenes, not matched baseline/treatment trials.

### Slow native movement timeout correction

Analysis of `budget_headroom_combat_20260907` found that longer legs expired while
soldiers were still making steady progress. The first 580-native-unit move covered
483.5 units before its 24.33-second deadline, leaving 96.8 units. Shorter 290-unit
legs completed in roughly 13 seconds. The policy's assumed speed of 1.5 policy
units/second was faster than this scene's observed speed of about one. All 44 legs
are summarized in `slow_movement_timeout_analysis_20260907.json` in the D: archive.

Move/cover timeouts now allow travel at 0.75 policy units/second plus five seconds
of startup allowance, bounded to 8..60 seconds. This is a conservative timeout,
not an inferred speed field or guaranteed arrival. Two regression tests exercise
a slow 29-second movement without premature replacement and a stalled order that
still expires as uncertain. All 299 tests pass. Physical arrival remains required
for completion; urgent danger and player takeover retain their invalidation paths.

The subsequent `slow_movement_combat_20260907` native retest ran 119.86 simulation
seconds, with 539 snapshots, 57 moves, three attacks and 206 enemy-contact samples.
All 11 soldiers recorded arrivals (36 completed movement legs); no inflight order
was retired at or beyond its deadline. There were no recorded casualties. All 12
hooks restored and all 773 records were retained. Native observation peaked at
7 ms and a runtime step at 152.53 ms, so this is not a native scale acceptance
result. The scene continued from the previous attachment with changed positions
and objectives; it supports the timeout correction, not a matched performance
comparison or superiority claim.

### Explicit mode-command observations

Read-only mapping of the native movement-button callback `0xa89a30` confirms
command type 5, mode byte at `+0x26`, and emission through `0xaaa1a0`. The fire
button `0xa89790` emits type 4; it does not reclaim suspended infantry. The
movement toggle's mixed-selection default is Hold, so a mixed squad alone is
not a validated way to emit an unchanged Move-at-will value. Mapping is saved in
`validation/tactical_mapping_20260907/mode_control_callbacks_verified.txt`,
`mode_toggle_selection_verified.txt` and `fire_mode_handler_verified.txt`.

Player-command events now preserve native flags, caller and previously suspended
addressed IDs. These lists retain the existing bounded command scope and add no
per-tick polling. Two native-memory fixtures verify suspension followed by a
same-value movement emission, and that a fire-mode emission leaves suspension
and the unit revision intact. All 297 tests pass, including 158 production-bridge
and 178 combined diagnostic fixture cases. This does not prove native acceptance
of same-value UI input: the fixtures mock emission, and the live handoff gate
remains outstanding. No experimental player-command emitter was re-enabled.

### Observed withdrawal, recovery and bounded failed-route work

`readiness_army_combat_20260907` exercised enabled readiness on owned infantry for
119.9 simulation seconds: 525 snapshots, 119 moves, nine attacks, 645 enemy-contact
samples and no recorded casualties in that window. All 11 controlled soldiers
had completed movement legs. All hooks restored. The following trial now records
actual pressure, squad-state samples, readiness samples, accepted withdrawal
orders and observed withdrawal arrivals.

`pressure_army_combat_20260907` observed peak policy pressure 2.524, exceeding the
1.6 withdrawal trigger. It recorded 54 withdrawal-state samples and 25 regroup
samples. Soldier 136 received two retreat moves after complete native path
preflights (ten and nine path points, outputs freed). The first arrived in 10.38
simulation seconds. A third attempt was refused before movement because its
snapshot-derived endpoint exceeded the query's distance bound at execution.
The trial stopped after 68.42 seconds when no enrolled survivors remained, with
three native deaths recorded during this attachment. It is withdrawal/recovery
integration evidence, not a survival benefit or superiority pass. All 12 hooks
restored; all 379 evidence records retained.

The policy now leaves headroom between observation and execution: movement legs
are at most 29 policy units (580 native units) against the native 600-unit bound.
Each native stage still revalidates. After a failed retreat route, it considers
up to eight distinct ranked friendly/cover anchors; failed-leg cooldowns remain
in effect, allowing another candidate instead of waiting repeatedly on the best
blocked one. Fixtures verify alternative selection and no replay of failed legs.

Expensive per-unit decisions are now capped at 64 per step independently of the
32-order cap. Rotating service continues, and urgent action invalidation still
visits every unit even after the decision budget is consumed. A 100-unit fixture
verifies that invariant. An offline coincident-unit/no-fallback stress comparison
at 128/256/512/1024 units measured maximum times of 1.48/3.43/7.63/21.44 ms with
the budget, versus 2.92/8.79/32.50/124.00 ms allowing 1024 decisions. These are CPU
measurements, not native path throughput. Evidence and source hashes are in
`decision_budget_scale_20260907.json` in the D: archive root. All 297 tests pass.
The recorded withdrawal used the preceding code. A subsequent combined attachment,
`budget_headroom_combat_20260907`, ran the refinements for 119.96 simulation seconds:
542 snapshots, 44 moves, five soldiers with observed movement-leg arrivals, all
11 nonleaders still enrolled and all 12 owned infantry eligible. Native observation
peaked at 5 ms and runtime steps at 54.49 ms. All 12 hooks restored and all 710
records were retained. This window had zero enemy contacts or withdrawals, so it
validates limited movement integration, not alternate retreat selection under
pressure, native scale or combat superiority.

### Combined native firing readiness validation

The existing read-only `0x84d0a0` mirror is now shared by weapon queries and the
passive firing observer. Exact component types and back-pointers remain required.
`fireState` exposes the native predicate, preparation state and a candidate that
requires both native firing eligibility and preparation state 3/4. Runtime can
consume it only through the `weaponReadiness` capability. Reloading and attributed
recent shots retain priority; unknown components remain unknown. The production
capability was disabled during comparator collection and was subsequently enabled
for conservative positive readiness after the evidence below. Other controller
admission gates remain unchanged.

`fire_predicate_verified.txt` and `fire_predicate_dependencies_verified.txt`
regenerate the actual predicate and its ammo/recovery/context dependencies. The
passive observer compares the mirror against native invocations, caps records at
1024, bounds identities at 128 and checks the extra hook on teardown.
`fire_predicate_contact_20260907` captured 36 comparisons: ten allowed and 26
refused, with zero mismatches. All ten recorded shot advances satisfied the
combined candidate and consumed one round. Fifteen refusals had preparation
state 3/4 despite inactive loading, demonstrating why the remaining native
predicate conditions matter. All 18 hook sites restored; 276 records retained.
The earlier fresh-match window had no predicate samples; it does not validate
either branch.

`fire_predicate_loading_20260907` completed another 275 snapshots with 462 native
comparisons: 219 allowed and 243 refused, including 17 refusals during native
loading. There were zero mirror mismatches. All 219 recorded firing cycles
consumed one round and advanced the shot counter once. Of these, 206 satisfied
the combined candidate; 13 fired in preparation state 5 with the native predicate
true. Therefore state 3/4 is conservative positive evidence, not a necessary
condition for firing. Other states remain unknown, never classified as unable
to fire. All 18 hooks restored; all 276 evidence records were retained.

`weaponReadiness` is now enabled for the exact validated component types. Both
runtime snapshots and explicit weapon queries use the same read-only helper.
The adapter emits `ready` only for a consistent positive candidate; explicit
queries return true or unknown for `readyToFire`. Neither claims hit accuracy
or that a shot will necessarily follow. `readiness_owned_snapshot_20260907`
verified the real owned-unit observation path after purchasing and opting in a
new squad: 11 enrolled nonleaders supplied the field, all 12 idle infantry stayed
unknown in the adapter, and all hook sites restored. This was a no-order weapon
query, not a combat-readiness performance trial. Actual shot events still guard
firing in state 5. Aim-settling protection and alternating covering groups remain
incomplete.

All 295 tests pass, including 156 production native fixture cases and 176 combined
diagnostic cases. Fixtures cover preparation states 3/4/5, capability gating,
unsupported components, inconsistent data, and reload/recent-shot precedence.

### Native firing-cycle and preparation correlation

`friendly_aim_watch` now passively brackets the supported shooter's `0x84d8a0`
routine. It validates exact code bytes, component types/back-pointers and unchanged
unit identity; records before/after ammunition, cumulative shots, burst remainder,
placement state, wait byte and deadline; and caps firing-cycle samples at 512.
It issues no orders. Teardown also checks the new hook site. The final observer
rejects replaced weapon/placement components, and native fixtures cover shots,
no-shot calls, component replacement and unit reuse.

`shooter_cycle_live_20260907` collected 275 snapshots and 255 firing cycles. Every
cycle advanced the shot counter by one and consumed one round, with native loading
false before the call. Preparation state was 3 in 248 cycles and 4 in seven.
Separately, 312 preparation results included 14 state-3 and three state-4 samples
while loading was true. Thus preparation success alone cannot establish readiness.
No wait-byte samples were observed. All 17 hook sites restored and 276 evidence
records were retained without loss. This is actual firing correlation, not hit,
accuracy or readiness sufficiency proof. The next step is to combine the verified
ammo/fire predicate with preparation state for supported rifle components and
validate positive and negative cases before promoting runtime readiness.

The full suite passed 294 tests; after adding component-replacement rejection,
the 21 focused bridge/scenario tests passed, including 171 combined native fixture
cases. Production readiness/aim capabilities remain unchanged.

### Cover assessment spatial context and regenerated mapping

The passive cover observer now records candidate XY, observer XYZ and the native
target record's stored XYZ. It reads the sensor record, not an unseen target's
current transform. These values remain diagnostic spatial context; they do not
promote protection or firing-access capabilities. Invalid coordinates stop the
observer. Native harness cases cover a target record, absent target, malformed
coordinates, foreign ownership, reused actors and oversized candidate vectors.
All 294 suite tests pass, including 167 combined native diagnostic fixture cases.

`cover_spatial_live_20260907` reached the ten-input-sample threshold in 11
snapshots. It captured 19 assessments, 11 weighted nonempty requests, ten weighted
requests with inputs and ten with a target. Sixteen assessments had stored target
positions. All 13 hooks restored and all 12 evidence records were retained. This
validates spatial-context collection during actual friendly-bot combat; it does
not establish protection or outgoing-fire predicates. The earlier passive attempt
`resume_cover_context_20260907` ended on match completion, with zero qualifying
input samples and all hooks restored. Its interrupted result is preserved.

Regenerated `cover_detector_verified.txt`, `cover_components_verified.txt` and
`cover_request_defaults_verified.txt` under `validation/tactical_mapping_20260907`
contain the actual requested functions. The older `cover_detector_semantics.txt`
contains helper functions, so its filename alone is insufficient evidence for
the parent routine's semantics. The fresh decompilation identifies candidate
`+0x58` as normalized path-cost preference; `+0x64` derives from incoming detector
flags; `+0x5c` uses target-related segment intersection (`0x8aa0d0`); and `+0x68`
is a weapon-range preference. These are component interpretations, not validated
outgoing firing access or measured cover protection. `firing_access_lead_verified`
preserves the native weapon-placement lead; no new weapon function was invoked.

### Per-soldier attack observation scope

Fresh isolated normal-bot validation: `observer_fresh_combat_20260907` advanced
the newly purchased squad for 119.82 simulation seconds, with 131 accepted moves
and completed legs for all 11 controlled soldiers. The following
`observer_fresh_contact_20260907` ran 119.98 simulation seconds: 490 snapshots,
73 accepted moves, 18 accepted attacks, 1076 enemy-contact samples, 475 firing-
guard samples and four native deaths. Attack cancellations were four, compared
with 249 in the historical run. This supports the observer-scope correction,
but different battle conditions prevent a combat-superiority comparison. Maximum
native observation time was 8 ms; runtime including RPC maximum was 142.85 ms.
All 12 hooks restored, and 887 records were retained without loss. No withdrawal
was selected. The previous match was reconciled and saved before the restart;
lobby joinability was closed again. All trials remained headless.

The 249 cancelled attacks in `resume_army_path_contact_20260907` were not evidence
of weapon range failure: native attack preflight checks the requesting soldier's
sensor, while policy previously selected from the shared contact pool. The
adapter now retains a bounded set of owned observers for each contact, and policy
selects attacks from contacts actually observed by that soldier. Shared sightings
remain available for threat memory and movement. Fresh native preflight still
rechecks identity and visibility before serialization.

An offline replay of the saved native observations found all 249 cancelled
attempts lacked a requesting-soldier observation. Seven of eight accepted attacks
had that observation; one became available only at the newer preflight, so the
new policy would wait for its next sensor update. This is a diagnostic replay,
not a matched combat performance comparison. Evidence is
`observer_targeting_replay_20260907.json` in the D: archive root. Fixtures verify
shared-contact movement, observer-only attacks, lost observer reports and reused
observer incarnations without retaining stale attack visibility.

`resume_observer_targeting_20260907` completed 119.84 simulation seconds with
504 snapshots, 30 accepted moves and completed movement legs for four soldiers.
No enemy contacts occurred in this late-match window; it does not validate live
combat targeting. All 12 hooks restored, and 625 records were retained without
loss. The adapter also cancels a queued attack before RPC if its observer has
since lost the sighting, even when another soldier still sees the target. The
final full suite passed 294 tests. Next live comparison needs a fresh contact
scene; combat superiority and the remaining plan acceptance gates are incomplete.

### Native local path preflight and withdrawal

Passive tracing identified the ordinary movement task as `Task::ePoint` at
`0xdf8728`, rather than the exact-point alternate below. The native descriptor
initializer is `0x8c44d0`, query wrapper `0x8c3c40`, and vector release `0x8b2740`.
Path entries contain XY and cumulative cost, not XYZ; the reverse vector starts
at the goal. Release receives allocation capacity, not the number of used points.
The diagnostic query uses the mapped native task layout on the game thread and
releases output in a finally block. Production `pathQuery` remains disabled.

`resume_path_squad_native_20260907` moved four opted-in soldiers to arrival in
10.02 simulation seconds. Traces captured their ordinary path queries and matching
native vector releases. All 14 hook sites restored. A 17-direction/query scan in
`resume_path_scan_20260907` found 12 complete requested routes and five endpoints
clamped at the map boundary. All 17 native calls reported success and no partial
flag: these flags alone do not prove the requested destination is reachable.
The adapter therefore also checks start and end coordinates, identity, generation,
simulation deadline and release confirmation before submitting a withdrawal.

`resume_path_follow_boundary_20260907` refused the boundary route with zero orders.
`resume_path_follow_valid_20260907` followed a verified route with one order and
observed arrival in 9.94 simulation seconds. These are local route checks, not
proof of safe exposure along the route or multiplayer replication.

Policy may consider friendly fallback positions of unknown reachability only
with the path-preflight capability. Known unreachable positions remain excluded.
Withdrawal uses legs of at most 30 policy units (600 native units), checks that
the intermediate endpoint has less observed danger, and preserves route-failure
backoff. Diagnostic bot combat enables this capability only for the bounded trial;
the production acceptance gates remain unchanged. Offline fixtures exercise
native allocation cleanup, malformed/partial/unreachable paths, stale authority
and time, uncertain replies and prevention of a move after an unusable preflight.

The full suite passed 292 tests after the short-leg correction, and JavaScript
syntax validation passed. A separate offline withdrawal measurement with 256
urgent contacts processed 128/256/512/1024 units with maximum step times of
17.13/31.49/62.34/134.97 ms, issuing at most 32 intents. This does not measure
native path-query throughput; data is `withdrawal_scale_20260907.json` in the D:
archive root.

The earlier match completed naturally and was reconciled/saved before restarting
an isolated normal-bot match. `resume_army_path_combat_20260907` reached the 64 MiB
evidence cap after 81.96 simulation seconds, 89 accepted moves and no enemy
contacts. It preserved 684 records and restored all hooks. Full per-observer
friendly sensor records dominated the log. The bounded bot-combat diagnostic now
allows 256 MiB, retaining complete observations without rotation or dropped data.

`resume_army_path_contact_20260907` then completed 119.96 simulation seconds:
465 snapshots, 76 accepted moves, eight accepted attacks, 604 enemy-contact
samples, 102 firing-guard samples and two native deaths. All 11 controlled soldiers
had completed movement legs (68 completions total). Native observation maximum
was 9 ms; runtime including RPC maximum was 162.24 ms. All 12 hook sites restored;
1553 records retained without loss. No withdrawal was selected, so integrated
combat withdrawal/recovery remains unverified. There were 249 cancelled attack
attempts; 244 attack queries returned no usable native target. Follow up the gap
between a visible contact and a usable firing target before claiming effective
engagement or superiority. Production `run` remains disabled; no manual test is
currently requested.

### Isolated normal-bot army combat integration

The scenario runner now has `bot_army_setup` and `bot_army_combat`. A diagnostic
extension reads the existing native session service/card on the game thread before
every observation and action, requiring local host authority, one local human and
only bots. It freezes the card/start-epoch/member signature and refuses changes.
Setup changes only eligible owned nonleader movement modes; a fresh attachment
adopts them. The 120-second combat trial uses the real adapter, policy and runtime
through diagnostic serialization, with scoped move/stance/attack/contact/death and
objective capabilities. It handles confirmed casualties and terminal matches.
Production admission gates remain unchanged.

`resume_isolated_army_contacts_20260907` completed 119.86 simulation seconds:
525 snapshots, 74 serialized move orders, 33 serialized attack orders, 706 visible
enemy-contact samples and 379 firing-guard unit samples. All 11 controlled soldiers
had observed completed move legs; five native deaths occurred. Maximum native
observation time was 6 ms, and maximum runtime step including RPC was 147.52 ms.
All 12 hook sites restored; 1195 evidence records retained with no rotation/loss.
These are integration measurements, not a pass for combat superiority. Native
fallback-route validation, cover/fortification integration and matched comparisons
remain incomplete. Attack serialization is not a confirmed kill or hit.

The first attempt (`resume_isolated_army_combat_20260907`) stopped on differing
sensor positions sharing one simulation timestamp. Saved records show sub-world-
unit motion between observers. The adapter now quarantines positional ambiguity
for that identity/timestamp until a newer observation, including across snapshots;
it neither averages positions nor treats them as new motion. Contradictory native
enemy/death classification within a snapshot still fails closed. Focused fixtures
cover quarantine, newer observation recovery and relationship contradictions.

The prior bot match was naturally completed, reconciled and saved in
`run_20260907_101828_203296` / `run_20260907_101954_441394`. A public-lobby human join
prevented a restart; no test started with that human present. After the human left,
Steam accepted `ai-joinability --joinability closed` for the local bot lobby in
`run_20260907_102655_152849`. The setting can be restored with `--joinability open`
in the bot-only lobby. The native proxy's slot 34 was independently identified as
SetLobbyJoinable, matching Valve's SteamMatchMaking009 header. The initial boolean
marshalling failure is preserved with an isolated NativeCallback proof of zero
native invocation and its specific journal reconciliation in
`validation/tactical_mapping_20260907/joinability_marshalling_reconciliation.json`.
No uncertain engine action was replayed. See [the isolation command](REFERENCE.md#ai-test-lobby-isolation).

Earlier complete suite: 289 passing tests, including native roster guard fixtures,
army death/terminal handling, joinability authority/record-only guards and numeric
boolean marshalling. Evidence remains under the D: archive named below.

Initial route lead (superseded by the validated ordinary-point queries above): Pather's
`Task::ePointExact` vtable is `0xdf9858`. The normal wrapper `0x8c3c40` takes a
16-byte actor path descriptor (`0x8c44d0` fills it), a 36-byte output and origin
position, and returns output byte `+0x20`. Its `+0x14` virtual method is
`0x8c3d20`, which chooses network or grid search. A native caller at `0x8d2e70`
constructs the task with flag byte `+4=1`, float `+8=100000` and target XY at
`+0xc/+0x10`. Output contains an allocated point vector; allocator/destructor
ownership and actual return semantics need passive tracing before a diagnostic
call. Mapping is saved as `native_path_goals`, `native_path_goal_callers`,
`native_path_query_callers`, `native_path_request_owner`, and `native_path_inputs`
under `validation/tactical_mapping_20260907`. No path function had been called at
that checkpoint.

Latest native scale checkpoint: `resume_army_168_objectives_20260907` observed
168 owned infantry and controlled 153 eligible nonleaders. It addressed/moved 152,
observed completed move legs for 141, and recorded a newly captured f1 with native
capture-radius proximity over 43.24 simulation seconds (546 orders, 139 snapshots).
Native observation maximum was 12 ms. All 12 hook sites were restored on detach.
This is objective/throughput evidence without enemies, not combat superiority.
Evidence is under `validation/local_archive/new_runs/`.

The adapter now preserves one simulation second after an attributed owned-unit
projectile as `firing`; mapped reload state takes priority. This is conservative
movement protection, not proof of settled aim or readiness to fire. Offline checks
cover expiry, capability admission, stale incarnation, invalid timestamps and
reload priority. A controlled normal-bot match loaded in
`run_20260907_100511_686446` for further live validation.

`resume_combat_guard_20260907` completed a single-soldier f4 capture in that
normal-bot match (8 move orders, 84.62 simulation seconds, native capture-radius
proximity), without firing. The subsequent `resume_attack_guard_20260907` recorded
7 owned projectile events and 15 recent-shot guard samples, then native death of
unit 50 at simulation tick 220704. The scenario correctly stopped but is recorded
as failed, not a successful engagement. All hooks restored. A fresh attachment in
`resume_combat_dead_rejection_20260907` rejected that dead unit. No kill advantage,
matched-trial superiority or synchronization claim follows from these runs.

Queued ordinary movement/stance/cover/build is now cancelled if firing, aiming or
loading begins before dispatch; emergency withdrawal remains allowed. Native
query-consumed projectile events are carried to the next adapter snapshot, avoiding
event loss or comparison against an older snapshot's clock.

Perception scheduling now uses each opted-in nonleader's native sensor, not a
possibly distant leader. It performs 4..32 bounded sensor reads per snapshot,
shares one registry address index, and retains at most 128 reports/4096 records.
Reports still expire after two simulation seconds; large populations or dense
contacts can lose old reports instead of claiming stale visibility. Offline
80-observer sparse/dense fixtures verify fair service and the record bound.
This scheduling change still needs live profiling with contacts enabled; production
contact admission remains disabled pending semantic/replication acceptance.

Headless lobby setup now traverses the fixed-team `eMultiSelectListbox` row vector.
The bounded vector establishes row membership; a native refresh can leave parent
null, while any different non-null parent is refused. Ordinary UI child ownership
checks remain unchanged. Both normal bots were assigned and the match loaded with
the game minimized/out of focus. Six statistics tests cover capture and ownership;
that checkpoint passed 284 tests, and both production JS bridges passed syntax checks.

The clarified target is a headless controller for hundreds of owned infantry.
Native registry enumeration supplies identity, positions, ownership and squads;
selection and screen coordinates are not inputs to tactical policy. The adapter
converts native X/Y coordinates by 20 and retains native Z for command submission.
Enemy transforms are now skipped before positional/component reads during registry
enumeration; contact positions still require native perception observations.

The owned-unit observation/policy limit is now 1024 (4096 total registry actors).
The 128-member bound on an individual native squad remains separate. New policy
orders are capped at 32 per step with rotating squad/member priority, emergency
priority, and runtime backpressure allowing only one extra dispatch wave to wait.
All units still undergo ownership, manual-takeover and action invalidation checks.
Threat projection is computed once per update. A sparse support grid evaluates
nearby units exactly and conservatively aggregates distant cells using their
farthest-member radius; these are policy counts, not mapped engine force estimates.

Repeat the offline benchmark without a game or PID:

```powershell
py -B diagnostics/tactical_scenarios.py policy_scale --output <new-directory>
```

`validation/local_archive/new_runs/resume_policy_scale_20260907`
contains five cold and five continuing samples per population, each with 256
contacts. Median cold/continuing times were 11.36/12.41 ms at 128 units,
21.62/22.15 ms at 256, 46.56/49.57 ms at 512, and 103.71/105.72 ms at 1024.
These measure Python decisions, not native engine or multiplayer throughput.
Regression tests cover service of all 1024 identities, bounded runtime queues,
immediate reclamation under load, emergency priority, and conservative support.
Native-memory fixtures now exercise the 1024-unit boundary and foreign tail.

The automatic keyboard test failed again with a 200 ms release interval. Supplying
scan codes alone did not fix it. At 750 ms, repeated complete sequences passed on
leader 24 and nonleader 22: Hold, Move at will, direct-control entry/exit, and
explicit re-enrollment. `GameKeys` now uses typed Win32 arguments, physical client
pixels, a mouse-position sampling interval, and foreground checks. This UI helper
is diagnostic only. `manual_move --screen-point X Y` verifies a real addressed
player command and specifically rejects a stale unit revision; unrelated
rejections cannot count as a pass.

Live evidence under `validation/local_archive/new_runs`:

- `resume_input_gap_20260907`, `resume_input_confirm_20260907`, and
  `resume_input_nonleader_20260907`: automatic handoff passes.
- `resume_manual_move_20260907`: nonleader 22 suspended while its native movement
  mode remained Move at will; the old unit revision was rejected before execution.
  Unrelated enrollment/revisions were unchanged. This is not same-value re-enrollment.
- `resume_squad_scale_changes_20260907`: four members completed four concurrent
  native movement legs in 9.94 simulation seconds; minimum concurrent endpoint
  spacing was 89.286 world units. All 12 checked hook sites restored.
- Nine ordinary purchases expanded the no-enemy scene to 120 owned infantry;
  `resume_native_population_20260907` captured 22 snapshots without a bridge fault.

The latest complete suite at this checkpoint passed 276 tests, plus JS syntax
validation (`tactical_resume_full_suite_20260907.log` on the archive drive).
Later army-trial tooling is being validated separately. Production run remains
gated; combat advantage and independent-client synchronization are not established.

### Headless army integration and stable objective assignments

`army_setup` uses normal native mode commands for owned nonleaders in an active
local-player-only scene, then verifies actual modes. It does not claim enrollment
within that attachment. `army_objectives` adopts already opted-in infantry on a
fresh attachment and runs the existing adapter/policy/runtime for at most 120
seconds, with a 64 MiB evidence limit. Its explicitly recorded diagnostic
capabilities do not change production admission. All actions retain native
identity, ownership, revision, deadline and enrollment checks. No UI helper is used.

```powershell
py -B diagnostics/tactical_scenarios.py army_setup --pid <current-pid> --output <new-setup-directory>
py -B diagnostics/tactical_scenarios.py army_objectives --pid <current-pid> --output <new-trial-directory>
```

The first integrated run, `resume_army_objectives_20260907`, prepared 99 native
modes but could control only the previously enrolled soldiers in that attachment;
it is retained as observed/incomplete. Setup and adoption are now separate.
`resume_army_adopted_20260907` subsequently addressed all 109 eligible nonleaders
among 120 owned infantry. It observed movement completion for 103, plus native
team capture/proximity at f2 in 44.12 simulation seconds. It submitted 667 orders.

Trace review found 428 retired objective orders: rotating scheduling priority
changed sequential allocation penalties and caused goal churn. Allocation now
starts from the complete existing assignment map and excludes the scoring squad's
own assignment. A regression keeps balanced goals stable through 50 rotated steps.

`resume_army_stable_goals_20260907` then addressed, moved and observed arrival for
all 109 nonleaders. It captured f5 with controlled-unit proximity in 43.08
simulation seconds, submitted 462 orders, completed 368 movement legs and retired
one order. Native snapshot time peaked at 8 ms. The scenes have different starting
positions and objectives: these counts are not a matched combat/performance A/B.
Both successful trials restored all 12 checked hook sites. Already issued native
orders continue after controller stop; the pending Python queue is discarded.

These trials validate headless integration at 120 observed/109 controlled units.
They exclude leaders and do not enable contact, cover, construction or production
multiplayer gates. Higher native populations, combat advantage and synchronization
remain unverified. Regression tests also verify setup scope and actual-arrival
requirements without promoting production capabilities.

## Current code

- `headless/tactical_policy.py`: pure, bounded decisions for enrollment, objectives,
  withdrawal/regrouping, known cover, firing commitment, decaying contact memory,
  alternating movement and defensive construction candidates. Construction is
  conditional on verified tools, terrain, escape route and sufficient safe time.
- `headless/tactical_bridge.js`: standalone quant-thread registry observations,
  ownership/identity admission, native serialized stance/move/cover/mode/build trials,
  bounded requests/events and detachment. Native pointers stay inside the bridge.
- `headless/tactical_controller.py`: bounded observation CLI, evidence, intent
  queue and native snapshot/submission adapter. Production `run` refuses unmet
  gates. Move/stance/attack are wired behind those gates; other live policy capabilities
  remain unmapped or disabled.
- `diagnostics/tactical_scenarios.py`: bounded native trials, including one-unit
  objective pursuit. `diagnostics/tactical_results.py` preserves failures and
  separates source versions/scenarios in JSON and Markdown reports.

The existing lobby host and recorder are unchanged. No retreat ratios, global
human/weapon definitions, damage, spread or inventory values are patched.

## Live results in the existing no-enemy-AI scene

| Check | Evidence / result |
|---|---|
| Selection-independent enumeration | Native actor registry; owned infantry checked against local scene player 2 |
| Stance | Changed and restored through serialized command type 3; repeated on quant callback |
| Short move | Actual position changed and returned to the starting area |
| Objective pursuit | `f4` captured in 56.9 simulation seconds / 7 orders; `f2` later captured in 24.62 seconds / 2 orders |
| Cover query | No candidates on the initial desert ground; positive candidates after movement into town |
| Cover placement | Native cover state 1/2 and arrival observed; returned to starting position |
| Mode setter | Hold / Move at will / repeated same-value Move at will events observed; initial numeric mode restored |
| Clean detach | Checked native code bytes restored after trials; no properties patched |
| Script loss / explicit stop | Unloaded without stop, reattached, observed continued ticks; old attachment intent rejected; stopped bridge rejected requests |
| Keyboard takeover/pause | Unverified: Windows is locked; focus guard withheld input |
| Window-message input | No native command events or mode changes across 38 snapshots; unsupported in the current state |
| Raw sensor query | 22 friendly-bucket records on leader 24; zero on soldier 18; visibility/death remain unknown |
| Simulated player-call hook | Failed: same-script reentrant calls did not trigger the emission observer; this is not counted as a handoff pass |

The first objective run exposed an eight-second completion timeout that replaced
still-progressing movement. Movement/cover completion now gets a bounded travel
allowance, independently of the 0.75-second intent submission deadline. Another
trial exposed floating-point rejection at exactly 600 world units; the bound now
has a 0.001-unit tolerance. Failed runs are retained.

These objective runs have different starting positions and source versions. They
are not matched trials and do not establish improved combat performance. Native
movement may change stance. Early move trials restored position, not necessarily
the original stance. Active mod load precedence is not yet captured.

## Repeatable commands

Run from this project root, using the current game PID:

```powershell
py headless/tactical_controller.py observe --pid 18552 --duration 30
py diagnostics/tactical_scenarios.py stance --pid 18552
py diagnostics/tactical_scenarios.py move --pid 18552
py diagnostics/tactical_scenarios.py cover_query --pid 18552
py diagnostics/tactical_scenarios.py cover --pid 18552
py diagnostics/tactical_scenarios.py objective --pid 18552
py diagnostics/tactical_scenarios.py lifecycle --pid 18552
py diagnostics/tactical_scenarios.py sensor_query --pid 18552 --unit 24
py tests/run.py test_tactical_policy test_tactical_bridge
node --check headless/tactical_bridge.js
```

Scenarios change existing owned nonleader infantry. Objective pursuit leaves the
soldier near the captured objective; it is not a scene reset. Normal native orders
continue after detachment. Run each scenario separately. The bridge refuses another
pending request and does not replay uncertain submissions. `input` requires an
existing owned selection, verified keyboard bindings and actual game-window focus.

The complete suite passes 214 tests; the latest focused run passes 38 tactical tests
(one runs 36 mocked bridge admission/serialization/observation cases).
Those mocks cover stale match/incarnation, ownership, inactive units, direct-control
locks, manual revisions, duplicate intents, reuse invalidation and stopped bridges.
They are not live death/reuse validation. Pure-policy cold-step profiling with 64
contacts/64 cover candidates measured medians of 1.16, 2.47, 4.63 and 10.04 ms for
8, 32, 64 and 128 units respectively (five samples each; not native engine profiling).

## Remaining acceptance gates

Phase 0 is partial: live death/reuse, complete player-origin reclamation, direct
control and pause/new match remain. Script loss was tested while observing; loss
with active combat/construction still needs validation. Individual native
squad-leader commands can expand their scope, so diagnostic actions exclude leaders.
The emission observer handles scoped mode commands; this is not full verification
of every manual command/direct-control path.

Phase 1 has local one-unit objective evidence and offline retreat/recovery cases.
It still needs independently controlled squads, verified threats and matched combat
trials. Phases 2–6 have policy code but lack enabled live dependencies: cover
protection/firing suitability and occupancy, weapon readiness, per-unit contact
visibility/death, formation spacing, casualty-normalized defensive boundaries and
physical construction/resource accounting. No accuracy advantage is claimed.

Independent-client synchronization remains unverified. Production action capabilities
stay disabled until their gates pass; diagnostic serialization is not a certificate
of multiplayer agreement. The overall goal remains unfinished.

The [saved trial report](../validation/tactical_implementation_summary.md) retains
both passed and failed scenarios. The latest lifecycle run is
[`tactical_scenario_20260907_044829_167644`](../validation/tactical_scenario_20260907_044829_167644/summary.json).
Additional offline fixes preserve motion across repeated observation timestamps,
choose alternating groups once per squad update, require known ammunition for
covering fire, invalidate pending advances on urgent danger, allow occupation of
completed defenses, and bound cancellation tombstones without unsafe eviction.

The sensor query is diagnostic only: it reads bounded perception vectors, resolves
subjects against the current infantry registry without dereferencing stale subject
pointers, and never substitutes an actor's current transform for recorded position.
The native `0x10000000` record flag marks a position set by several event paths;
it is not sufficient evidence of visual contact. The original no-bot scene reached
200/200 VP and closed the native purchase gate. Its results were saved before the
fresh AI scene described below.

## Fresh AI scene and native spawning

The guarded host flow saved prior results (`run_20260907_010558_334928`), dismissed
them, assigned easy bots to open slots 2 and 5, applied its 75 VP / 10000 MP test
profile, and verified a new match generation (`run_20260907_010850_598949`). The local
human remains on team A.

- `purchase_query` checks the offered local entry and native availability gate.
  Individual rifle template 166 was not offered. Squad template 854,
  `riflemans(usa)`, was offered but unavailable in the completed match; it became
  available after the fresh start. No resource or readiness guard was bypassed.
- `purchase` invokes the normal native UI purchase wrapper, which allocates,
  serializes and destroys its own temporary order. Assembly established `stdcall`
  (`ret 4`), correcting an initial declaration before any purchase invocation.
- One purchase spawned 12 owned soldiers, IDs 33–44. Initial appearance was observed
  after 0.26 simulation seconds; a later baseline verified all 12. Evidence:
  `tactical_scenario_20260907_051013_747680` and
  `tactical_scenario_20260907_051127_449769`. Resource accounting remains unverified.
- All spawned members were Hold position and unenrolled. Diagnostic `enable` changed
  only soldier 34 to Move at will. This is scene setup, not proof of player-origin
  reclamation.
- The first AI objective trial exposed a false positive: team capture was counted
  while the soldier remained far away. Its summary is corrected to `observed`, with
  the original preserved as `summary.original.json`. The runner now records proximity
  and labels capture attribution as team-only.
- Another trial yielded on two native commands with no owned addressees. The bridge
  now filters those before changing the local command revision. Regression coverage
  verifies that foreign commands preserve enrollment while owned manual commands
  revoke it. A follow-up ran 44.56 simulation seconds / four moves and recorded team
  capture without unit arrival (`tactical_scenario_20260907_051722_961611`).
- Invalidated policy goals now cancel queued objective moves. New scenarios also
  hash the scenario source and record configuration. A 15-second observer collected
  67 samples without a bridge fault; no foreign commands occurred in that short
  window, so it is not a positive live filter test.

Additional scenario commands: `purchase_query`, `purchase`, and `enable --unit 34`.
Purchase is limited to the verified named US rifle squad template. It can run before
local infantry exist but requires an active local playing team. These diagnostic
results do not enable production multiplayer deployment.

## Perception, ammunition and completed-match checks

Native perception scanning clears/sets record bit `0x20000000` from its visual
test and latches it into record flag `0x40`. A separate current-target path can
refresh recorded position without that visual result. Diagnostic queries expose
these separately; position freshness never enables an unseen contact. A 30-second
watch collected 138 samples with maximum query time 1 ms but no visual transitions
(`tactical_scenario_20260907_052732_162552`), so occlusion remains unverified.
Soldier 34 subsequently disappeared from the controllable registry. The unavailable
identity rejection passed (`tactical_scenario_20260907_053315_827121`); disappearance
is not recorded as a confirmed death.

`weapon_query` follows the validated current-weapon slot and bullet-ammunition
owner chain without native calls or writes. Native accessors and serialization
identify inventory count, loading/reload flags and recovery deadline. Soldier 35
had eight rounds and clear loading/reload flags
(`tactical_scenario_20260907_054021_221148`). Readiness remains unknown pending
shot/reload attribution. `weapon_watch` records bounded 30-second field transitions.

The fresh AI match eventually reached native manager state 3 (completed). A mode
submission returned serialized but did not execute while simulation ticks still
advanced (`tactical_scenario_20260907_054551_478123`). Diagnostic mutations now
require the verified manager type and active state 1; the completed-match rejection
was observed before submission (`tactical_scenario_20260907_054722_190706`). This
does not promote serialization acknowledgements to completion. The focused suite
passes 38 tests, including 36 mocked native admission/query cases; mock evidence
is separate from native behavior.

The second controlled AI start (`run_20260907_014903_043604`) followed normal
completion capture and saved results, using the existing guarded host flow. One
rifle-squad purchase and single-member opt-in succeeded. Soldier 26 approached f4;
team capture preceded its arrival, so the scenario remains `observed`. A later
baseline placed it at the objective. A further 600-world-unit approach reached its
destination and recorded 50 native visual transitions across nine enemy-owner
identities (`tactical_scenario_20260907_055308_194139`). This is not yet controlled
occlusion validation.

The read-only bullet-constructor observer accepts only the verified shooter call
site and current owned registry identities. In
`tactical_scenario_20260907_055351_183711`, 143 successful weapon samples contained
nine attributed bullet constructions matching ammunition decreases. Zero rounds
at simulation tick 251224 became eight at 257304, following recovery deadline
257204. The requested-reload flag remained set during ordinary firing as well;
it cannot by itself identify an active reload. The final query was rejected when
the unit became ineligible, leaving the full 30-second scenario failed. Partial
observations remain usable evidence; no hit, damage, accuracy or death claim is
made. Future interrupted watches preserve their partial counts in the summary.
All 214 tests passed again (`tactical_full_suite_20260907_0553.log`), and all eight
checked hook sites matched original bytes after detachment.

Objective-free policy snapshots now support rallying toward stationary, owned
infantry in another squad when its route is explicitly reachable and observed
danger is no greater. Moving squads do not chase each other, and rally movement
stops ten policy units short of the anchor. The chosen anchor remains committed
until invalid; loss, takeover or movement beyond five units invalidates queued
rally movement/cover orders. Unknown routes and foreign units are excluded.
This fills the friendly-position fallback in phase 1 but is not enabled by the
live adapter until its route observations pass validation. The focused suite
passes 41 tests, including arrival spacing and stale rally cancellation.

Defensive occupation now rejects positions beyond the local support/contact
boundaries around each objective. Up to eight strong, confident observed approaches
are considered separately; opposite threats cannot cancel through averaging.
Changing contact/support invalidates an unsafe pending defensive reservation.
Low-confidence local memory alone does not justify a new construction job, while
existing-cover suitability remains independently required. These are conservative
policy rules, not a measured map-wide front or native construction capability.

Casualty penalties can be normalized by explicitly supplied complete friendly
positions. The sparse presence history is capped at 512 cells and expires after
120 simulation seconds. Without that observation, the denominator remains unknown
and raw casualty penalties apply. Only deduplicated confirmed death events add
casualties. The live adapter does not yet supply this presence/death contract.

All 220 tests passed (`tactical_full_suite_20260907_defensive.log`). A separate
five-sample offline maximum-size snapshot profile (128 units, 256 contacts, 128
covers and 128 objectives) took 42.4–44.6 ms per initial policy step. This checks
policy work size only; it does not establish native callback cost or multiplayer
performance. Evidence: `tactical_defensive_policy_profile.json`.

Alternating advances now retain the last terminal action result per member and
require a completed move/cover action from the current advance before switching
groups. A failed, uncertain or cancelled action is not arrival. Coordination
falls back to individual tactics for ten simulation seconds after failure or a
30-second wait, preserving the individual retry backoff. A new coverer still needs
verified readiness, ammunition and firing access. Focused validation passes 46
tests, including failed advances and accepted-versus-completed group switching.

Further static aiming analysis is saved in `tactical_mapping_20260907/aiming_state.txt`.
The aimer reset path writes state 2 at offset `0x0c`; several other fields concern
ballistic projection or placement. Their enum/behavior meanings are not yet
validated, so none is exposed as a guessed ready/aiming boolean.

The controller module now contains the bounded `Runtime` used by the objective
diagnostic: policy evaluation, queue admission, submission limits, tracked accepted
orders and separate terminal acknowledgements. Manual reclamation invalidates late
completion events; changed local authority stops the runner. Lost/unknown submission
replies stop it without replay. Expired unsent intents clear policy waiting state.
This execution core accepts a validated adapter contract; the general live `run`
command remains disabled by its native and multiplayer gates. It does not pretend
to cancel an already executing native order when only its queued work is retired.
All 227 tests pass (`tactical_full_suite_20260907_runtime.log`).

`aiming_ready_paths.txt` further establishes that native weapon gate `0x8433c0`
requires ammo flags `0x24` clear and recovery deadline zero. The shooter also checks
ammo availability and placement/aimer state; a positive ammunition gate alone is
not full firing readiness. These routines were inspected statically, not invoked.

The runtime-backed native objective trial completed eight submissions and seven
observed arrivals over 78.22 simulation seconds
(`tactical_scenario_20260907_060952_685477`). Team capture ended the trial while the
soldier remained 590 world units from f4; its eighth action was still executing,
so the outcome remains `observed`, not an individual capture pass. All eight
post-detachment code checks passed. The preceding purchase baseline timed out
before any action; a three-second observer then confirmed callback continuity
and the subsequent single purchase succeeded. The new match generation is saved
in `run_20260907_020845_946250`.

The native property registry names `dead` and maps its factory `0x7d1c30` to
vtable `0xdefd5c`, whose predicate `0x7cf8b0` reads health-wrapper `actor+0x32c`,
object pointer `+0x0c`, and status bit 1 at `+0xf8`. Eligibility checks mask 5,
so ineligible and dead are not interchangeable. Snapshots now expose
`nativeDeadPredicate` independently of the still-unknown `alive` field. Mock cases
distinguish bits 1 and 4; 51 focused tests pass (38 native fixture cases).
A three-second live observer produced 13 samples without fault
(`tactical_20260907_061543_532328`); a positive death transition remains required
before enabling the death capability. Static evidence is in
`actor_dead_property.txt` and `dead_predicate.txt` under the tactical mapping run.

Three subsequent `death_approach` trials advanced soldier 37 by bounded native
legs and recorded 754 samples without its death or disappearance. A contact query
then observed 40 true, 36 false and two unknown native death predicates across 78
records (`tactical_scenario_20260907_062030_418978`). Contact health is read only
for registry-validated subjects with both native visual flags set; unknown or
hidden records remain null. A 137-sample contact watch recorded three visual
transitions but no death transition (`tactical_scenario_20260907_062104_649058`).
These positive static states do not complete transition/reuse validation.

The owned-infantry capacity check now runs after filtering foreign owners. The
fixture accepts exactly 128 owned infantry followed by a foreign registry entry
and still rejects 129 owned infantry. All 51 focused tests pass, including 42
mocked native cases and explicit hidden-contact death-read exclusion.

## Physical fortification mapping

The shipped `interface.pak` defines infantry action `barricade`: it requires
`sandbag_kit`, takes the item, reserves hands, runs `squat_repair_1/2` for total
time 15, unreserves hands and installs `sandbag3` with exact placement. This is
physical construction, separate from the cannon-only `round_sandbag` action using
`sandbag_kit2`. Shipped US rifle breeds include one sandbag kit, but that definition
does not prove a particular live unit still has one. Exact extracted action text
and entry hashes are saved in `fortify_shipped_actions.json`; inventory definition
matches are saved in `sandbag_definitions.json`.

Native `eFortifySequence` has factory `0x8d9790`, parameterized constructor
`0x8d92b0`, vtable `0xdf9c90`, and state machine `0x8d9350`. It holds a referenced
line distributor at `+0x20`, reserves/releases cells, checks inventory, and dispatches
`eCustomActionOrder` through `0xa99580`. The action handler `0xaa6570` constructs
the sequence. Cell validation `0x8d8cf0` performs collision checks; cancellation
releases a reserved cell through `0x8d96c0`. These functions have not been invoked
by the controller. Live availability, placement, item consumption, completion,
cancellation and replication remain required before enabling `build`.

Mapping evidence is under `validation/tactical_mapping_20260907/`: use
`fortify_sequence.txt`, `fortify_children.txt`, `fortify_constructor.txt`,
`fortify_action_identity.txt` and `fortify_dispatch_refs.txt`. Earlier exploratory
files named `fortify_entry.txt`, `fortify_build_paths.txt` and
`fortify_requirements.txt` also contain the adjacent **eFight** order (`0x8d8560`,
vtable `0xdf9bd8`) and melee helpers; those functions are not building prerequisites
or progress evidence. The factory names, not their table adjacency, establish this
distinction. No game resource archive was modified.

The barricade action constructor `0xaa7b90` registers its live pointer at
`0xfe84b0`. Its RTTI is `e_barricade@Action@Interface`, vtable `0xe1b2a8`, and live
action ID is 37. Diagnostic `barricade_query` verifies these before calling native
actor/inventory gate `0xaa3e20` on the simulation callback. Assembly verifies its
`thiscall` convention and `ret 4`; its byte signature is checked at attachment.
The gate returned true for held soldier 38
(`tactical_scenario_20260907_063123_784000`). Placement, item count and construction
completion remain unknown, and no building command was sent. The focused suite
passes 51 tests with 45 native fixture cases, including availability rejection,
wrong action type, and the distinction between inventory permission and placement.

The `install` instruction registry at `0xf3ae00` resolves factory `0xa9d370`,
vtable `0xe1a1dc`, parser `0xa9c640`, and execution method `0xa9ca60`. Parsing sets
the exact-placement byte at `+0x28`; execution uses the supplied position and
orientation, handles the held inventory item through `0xa9ddb0`, dispatches entity
event 4 through `0x78f230`, then creates the requested entity through `0x794120`
(call site `0xa9cc78`). Crucially, execution returns 1 even if entity creation
returns null. Construction completion must therefore require an observed created
defense and separate inventory accounting, not this return value.

Evidence: `install_factory.txt`, `install_execution.txt`, and
`install_resource_and_create.txt`. The exploratory `install_instruction.txt`
contains a neighboring instruction at `0xa9ced0`, not the registry-resolved
installation method. No installation or inventory mutation was invoked in this
mapping step.

The bounded barricade query now counts inventory stacks matched by the action's
native item filter (`0x644480`, verified `thiscall`). It validates the inventory
type, vector size, distinct item pointers, tag-vector bounds, a nonempty action
filter and the resulting count. Stack quantity is item `+0x24`; `+0x2c` is loaded
ammunition and is deliberately excluded. Live soldier 38 reports one matching kit
and native availability true in `tactical_scenario_20260907_064348_845829`.
Placement and construction remain unverified. All eight observed hook sites were
restored after detach. The focused suite passes 51 tests, including 49 native
fixture cases covering duplicate entries, missing filters, unmatched items and
excessive counts. No building command was submitted.

Further static mapping (`fortify_distribution.txt`, `fortify_placement.txt`)
resolves the line distributor constructor `0x8d88c0`: action entity name `+0x5a8`
and spacing `+0x5c4` determine native cells between the supplied endpoints. The
placement predicate `0x8d8cf0` validates a cell against entity geometry and world
collisions. These are internal construction objects with native ownership and
cleanup; they have not been invoked as independent placement queries. Their
existence does not establish that a proposed site is usable or replicated.

## Physical construction trials

Diagnostic `barricade` sends one native action ID 37 through serializer `0xaa9b20`
with the ordinary spatial-command fields. Admission requires an active supported
match, eligible owned nonleader, native availability, exactly one matching kit,
entity `sandbag3` and a destination within 150 world units. A one-unit nonzero
line avoids the engine's equal-endpoint fallback. Production construction remains
disabled: placement suitability, threat interruption and replication are not yet
validated. The diagnostic never replays an uncertain build.

The creation observer hooks `0x794120` only at caller `0xa9cc7d`, validates the
owned current unit/incarnation and the install instruction type, and records the
created entity's uint16 ID. Assembly verifies placement locals at caller EBP
`-0x10/-0xc/-8`. The original target argument is reused before this call and must
not be read here. The initial trial on soldier 18 timed out without an attributed
event (`065135_605813`); the subsequent soldier 21 trial (`065413_560237`) recorded
creation but its target-position telemetry was invalid. These runs are retained
as failed/observed evidence, not retroactively promoted to successful placement.

With corrected locals, soldier 19 created `sandbag3`, entity 36480, after 34.58
simulation seconds (`tactical_scenario_20260907_065615_643787`). The prepared point
was `(4720.07, -5246.18, 0)`, about 61.77 world units along the line from its start;
native cell centers use half the entity spacing. This exceeded the trial's preset
50-unit proximity check, so that check remains failed. Native cover subsequently
returned **entity 36480** as the source of both nearby cover candidates
(`065856_845191`). Soldier 19 settled in cover state 2 and stance 2 at one candidate
without a further diagnostic movement/cover order. This establishes a created
structure offering native cover slots, not measured ballistic protection.

Inventory accounting now also traverses the two native hand boxes, deduplicating
items shared with the inventory vector. `0x81a4b0/0x8192b0` resolve `hand_right`;
both hand-box getters `0x81cbd0` return item `+0x2a0`. The completed builder's
inventory, held and combined matching kit counts are all zero (`070217_619327`).
The diagnostic exposes these separately so taking a kit into hand is not called
consumption. Static evidence: `held_inventory*.txt`, `hand_item.txt`,
`cover_candidate_layout.txt`, and `cover_identity.txt`. Native cover record `+0x18`
receives the source entity ID through `0x8aa1e0`.

The focused suite passes 51 tests with 63 native fixture cases, including hand-item
deduplication and installation identity/call-site filtering. The full suite passed
227 tests earlier in this construction work. All nine checked hook sites were
restored after the latest live queries. A separate `barricade_cancel` trial now
waits for a held kit before submitting one native move away; it checks return to
the initial position, restored combined kit count and 20 simulation seconds
without creation.

The interruption trial subsequently passed on soldier 47 in the next controlled
bot match (`tactical_scenario_20260907_070548_743510`): one build, one move back
after the kit appeared in hand, arrival back at the starting point, combined kit
count retained at one, and zero installation calls over 20.02 simulation seconds
after interruption. The retained item remained in hand and was also represented
in the inventory vector; deduplication correctly counted it once. No claim of
returning it to a particular backpack slot is made.

Rebuilding at the cancelled site then passed the native creation/cover/accounting
gate (`070633_727633`): one sandbag entity 49272, 34.7 simulation seconds, combined
inventory-and-hands kit count 1 to 0, and two native cover candidates sourced from
entity 49272. This provides local evidence of reservation release after the tested
interruption. The native placement point remains offset from the line start by
half the cell spacing; the reported 50-unit point-proximity check still does not
pass and is not the native creation/cover gate. Tactical placement quality,
threat-triggered interruption, destruction, duplicate-site competition and remote
replication remain unverified. The full 227-test suite and JavaScript syntax check
pass for this implementation; full output is in
`validation/tactical_full_suite_20260907_construction.log`.

## Player-emission diagnostic failure and containment

An experimental native C caller attempted to exercise the manual-command observer
outside a reentrant JavaScript call. Compilation initially failed because the
embedded API exposes `ic->cpu_context`, not a getter (`071246_203785`). The compiled
same-script test then emitted a command but did not suspend enrollment
(`071316_545707`). A separate-script variant obtained no simulation callback
(`071529_054796`), and a subsequent plain observer also timed out.

External reads showed manager state 1, pause 0 and an unchanged simulation clock
of 470284. Thread inspection located the quant thread in the game's fatal error
dialog, whose text was `Undefined Interface::Command handler (76)! (eIC.cpp, 45)`.
The dialog explicitly stated that the program would terminate. This establishes
a command-stream failure after the diagnostic, not a proven root cause or a
manual-takeover pass. Evidence is retained in
`validation/tactical_native_handoff_stall_threads.json`,
`tactical_native_handoff_error_dialog.json`, and
`tactical_native_handoff_game_log_tail.txt`. The last experimental helper source is
retained as `validation/tactical_native_player_failed_probe.js` for investigation.

The helper and experimental CLI path were removed. The bridge now rejects every
`asPlayerCommand` request before inspection or native submission, and the callable
native player-emitter binding was removed. The production observer remains
unchanged; actual manual takeover is still unverified. A regression fixture checks
the disabled entry, bringing the native fixture count to 64 (51 focused Python
tests pass). Ordinary serialized diagnostic orders retain their existing path.

The verified game-owned exception dialog was acknowledged, and PID 18552 exited.
The supported lobby workflow relaunched the same executable with
`-no_reload_caching` as PID 41944 (`run_20260907_032013_260532`). AI assignment and
configuration passed through the existing guards. No OS lock state was changed,
and no recovery/start guard was bypassed.

Recovery validation on PID 41944: AI gameplay loaded (`032142_677090`), a rifle
squad purchase succeeded (`072234_521541`), and 13 plain observer samples showed
continued simulation (`tactical_20260907_072310_924718`). The short movement order
on soldier 48 serialized and changed position but did not arrive within eight
seconds (`072243_771125`); it remains a failed arrival check. A separate stance
trial changed and restored posture successfully (`072326_194139`). All nine hook
sites restored after detach. The full 227-test suite passes with the new rejection
guard (`validation/tactical_full_suite_20260907_player_guard.log`). The resumed
game remains running; no tactical controller is attached.

## Cover-source identity and event continuity

Cover queries now resolve their source entity through the native entity-ID registry
at `0xfe3ff4`, following the lookup performed by `0x9dc2b0`. Lookup is bounded to
64 tree steps and verifies the returned entity ID and type bit before use. Up to
256 queried sources retain attachment/match generation and incarnation; no saved
source pointer is dereferenced. Missing or replaced entities invalidate identity.
The native registration hook `0x9dc350` invalidates known sources before a
registration change, including reuse of the same ID and address. Invalidation is
reported separately from destruction (`destroyed: null`). Match change and stop
clear the cache. Static evidence is in `cover_entity_registry.txt` and
`cover_registry_remove.txt` under the mapping evidence directory.

The native fixtures cover missing sources, same-address reuse, replacement
addresses, mismatched IDs and unrelated registrations. Queries and rejected
diagnostic requests now return all events consumed by their baseline snapshot in
`observedEvents`; previously those events could be discarded unless the query
returned a specialized subset. Fixtures verify both manual-command and cover-source
invalidation delivery. Callers must deduplicate repeated specialized event fields
by the existing event key.

On PID 41944, soldier 48 built sandbag entity 40806, consumed one combined kit and
obtained native cover sourced from that entity in 35.22 simulation seconds
(`tactical_scenario_20260907_072833_157356`). The new registry lookup resolved its
identity successfully. A subsequent query (`073054_132875`) resolved the same
entity on a fresh attachment. Live entity removal/destruction and same-address
reuse are still unverified; the offline fixtures are not substituted for those
engine tests. All ten checked hook sites restored after detach. The focused suite
passes 51 tests with 69 native cases; the full 227-test suite and JavaScript syntax
check pass (`validation/tactical_full_suite_20260907_cover_identity.log`).

## Ordinary movement endpoint spacing

The policy now avoids assigning ordinary advances to endpoints within three
policy units of another live owned unit's pending destination. It tries the
original short leg, then 75% and 50% of that same leg, preferring clearance from
stationary units. If stationary units crowd every available candidate, it uses
the candidate with greatest clearance; only pending destinations can make it
wait for space. There are no lateral offsets or fixed
formations, and native navigation still determines the route. Urgent withdrawal
retains its existing path. The three-unit spacing is an offline starting value,
not a live-validated collision radius or exposure threshold.

Testing caught and fixed a backoff interaction: shortening an endpoint must not
bypass a recent failed/uncertain advance. Ordinary moves therefore retain their
move backoff even when spacing would propose a different endpoint. Focused tests
verify distinct collinear endpoints, progress after moving members clear them,
and progress despite stationary blockers. The full suite
passes 229 tests (`validation/tactical_full_suite_20260907_spacing.log`).

An offline fixed-snapshot comparison used 128 units, 256 distant weak contacts,
128 cover candidates with unknown suitability, and 128 objectives. Seven samples
with the prior endpoint arithmetic had median 38.57 ms; spacing had median
44.08 ms and maximum 46.68 ms. It issued 35 initial orders versus 128 in that
crowded fixture. This measures policy computation and endpoint deferral only,
not live simulation cost, physical spacing, narrow-route progress or tactical
benefit. Configuration, source hash and raw timings are saved in
`validation/tactical_spacing_policy_profile.json`. A live squad movement trial
remains necessary before enabling or tuning this behavior for deployment. These
profile numbers precede the stationary-blocker fallback described below.

The four-member `squad_advance` diagnostic records every serialized leg and only
accepts observed arrivals before their simulation deadlines. Run
`tactical_scenario_20260907_074319_938134` completed three members' legs but its
one-leg limit prevented them from clearing space for the fourth. A revised trial
allows two legs per member and waits for all issued legs to complete. Run
`tactical_scenario_20260907_074526_015541` issued zero orders: the previous three
soldiers occupied all candidate endpoints for every new member (nearest gaps
3.95–46.79 native world units, below the 60-unit threshold). This exposed a
permanent stationary-blocker deadlock, fixed by treating stationary positions as
a preference while retaining hard pending-destination reservations and failed
move backoff. All 229 tests pass after the fix. The immediate live retry
`tactical_scenario_20260907_075219_767972` was rejected because the match had
completed; native manager state 3 was independently confirmed. None of these
three runs establishes the live squad-advance acceptance gate.

After normal completion/results capture and a fresh supported AI match, run
`tactical_scenario_20260907_075429_193969` passed: opted-in nonleaders 37–40 all
advanced toward uncaptured f4. Six serialized legs completed within their
individual simulation deadlines over 18.96 simulation seconds (159 samples),
with at most four concurrent orders. Minimum concurrent endpoint separation was
120.24 native world units; minimum pairwise physical separation changed from
13.42 at baseline to 130.61 at completion. All ten observed hook sites matched
their original bytes after detach. This verifies bounded local squad progress
and completion accounting, not continuous physical clearance, a narrow gate,
combat exposure improvement, manual reclamation or independent-client replication.
The report now preserves these squad metrics separately from release gates.

An offline replay of the exact stalled baseline now emits three initial moves
instead of zero (`validation/tactical_stationary_blocker_replay.json`).

## Owned death transition during objective approach

Run `tactical_scenario_20260907_075543_648771` advanced unit 37 toward f2 and
stopped on ineligibility before reaching it. At simulation tick 207864 the unit
was eligible/enrolled with native death predicate false. At 208084 the same
match generation, unit ID, incarnation 1 and entity ID 40962 had predicate true,
eligibility/enrollment false, empty squad membership and unit revision 1 instead
of 0; global command revision remained 0. No further order was issued. The raw
run and extracted `validation/tactical_owned_death_transition.json` preserve this
positive transition separately from disappearance. This validates the observed
owned predicate transition and relinquishment in this encounter; it does not
validate reused identities, an attributed attacker, or full combat policy.

Run `tactical_scenario_20260907_075923_029372` then addressed the still-enumerated
unit 37 with native death predicate true and eligibility false. The bridge
rejected the enrolled stance request, issued zero native orders, and all ten
hook sites restored after detach. `reject_unavailable` now accepts this explicit
dead-row case as well as an absent ID; it refuses an eligible or ambiguous row.
The standalone rejection does not itself establish a death transition.

The bridge now emits `owned_death` once when an owned incarnation's native death
predicate changes from false to true after eligibility was observed in that same
incarnation. The event includes unit identity, observed
position and simulation time; no new hook or native mutation is introduced.
The incarnation's enrollment record retains the observation, so repeated samples
or a temporarily cleared predicate cannot count it twice. Existing corpses on
attachment produce no event, and disappearance does not synthesize one. Offline
native fixtures cover transition, disabled-but-not-dead, duplicate suppression
and corpse attachment. A further fixture excludes an initially inactive unit
that was never observed eligible (71 fixtures). All 229 tests and the JavaScript syntax
check pass (`validation/tactical_full_suite_20260907_owned_death.log`). Live
observation `tactical_20260907_080133_821161` sampled 13 snapshots across 2.64
simulation seconds: already-dead unit 37 produced no new death event.

The subsequent approach `tactical_scenario_20260907_080207_003167` ended with
an active-match rejection before reaching combat. Native manager state 3 was
confirmed independently; this does not validate live delivery of the new event.

## Combined combat observations

`combat_approach` now samples the existing bounded weapon and sensor queries once
per simulation second during objective pursuit. Queries and moves use one
monotonic native request sequence, while policy intent identity remains separate.
Events returned with queries and rejections are retained and deduplicated; a
fixture verifies interleaving and death-event preservation on query rejection.
The full suite passes 230 tests (`tactical_full_suite_20260907_combat_probe.log`).

Run `tactical_scenario_20260907_080816_110891` delivered four `bullet_created`
events for owned unit 47 at ticks 177204–178404, followed by exactly one
`owned_death` at 178464. The same incarnation became ineligible/unenrolled with
revision 1, and the objective trial stopped without another command. Weapon
samples showed ammunition changing from 8 to 5 before the fourth bullet event;
the reload-request flag was set while firing, consistent with earlier evidence
that it does not identify active reloading. The approach did not pass its capture
goal; the run remains failed rather than being relabeled a combat success.

There were 123 sensor samples, including 30 records for owner 4. A separate
read-only native player-table observation identifies owners 2/3 as team a and
owner 4 as team b (`tactical_match_player_teams_20260907.json`). Raw contact
visibility fields remain separate from this team attribution. Extracted event,
ammunition and first/last contact evidence is saved in
`validation/tactical_combat_observation_20260907.json`. This validates local
delivery of the new death event, not attacker attribution, hits, accuracy,
successful withdrawal or multiplayer replication.

Of the 30 opposing-owner records, six had both native visual flags set and 24
had both clear. None was the sensor's current-target record. This preserves
the distinction between team identity, visual flags, and targeting.

Snapshots now expose bounded native `playerTeams`, and registry-resolved sensor
identities include that owner's team or null when unavailable. Duplicate owner
entries fail observation instead of silently selecting a team. No enemy or
visibility boolean is inferred by this addition. Live observation
`tactical_20260907_081218_965029` reproduced owners 2/3 on a and 4 on b;
`tactical_scenario_20260907_081302_943593` exercised the enriched sensor query.
Native fixtures cover distinct teams, missing owners and duplicate rejection
(73 fixtures); all 230 tests and JavaScript syntax checks pass
(`tactical_full_suite_20260907_contact_teams.log`).

## Native adapter execution wiring

`NativeAdapter` now converts owned eligible infantry, native squad membership,
enrollment revisions, stance, simulation time, active-match state and pause state
into typed policy snapshots. Objective and death-event conversion requires their
explicit bridge capability gates. Unsupported contacts, cover, readiness, attack
and construction are not enabled by the adapter. Raw sensor flags are not treated
as decoded observations. Native pointers remain in the bridge.

Policy action revisions and native unit revisions are separate. A native
same-value reenable produces a policy event that retires the old action before
its late arrival can be accepted. Returned submission events are retained for the
next snapshot, and native death event keys preserve casualty deduplication. Death
events retain their observed simulation timestamp for casualty aging (see the
continuity update below). No complete allied-presence denominator is inferred from owned
infantry alone.

The gated native `submit` path supports the mapped move/stance packets, requires
enrollment and a finite submission deadline, and checks that deadline on the
game callback. Serialization remains an acceptance, not completion. The adapter
reports movement completion only within 40 native XY units and before its intent
deadline; stance completion requires the observed native stance. Known native
admission refusals cancel unexecuted policy work without recording a failed route;
uncertain replies still stop the runtime without replay. An inactive supported
match stops conversion. The CLI now connects this adapter to `Runtime` after its
existing release gates pass; none of those gates was promoted by this change.

Six adapter tests cover coordinate/revision/deadline conversion, observed arrival,
same-value reenable, retained/de-duplicated death events, known refusal, unsupported
features, pause/inactive state, foreign units and late completion. Native fixtures
also verify production admission refusal with current gates and deadline rejection
under fixture-only promoted gates (75 fixtures). All 236 tests and JavaScript
syntax checks pass (`tactical_full_suite_20260907_native_adapter.log`). Live
observation `tactical_20260907_082108_384337` returned 13 snapshots of the completed
match with playing=false and paused=false. `tactical_20260907_082111_928063` confirms
that `run` still refuses unmet identity, clock, death, authority, synchronization
and move gates. This is tested execution wiring, not enabled multiplayer AI.

## Selected native cover source and slot

The diagnostic cover request can now carry the queried source identity and an
explicit nearby point. Before serialization, the bridge re-queries that point
and requires the same match/entity/incarnation and a native slot position within
one world unit of the selected point. A changed source, reused identity, missing
entity or changed slot is rejected instead of silently replacing the policy's
choice with another nearby cover position. Explicit points retain the 600-world-
unit distance bound. No protection, firing-access or route score is invented.

The existing `cover` scenario now selects a source-identified candidate first and
uses one monotonic sequence across query, cover order and return move. Six native
fixtures cover exact selection, stale generation, wrong source, moved slot,
missing entity and same-address registration reuse (81 fixtures total). All 236
tests and JavaScript syntax checks pass
(`tactical_full_suite_20260907_selected_cover.log`).

Fresh-scene construction `tactical_scenario_20260907_082709_296724` created a
sandbag with native cover. `tactical_scenario_20260907_082807_788140` then selected
entity 49244, incarnation 1 at (4782.1802, -5350.2681), serialized the checked
cover order, observed native cover state with proximity, and returned to its
starting area. All ten hook sites restored after detach. This validates the
selected-slot local command contract, not tactical suitability, destroyed-cover
recovery in combat, or independent-client replication. Production cover selection
remains disabled pending those mappings and gates.

## Event continuity and delayed casualty aging

The bridge no longer silently clears pending events after a polling lapse over
five wall-clock seconds and then accepts more commands. Losing queued events
records a persistent observation fault, preserving any earlier fault; subsequent
diagnostic submissions are refused. A quiet lapse with no events does not
invent a loss. This does not cancel orders already executing in the engine.

Native death events now carry their simulation observation time through the
adapter into policy `Event.observed_at`. Casualty cells use observation time,
not delivery time, for their existing bounded decay. Late events no longer gain
a fresh lifetime, older arrivals cannot advance a cell's timestamp, events older
than the 120-second memory window add nothing, and future/nonfinite timestamps
are rejected. Legacy synthetic events without a timestamp use snapshot time.

Tests cover a 90-second delayed casualty and expiry, out-of-order/expired events,
invalid timestamps, native timestamp preservation, and watchdog behavior with
and without lost events. All 240 tests (83 bridge fixtures) and JavaScript syntax
checks pass (`tactical_full_suite_20260907_event_continuity.log`). Normal live
polling `tactical_20260907_083301_118129` returned 13 snapshots without a fault.
The watchdog-loss branch is fixture-validated; this does not claim an induced
live loss during combat or construction.

## Native contact relations

Static mapping now follows sensor relation calculation through `88d630`,
`9c9330` and `9c9560` to the native relation table at `fe37e0`. Its begin/end
pointers and row stride describe a dynamic flat matrix; it is not a fixed
18x18 allocation. A read-only live table sample was 5x5 and matched the observed
team assignments (`tactical_native_relations_20260907.json`). The bridge reads
bounded entries without invoking a native function. Exact code signatures guard
the table accessor and the call site's table address.

Sensor records now expose `nativeOwnerRelation` and `nativeSensorRelation`.
The latter mirrors the record's perceived/actual ownership mode and the native
subject-status precondition. Only native relation 1 maps to enemy=true and 2 to
enemy=false; missing, out-of-range, neutral, unknown or inactive cases remain
null. Actual owner relations do not override perceived local ownership. No
current enemy transform is read for this decoding, and visible remains null.

Live query `tactical_scenario_20260907_083943_909593` returned two owner-4 records
with relations 1/1 and enemy=true, 24 owner-2/3 records with 2/2 and enemy=false,
and two inactive owner-3 records with sensor relation/enemy null. It issued no
orders and all ten hook sites restored after detach. Ten new fixtures cover
table orientation, allied/enemy/neutral/unknown values, missing/malformed bounds,
perceived ownership, actual-owner mode and inactive subjects (93 fixtures total).
All 240 tests and JavaScript syntax checks pass
(`tactical_full_suite_20260907_native_relations.log`). General contact capability
remains disabled until visibility/lifetime gates pass; this does not enable
targeting or prove threat-memory behavior in combat.

## Visual-pass timing and conservative decoding

Static sensor update `88daf0` clears the visual-result bit at the start of its
four-vector pass, performs native visibility checks, updates the visual latch,
copies visible records' positions and stamps sensor +0xb0 on completion. Record
+0x40 is a visual-transition timestamp; +0x44 is the position-update timestamp.
Target preparation `889210` can also update position through `88c150`, so position
freshness alone cannot establish sight. The bridge now exposes these separate
clocks, with code signatures guarding the visual pass and completion stamp.

Watch `tactical_scenario_20260907_084324_486671` collected 145 queries across 27.03
simulation seconds and 29 visual-pass timestamps. Pass age ranged 3–1066 ms.
There were 1,595 record samples with both visual flags set and matching position/
pass timestamps, and 2,030 with both clear and nonmatching timestamps. No visual
transition occurred in this stationary completed-match scene. Raw counts and
examples are saved in `tactical_visual_clock_observation_20260907.json`.

The diagnostic decoder requires a registry-resolved identity and a completed
native visual pass no more than two simulation seconds old. Both clear flags
produce visible=false. Both set flags additionally require position-valid and
position timestamp equal to the completed pass; only then are visible=true,
`visualObservedPosition` and `visualObservedAtTicks` supplied. Mixed flags,
unmatched updates, zero/future/stale pass timestamps remain unknown. Current
subject death state is read only for the decoded visible case. Raw recorded
positions remain separate and are not promoted to observed positions.

Nine fixtures exercise these distinctions and the two-second boundary (102
bridge fixtures total). All 240 tests and JavaScript syntax checks pass
(`tactical_full_suite_20260907_visual_decoder.log`). Live query
`tactical_scenario_20260907_084736_334615` decoded 11 visible owned contacts in the
completed match. This verifies data shape and timestamp agreement, not active
obstruction, unseen movement or reacquisition. General contact capability remains
disabled. The policy's current half-second contact-freshness window also needs
alignment with the measured native cadence before native contacts are enabled.

## Bounded contact collection and active approach

The bridge now has a gated perception collector that samples at most four owned
squad observers per snapshot, rotates observers and caches at most 16 reports
for two simulation seconds. It drops reports for lost eligibility, enrollment or
identity, and filters cached contact identities against the current registry.
It uses the same native sensor decoder as the diagnostic query, with no new
native function calls or hooks. A fixture exercises 20 observers, cache bounds,
round-robin coverage and removal after Hold position (103 bridge fixtures).

The adapter consumes this data only when both contact and death capabilities
are enabled. It checks observer ownership, generations, position/pass timestamps,
freshness, incarnation reuse and conflicting observations; raw recorded positions
are never promoted. Native contact freshness is two seconds, matching the measured
visual cadence; synthetic contacts retain the half-second default. Freshly observed
friendly contacts remove obsolete enemy memory. Capabilities remain disabled in
the live bridge pending their remaining behavioral and lifecycle validations.

After normal completed-match recovery, a fresh bot match started in
`run_20260907_045536_797964`; purchased infantry IDs were 56–67. Approach
`tactical_scenario_20260907_085821_165512` exposed a diagnostic guard using initial
objective ownership after that ownership changed. It remains recorded as failed.
The guard now checks the current snapshot, with a regression test. Subsequent
`tactical_scenario_20260907_090108_233062` passed: unit 57 reached objective f4
within 7.414 world units after five orders and 57.54 simulation seconds. Capture
is attributed to the team; this does not measure that soldier's independent
contribution. All ten hook sites restored on detach.

That active approach collected 51 sensor and 51 weapon queries. Sensor pass age
was 0–1080 ms, with 19 visible-enemy record samples and 333 hidden-enemy samples.
Enemies 38 and 39 became visible, hidden, visible again and hidden again.
These are native visibility transitions in an uncontrolled approach, not proof
of particular obstruction geometry or unseen direction changes. Saved analysis:
`tactical_active_contacts_20260907.json`.

The active data also contained 219 visible-dead record samples whose native
relation was unknown. The adapter previously skipped these because it required
a boolean enemy relation. It now preserves unknown relation for a confirmed
visible death, allowing the policy to clear the matching memory without guessing
a team. Hidden, stale or unconfirmed deaths cannot take this path. Dead contacts
take priority at the contact budget limit. Saved-data adapter replay accepted all
219 such samples; these are repeated observations, not 219 distinct casualties.
The replay enabled contact/death gates only on copied evidence. All 247 tests and
JavaScript syntax checks pass (`tactical_full_suite_20260907_contact_death.log`).

## Hidden replacement identity and completed-match admission

The adapter now supplies bounded identity-only contact observations alongside
visible contacts. The policy removes memory belonging to an older incarnation
when a registry-validated replacement is present, including a hidden replacement.
Previously, the adapter discarded the old visible record but could leave an
earlier policy memory alive until expiry. No position or death is inferred from
replacement. Inputs are limited to 4,096 unique, current-match identities with
positive integer incarnations; the native collector still bounds reports to
4,096 records. Adapter-to-policy regression coverage verifies removal without a
casualty, and policy tests reject duplicate, foreign and over-budget identities.
These are offline reuse checks; live native ID reuse remains unverified.

`tactical_contact_identity_profile.json` compares 20 cold policy decisions per
configuration after two warmups, at 1/32/128 units with 256 contacts, 128 covers
and 128 objectives. At 128 units the median was 43.78 ms without identity-only
records and 44.65 ms with 4,096; maximum was 48.76 ms with them. This is offline
whole-policy cost, not game-thread timing or a game FPS measurement.

Query `tactical_scenario_20260907_091216_479623` found unit 57 dead/ineligible
while the match remained active and the other eleven purchased soldiers were
alive/eligible. Unit 58 was enabled in `091306_291676`. The match then completed:
approach `091312_409155` recorded playing=false and native rejection before any
move serialization. The objective runner now checks active/unpaused state at
baseline and every iteration, avoiding a misleading uncertain-command report
for this known state. Live `091415_965671` verified the early refusal with no
trial action. The failed earlier attempt remains saved. The identity changes
passed all 248 tests (`tactical_full_suite_20260907_contact_identity.log`), and
all three objective-runner tests pass after the additional admission guard.

## Native rifle fire predicate

Read-only mapping followed shooter predicate `84d0a0` through `8433c0`,
`843f80` and `8433f0`, including explicit ECX disassembly. The predicate combines
ammunition/recovery, clip-boundary reload request, context availability and two
placement pointers. It does not establish that aim has settled. The ammo item's
virtual accessor (`845720` to weapon `843cf0`) resolves the already-read inventory
item. Static evidence is under `tactical_mapping_20260907/weapon_readiness_predicates.txt`,
`weapon_constructor.txt`, `weapon_init_calls.txt` and `ammo_item_accessor.txt`.

The diagnostic weapon query now exposes `nativeFirePredicate` only for the
observed rifle definition/placement/context/shooter vtables, with component
back-reference and bounded clip-size checks. Unsupported component types return
null. The decoder performs no native calls or property writes; exact signatures
guard the composite predicate and context/placement predicate. `readyToFire`
remains null and the weapon-readiness capability remains disabled.

Live idle query `tactical_scenario_20260907_091750_400042` on unit 58 returned
predicate=true, eight rounds, clear flags and zero recovery deadline. This was
a completed match; it proves neither active combat readiness nor reload behavior.
Ten fixtures cover ready/empty/recovery/ammo blocking, reload at/within a clip,
context/placement absence, unsupported types and mismatched owner. All 249 tests
pass, including 113 bridge fixtures
(`tactical_full_suite_20260907_fire_predicate_verified.log`).

Normal completion/results recovery (`run_20260907_051928_326013` and
`run_20260907_051942_599691`) preceded new bot match
`run_20260907_052024_528061`. Rifle infantry 16–27 were purchased in
`tactical_scenario_20260907_092122_018742`; unit 17 was enabled separately.
Active approach `092139_052528` ended failed when unit 17 became dead/ineligible.
It recorded five attributed bullet constructions and one confirmed owned-death
event. Of 147 weapon queries, 146 had predicate=true/eight rounds; the last had
five rounds, flags=16, recovery-until=194304 at simulation tick 193984, and
predicate=false. Sampling was roughly once per second, so it did not resolve
every shot or a complete reload cycle. All ten hook sites restored after detach.
Saved extraction: `tactical_fire_predicate_observation_20260907.json`. This supports
the recovery gate under firing, not settled aim, accuracy improvement or successful
autonomous capture. The finer-grained `weapon_watch` now includes recovery and
predicate changes in its transition records for the next firing validation.

## Capture-zone geometry and objective validation

Review of `092139_052528` found that f4 became team-owned at tick 106264 while
unit 17 was 589 world units away, and f2 became team-owned at tick 163444 at the
same approximate distance. Each route change followed a team capture; it was
not unexplained objective oscillation. The diagnostic's fixed 400-unit proximity
threshold did not recognize arrival within the actual capture zone.

Native `bca5c0` uses squared 3D distance and per-team squared radii at capture
engine +0x12c/+0x138, centered on map-point components +0x130/+0x13c. Its distance
weight is zero at the exact boundary, which therefore contributes no presence.
Read-only inspection found both radii equal to 360000 and both centers equal
to the objective component for every current flag. Evidence:
`tactical_mapping_20260907/capture_presence.txt` and
`tactical_capture_geometry_20260907.json`. Constructor fields +0x120/+0x124 are
capture timing, not radius; the older exploratory filename `capture_range.txt`
contains UI/timing initialization and is not the radius evidence.

The bridge now exposes `captureRadius` only when both positive radii agree and
both zone centers are the objective component. Different team zones remain null;
negative radii fault. Objective trials use strict 3D inclusion in this shared
zone, falling back to their old 400-unit check when native geometry is unknown.
Reports identify the proximity basis and radius, while capture attribution stays
team-only. Existing saved outcomes are not retroactively changed.

Live query `tactical_scenario_20260907_092920_086125` confirmed radius=600 for all
five flags during active gameplay and restored all ten hook sites. Four bridge
fixtures cover common/different radii, different centers and negative values;
scenario regression cases cover 589 units, the excluded 600-unit boundary and
vertical separation outside the sphere. All 250 tests pass, including 117 bridge
fixtures (`tactical_full_suite_20260907_capture_geometry.log`). A new live capture
trial using this threshold remains pending; this mapping is not a new capture pass.

## Cover query ahead of an advancing unit

Further static tracing of native cover filters (`cover_suitability.txt` and
`cover_record_geometry.txt` under `tactical_mapping_20260907`) distinguishes
nearby occupancy filtering (`8a9f30`) and candidate spacing (`8a7530`) from
protection or firing access. The existing nearest-cover query supplies no
validated threat-direction score; those fields remain unknown.

`cover_query` now accepts an optional three-coordinate destination as its search
center, limited to 600 world units from the owned eligible soldier. The existing
five offsets and time budget remain bounded. This permits inspecting cover near
the next movement goal; omitting the destination preserves the current-position
query. Candidate positions must be finite. The diagnostic CLI exposes this as
`cover_query --destination X Y Z` and saves the center in the query result.

Live `tactical_scenario_20260907_093308_528590` queried center
(4400, -5350, 55) for unit 18 and found no candidates in five samples. It issued
no orders and restored all ten hook sites. Tests cover a valid ahead point,
excess distance and nonfinite coordinates, preserving unknown suitability.
All 250 tests pass, including 120 native bridge fixtures
(`tactical_full_suite_20260907_cover_ahead.log`). This establishes bounded query
placement, not protection, native reachability or autonomous cover selection.

## Native attack target preflight

RTTI and constructor tracing resolve `Interface::Action::e_attack` to vtable
`e1ad00`, registered at `fe7eb0` by `aa48f0`. Read-only live inspection verified
action ID 30; it is not the adjacent move action's ID. Target serialization
`7f4000` writes type 2's entity ID from its entity pointer +0x54, an optional
target string, two coordinate triples and an additional four-byte field. The
target structure's entity pointer is at +0x20. Mapping evidence is in
`attack_action.txt`, `attack_target.txt`, `attack_command.txt` and
`attack_target_encoding.txt` under `tactical_mapping_20260907`.

The new diagnostic `attack_query` validates the native action and obtains
targets through the existing owned observer's sensor decoder. It returns at
most 32 distinct current identities, entity IDs, observed positions and observed
timestamps. Only visible, enemy=true, native-dead=false records qualify; target
registry incarnation/owner, entity validity and entity ID are checked again.
It never returns a hidden transform or invokes the attack action. This preflight
does not enable the production attack capability or establish command completion.

Seven fixtures cover visible, hidden, stale, allied, dead, invalid entity ID and
incorrect action type. The positive fixture places the actor's actual transform
at a different location and verifies that only its observed position is returned.
Live `tactical_scenario_20260907_093929_739117` returned zero eligible targets for
unit 18 with no order submission; all ten hook sites restored. All 250 tests and
JavaScript syntax checks pass, including 127 bridge fixtures
(`tactical_full_suite_20260907_attack_preflight.log`). Actual attack serialization,
execution and cancellation still require a separate validated trial.

## Diagnostic attack packet construction

Additional target mapping (`target_constructors.txt`, `target_defaults.txt`,
`target_entity_setter.txt`) confirms that `7f3e30` creates type 2 targets, while
`7f3f10` resolves the serialized entity ID and registers the receiver's entity
reference. The bridge now constructs the serializer's value subset in its
temporary command buffer: normal action command 0x101/flags 0x18, attack action
ID 30, type 2 target, validated entity pointer, observed coordinate triples and
an empty inline target-name string. It calls neither the target constructor nor
a native destructor and does not register the temporary input as an entity
reference. The existing synchronous serializer remains the only submission call.

Diagnostic `attack` requires the exact preflight generation, unit incarnation,
owner and entity ID, and repeats the sensor/registry/death checks at submission.
The scenario requires an enrolled soldier in an active unpaused match, performs
preflight, submits once, then records weapon fields for up to 30 seconds without
replaying the attack. Serialization and bullet observations do not mark attack
completion; the report keeps `attackCompleted=false`.

The existing seven preflight fixtures now also exercise attack admission. The
positive fixture verifies packet fields and observed rather than current enemy
coordinates. Subsequent stale match/incarnation/owner/entity and post-preflight
death submissions are rejected with no extra serialized command. All 250 tests
pass (`tactical_full_suite_20260907_attack_packet.log`). Live attempt
`tactical_scenario_20260907_094418_294380` stopped at the scenario's active/enrolled
guard before an attack was issued. No live attack execution pass is claimed;
the production attack capability remains disabled.

## Advance-to-contact attack trial

`attack_approach` reuses the objective trial's bounded movement and stops its
policy runtime when an eligible target appears. A shared weapon-observation
helper then performs fresh preflight, submits one attack with continuing native
sequence numbers, and records weapon state for up to 30 seconds. It makes no
further movement submissions. A regression test verifies the sequence across
preflight/attack/observation and no replay after an unknown reply. All 251 tests
passed (`tactical_full_suite_20260907_attack_approach.log`).

Normal completion/results recovery `run_20260907_054615_669471` and
`run_20260907_054658_740908` preceded new bot match `run_20260907_054734_664973`.
Purchased IDs were 26–37 (`tactical_scenario_20260907_094821_948903`); unit 27 was
enabled in `094837_521176`. Attack approach `094845_733769` issued 12 movement
orders, then serialized one attack (sequence 238) against visible owner-4 unit 43,
incarnation 1, entity ID 49211. The owned observer was at (-8.747, -734.198, 0),
and the enemy's observed position was (83.261, 1160.663, 0), about 1,897 world
units away. All subsequent 251 weapon samples retained eight rounds, with no
attributed bullet construction. The game continued ticking and all ten hook
sites restored after detach. Follow-up sensor query `095136_001511` found the
soldier alive at (66.991, -405.505, 1.390) and target 43 hidden, not its current
sensor target. This is a live serialization observation, not a firing or target
completion pass.

For the next trial, a 1,000-world-unit maximum observed target distance is fixed
before execution. The scenario chooses the nearest qualifying preflight target;
the approach continues until one enters that bound. This is a diagnostic scene
constraint, not a decoded native weapon range. The original longer-distance
trial is retained unchanged.

The closer trial `tactical_scenario_20260907_095309_391284` reused unit 27's
forward position and serialized one attack against owner-4 unit 23/entity 49167
at 900.307 world units. It recorded 43 successful weapon samples and seven bullet
constructions during the observation phase. Ammunition fell from seven rounds
to zero; a prior bullet at tick 323064 occurred during approach and is separate
from the seven post-attack events at 347624–351324. The predicate repeatedly
became false during nonzero recovery deadlines and true when they cleared.
With no ammunition it was false, with recovery-until=357324 at tick 351424.
An owned-death event at tick 352144 stopped the trial before reload completion.
All ten hook sites restored. The trial remains failed and `attackCompleted`
remains false; shooter-attributed bullets do not establish hits on the selected
target, accuracy improvement, or improved survival.

The extracted sequence is saved in `tactical_attack_firing_observation_20260907.json`.
All 251 tests pass after the distance-bound regression check
(`tactical_full_suite_20260907_attack_firing.log`). This supplies live evidence
of a serialized attack followed by firing and recovery transitions, while
leaving full attack/aim/reload and multiplayer release gates incomplete.

## Unattended duration and bounded evidence retention

The run CLI now defaults to continuing until stopped; `observe` still defaults
to 30 seconds. An explicit `--duration` retains the 0–3600-second validation.
This removes an unintended 30-second limit from the intended unattended workflow
without bypassing capability admission. Live `tactical_20260907_100025_420570`
still rejected run mode for the existing unverified gates before issuing orders.

Run-mode evidence now rotates four files of at most 16 MiB each instead of
stopping when the first file fills. Diagnostic trials and observation mode retain
their strict single-file limit. Oversized individual records still stop before
being written; failed I/O is not ignored. Newline handling is explicit so byte
accounting matches actual Windows files. Rotation keeps bounded archive metadata,
persists discarded-record/byte counts in `retention.json`, and includes final
retention accounting in the summary. Retention removes only generated files in
the newly created run directory. The retained JSONL data bound is 64 MiB; small
summary and retention metadata files are additional.

The report reader consumes retained archives in order, checks their record count
against final retention metadata, and labels incomplete history explicitly.
Runs with discarded or missing evidence are excluded from pass/time aggregates;
their metrics describe retained records only. Short rotated runs with no lost
records remain complete. Existing single-file evidence stays readable.

Four focused tests exercise actual disk rotation/limits, retained/discarded
accounting, report completeness after archive loss, strict and oversized-record
refusal, and CLI duration defaults. All 255 tests pass
(`tactical_full_suite_20260907_retention.log`). This verifies controller/log
infrastructure, not an enabled long-duration autonomous gameplay run.

## Gated production attack adapter

The production adapter now supports the mapped attack serialization contract,
behind the existing attack/contact/death capability gates. A policy target must
still be a fresh, visible, living enemy in the normalized snapshot. Submission
performs read-only native preflight for the same observer, validates generation,
observer ownership/identity, monotonic simulation time and the submission deadline,
then selects only the exact target incarnation. The serialized request carries
the fresh entity ID, owner, generation and incarnation. The bridge repeats native
visibility and identity checks before its normal synchronous serializer call.

Lost/reused targets and expired preflight are known-unexecuted cancellations,
without route penalties or attack replay. An unknown preflight response stops
the runtime. Preflight and submission share the bounded native event buffer and
strictly increasing sequence numbers. Attack serialization still yields no
synthetic completion acknowledgement; move and stance retain their observed
completion checks. General attack capability remains disabled.

Three adapter tests cover successful policy-to-preflight-to-submission mapping,
lost/reused/expired target cancellation and unknown reply handling. The bridge
fixture now exercises production attack admission: critical gates and the contact
gate reject it before fixture-only promotion. All 258 tests and JavaScript syntax
checks pass (`tactical_full_suite_20260907_attack_adapter.log`). Live observation
`tactical_20260907_100539_025602` completed nine samples with zero orders, all
production tactical gates still false, and normal bridge stop.

## Paused callback continuity and command rejection

The executor at `0x665420` skips quant dispatch `0x715c60` while its DWORD
pause-reason count at `0xfbaffc` is nonzero. The bridge previously depended on
that skipped callback for every snapshot, so a pause could cause callback timeout.
It now services paused requests at `0x715b60` entry, exclusively from executor
return address `0x665556` with ECX `0xfbafdc`. This call precedes lock release
at `0x665591`. Normal observations and dispatch retain the original quant hook.
The new site has an exact executable signature and is included in detach checks.

Paused snapshots use read-only inspection without new perception collection.
Every paused trial, including diagnostic queries, is rejected before native
function calls and before sequence admission. Pending requests are consumed, so
resume cannot replay them; wall-clock expiry still bounds unserviced requests.
The pause predicate now reads the same full DWORD as the native executor.
Four additional mock cases verify resume/no replay, wrong caller, wrong context,
timeout, frozen simulation time and nonzero high-byte pause count. All 258 tests
pass, including 131 native-memory fixture cases
(`tactical_full_suite_20260907_pause_dispatch.log`).

Live observation `tactical_20260907_101343_983918` completed nine snapshots with
zero orders. Read-only weapon query `tactical_scenario_20260907_101425_712399`
completed and verified all 11 hook sites restored after detach. Neither trial
paused the game; live pause/resume remains an open acceptance gate.

Static evidence in `pause_clock.txt`, `native_pause_calls.txt`, `pause_setters.txt`,
`multiplayer_pause.txt` and `network_pause.txt` distinguishes native local pause
reason insertion/removal (`0x715970`/`0x715a10`) from the multiplayer request path.
The ordinary pause handler `0xac7730` branches on `0xfeab08 != 0`; its multiplayer
branch calls `0xb57a00` with argument zero and issues native message type `0x25`
when the session permits it. Calling the local setter directly would not validate
this multiplayer path. No pause setter or request was invoked, no native pause
property was patched, and no capability gate was promoted.

## Native multiplayer pause and automatic resume validated

Two bounded bot-session trials now validate the previously open pause behavior.
The completed match was returned to the lobby with normal `finish-ai` and
`save-ai-results`; `run_20260907_061943_024658` then started a fresh AI match through
the supported host CLI. The game remained minimized and out of focus.

The diagnostic runner adds `pause` and `pause_watchdog`. Only these scenarios load
the extra pause RPC. It resolves the native service registry, validates supported
client/server vtables and local native pause authority, and calls the ordinary
client request entry `0xb57a00(client, 0)` with the verified thiscall convention.
The function constructs, sends and destroys its own type `0x25` message. The host
handles it via `0xb5b6b0` / `0xb52890`, broadcasts the resulting boolean, and the
client applies it through `0xb57f20` / `0xb58d30` and its normal update. No direct
pause-flag writes or local pause-reason setter calls are made by the diagnostic.
Static traces are saved as `pause_network_handlers.txt`, `pause_network_transition.txt`,
`pause_authority.txt`, `pause_message.txt`, `pause_host_toggle.txt` and
`pause_host_admission.txt` in `validation/tactical_mapping_20260907`.

Each attachment admits one pause and one resume request. Both execute only at
the verified locked executor callback. Resume requires the same session and
confirmed native paused state. A native callback safeguard requests resume after
five wall-clock seconds if Python has not already done so; neither request is
replayed. This safeguard relies on the injected script remaining loaded.

- `tactical_scenario_20260907_102147_291256`: PASS. Five paused snapshots held
  simulation tick 77084; a paused diagnostic query was rejected; explicit normal
  resume restored tick progression (77304). Zero unit orders.
- `tactical_scenario_20260907_102227_115169`: PASS. Five paused snapshots held tick
  115984. After 5.5 seconds without Python RPC/input, the safeguard had resumed
  gameplay and the next snapshot was unpaused at tick 117564 without bridge fault.
  No Python resume request was needed. Zero unit orders.

All 11 native hook sites were restored after both trials. These establish local
pause/clock behavior in this supported multiplayer bot session, not independent
client agreement. `simulationClock` is now enabled; identity lifecycle, command
authority, synchronization and all tactical action capability gates remain false.
Post-promotion observation `tactical_20260907_102337_182370` completed eight snapshots
and stopped normally. Two new orchestration tests also check that a failed frozen
clock assertion still requests resume. All 260 tests pass, including 131 bridge
fixture cases (`tactical_full_suite_20260907_clock_gate.log`).

## Ownership transitions between snapshots

The native ownership setter at `0x830f90` writes actor `+0x774` in both its normal
and initial-owner branches. Static evidence is saved in
`validation/tactical_mapping_20260907/actor_owner.txt`; `unit_registry.txt` separately
confirms registration/removal behavior. The setter invokes native callbacks around
its owner update, so detecting ownership only during later snapshots leaves a gap
when a tracked unit transfers away and back between polls.

The bridge now observes this setter with an exact code signature and invalidates
the tracked identity/enrollment at entry when the requested owner differs. It
checks the tracked actor pointer internally, ignores unrelated actors with the
same numeric ID, and preserves identity for same-owner setter calls. Invalidating
before native callbacks prevents stale submission even if the transfer returns
to local ownership before the next snapshot. The observation hook never calls
the setter or writes native properties. Registry-hook exceptions now set a bridge
fault rather than escaping without a recorded failure.

Three fixture cases cover an already queued request across away-and-back transfer,
same-owner calls, and an unrelated actor sharing the numeric ID. The old request
is rejected in the transfer case; the other two do not invalidate the live unit.
All 260 tests pass, including 134 native-memory bridge cases
(`tactical_full_suite_20260907_ownership_lifecycle.log`); JavaScript syntax passes.
Live pause/resume trial `tactical_scenario_20260907_102648_274897` also passes with
the new observation hook, and all 12 hook sites were restored after detach.
This validates attachment and cleanup, not a live ownership transfer or ID-reuse
scenario. The identity lifecycle capability remains disabled pending those tests.

## Preserve weapon work after losing visual contact

The policy previously protected observed aiming/firing/reloading only while a
visible target remained in the current snapshot. It could start ordinary movement,
cover/stance changes or construction immediately after losing sight, interrupting
unfinished native weapon activity. Those ordinary actions now wait while the
validated readiness observation remains busy. Urgent withdrawal still runs first;
readiness returning to ready permits progress again. Two focused policy tests cover
all three busy states, contact loss with/without cover, subsequent movement and
urgent withdrawal during reload. This does not supply unknown native readiness.

Static ammo transition mapping now distinguishes active runtime loading (ammo flag
0x20) and unloading (0x4) from saved-state loading (0x2) and the reload-request
latch (0x10). `0x8447e0` sets the request latch after ordinary shots. `0x844470`
prepares the pending round count, starts loading and sets 0x20; `0x844650` waits
for native animation/deadline conditions; `0x8454c0` clears loading and adds the
pending rounds. Saved evidence: `ammo_loading_flow.txt`, `ammo_loading_begin_end.txt`
and `ammo_reload_transitions.txt` under `validation/tactical_mapping_20260907`.
Weapon diagnostics expose `nativeLoading`, `nativeUnloading` and bounded
`pendingRounds`; exact function signatures guard these interpretations. Three
additional bridge cases check loading/unloading and pending-count overflow.
Neither these fields nor the request latch is yet promoted to policy readiness.

Normal rifle purchase `tactical_scenario_20260907_103217_661686` passed, producing
owned squad 156-167. Unit 157 was enabled in `103259_157596`. Firing approach
`tactical_scenario_20260907_103259_832616` ended with a completed match
(playing=false): 58 weapon queries, eight rounds throughout, no loading sample,
no movement or attack orders. All five objectives were already friendly and no
visible attack target was available. All 12 hooks restored after detach. This is
retained as a failed scene condition, not a firing/reload pass.

That scene exposed an avoidable diagnostic limitation. Combat approach now allows
normal policy defense of existing friendly objectives when every objective is
friendly, using their validated locations. Pure capture trials retain their
nonfriendly-objective guard. The runner remembers whether a chosen target was
already friendly and cannot report defending it as a capture. A new scenario test
checks friendly-objective movement and absence of false capture attribution;
existing capture-proximity tests still pass. This fallback awaits a live repeat.
All 263 tests pass, including 137 native bridge fixture cases
(`tactical_full_suite_20260907_reload_observation.log`). Live reload completion,
settled aim and readiness capability remain unverified/disabled.

## Moving-observer admission rejection during combat approach

Normal completion recovery saved the prior match; fresh bot start
`run_20260907_063748_207189` passed. Rifle purchase
`tactical_scenario_20260907_103838_358015` created squad 25-36, and unit 26 was
enabled in `103847_616908`.

Repeat approach `tactical_scenario_20260907_103848_296047` reached the central map,
recorded 256 combat queries and two attributed native bullet constructions, and
observed ammo counts 8, 7 and 6. No active-loading observation or explicit native
attack submission occurred. Its fourteenth movement attempt was explicitly
rejected by native admission because the requested destination exceeded the
600-world-unit bound at callback time. The snapshot used to plan that leg and
the later admission callback observe a moving soldier at different positions.
The bridge refused the request correctly; the diagnostic incorrectly classified
that known refusal as an uncertain command and aborted. The raw failure and all
12 successful detach checks remain saved unchanged.

Objective/combat trials now return a known-unexecuted cancellation for explicit
native rejection, matching production adapter semantics. The runtime can replan
from its next snapshot without retrying the old intent or applying a route-failure
penalty. Unknown acknowledgements still abort without replay. A focused test
verifies both branches, increasing sequence numbers and a newly planned destination
after the observation changes. All 264 tests pass
(`tactical_full_suite_20260907_admission_recovery.log`).

Immediate live retry `tactical_scenario_20260907_104249_684781` refused unit 26:
its baseline confirmed native death, with the match still active. No new command
was issued and hooks restored. This refusal does not demonstrate live cancellation
recovery, nor did either run establish reload completion. A different supported
combat setup is needed for the next loading measurement; repeating an isolated
rifle approach is not sufficient evidence of useful firing behavior.

## Friendly native reload cycles observed without issuing orders

A diagnostic-only `friendly_reload_watch` scenario observes existing local/allied
infantry through native ammo start (`0x845050`), update (`0x844650`) and finish
(`0x8454c0`) callbacks. It never invokes native functions or issues orders to
friendly bots. The helper checks the tracked actor/weapon/ammo relationship,
incarnation, native death predicate, verified owner relation, supported component
vtables and bounded counts. No enemy positions or weapon observations are exported.
Unmatched finish events cannot establish a completed cycle, and changed identities
cannot complete an earlier cycle. At most 128 cycles are retained, stale records
expire after 60 simulation seconds, and progress samples are limited to one per
cycle per simulation second. The outer run lasts at most 60 wall-clock seconds.

`tactical_scenario_20260907_104829_456012` passed its initial start/end contract:
owner-3 allied infantry 107 and 97 each completed a six-second, eight-round cycle.
Unit 107 increased from one round to eight using seven pending rounds; unit 97
increased from zero to eight using eight pending rounds. An end event for unit 82
had no observed start and was not counted. Zero orders; 14 hook sites restored.

The stronger repeat `tactical_scenario_20260907_105009_386907` also samples the
active runtime flag between start and finish. It recorded 27 active-loading
samples and four completed cycles. Units 92 and 94 each loaded eight rounds from
zero over exactly 6000 simulation milliseconds. Unit 86 went from one to fifteen
rounds in 4500 ms; unit 95 loaded one round in 11400 ms. The pass threshold was two
eight-round cycles with observed active loading, cleared loading/pending state at
finish, increased ammunition and positive elapsed simulation time. It does not
infer a shared duration for other weapons. Zero orders; all 15 hooks restored.
Extracted evidence: `validation/tactical_friendly_reload_cycles_20260907.json`.

The native-memory harness verifies a matching cycle and intermediate loading,
enemy filtering and invalidated identity; the scenario test rejects a pass without
intermediate loading or two matching clip sizes. All 266 tests pass
(`tactical_full_suite_20260907_reload_cycles.log`), including the 137-case production
bridge harness and 140-case combined diagnostic harness. The result summarizer
preserves these cycle details and their exact source hashes.

This validates the mapped loading flag and actual ammunition transfer on friendly
bot infantry. It does not establish settled aim, hits, accuracy improvements,
independent-client replication or policy readiness integration. General weapon
readiness and tactical action gates remain disabled; simulationClock remains enabled.

## Verified ammunition/loading observations integrated with policy

The bridge now exposes a narrowly scoped `ammoLoading` capability, separate from
the still-disabled general `weaponReadiness` capability. Supported enrolled owned
infantry receive an ammunition observation containing the current simulation tick,
round count and active native loading flag. Unsupported or unequipped weapons
remain unknown. The existing weapon-query decoder is shared; the snapshot path
returns before reading unneeded aim/fire components and makes no native calls.
Owner mismatches and invalid counts still fault rather than silently invent data.

The adapter accepts only exact enabled capability, current-snapshot timestamps,
bounded integer ammunition and a boolean loading flag. Active loading maps to
policy readiness `reloading`; loading false maps to `unknown`, never `ready`.
Thus the verified reload guard can defer ordinary movement/stance changes without
claiming settled aim or enabling alternating covering fire. The objective/combat
scenario uses the same normalization, so it no longer discards this native state.

Two adapter tests cover real snapshot-to-policy reload preservation, subsequent
progress, missing capability, unknown equipment and stale/malformed observations.
Bridge fixtures exercise ammunition-only snapshots independently of unsupported
fire components. A scenario test confirms that an objective order waits during
native loading and is issued only after loading clears. All 269 tests pass
(`tactical_full_suite_20260907_ammo_integration.log`).

Normal bot start `run_20260907_065652_382424` followed completed-match recovery.
Purchase `tactical_scenario_20260907_105754_560320` created squad 38-49; unit 39 was
enabled in `105804_728243`. Live observation `tactical_20260907_105805_404095`
completed eight snapshots with zero orders. Soldier 39 reported eight rounds,
loading false, current tick 26604; replay through the actual adapter retained
ammo 8 and readiness `unknown`. Read-only weapon query
`tactical_scenario_20260907_105900_878272` also succeeded with eight rounds and all
12 hooks restored after detach. The live active-loading semantics are established
by the preceding friendly-bot cycle trials; interruption prevention remains tested
in fixtures rather than claimed as a matched live combat improvement.

## Placement/aim mapping and desktop recheck

Normal gameplay input remains unavailable. Although `OpenInputDesktop` reported
Default, the foreground window was `Windows Default Lock Screen` and the game
could not receive focus. No key or mouse input was sent; the game was minimized
again. No OS authentication boundary was bypassed. Manual handoff therefore remains
an open live gate; the previously disabled player-emission helper stays disabled.

Read-only mapping identified placement base routine `0x851330`, invoked by the
known placement virtual method and overrides `0x855400`, `0x855710`, `0x855280`.
The base routine sets placement `+0x54` while an alignment threshold is satisfied
but the simulation deadline at `+4` is still pending. However, some early returns
precede clearing that byte, so its raw value alone is not established aim readiness.
Return values also distinguish multiple placement outcomes. Mapping files:
`weapon_placement_readiness.txt`, `accuracy_sources.txt`, `placement_update_caller.txt`
in `validation/tactical_mapping_20260907`. No spread or damage fields were changed.

Diagnostic-only `friendly_aim_watch` reuses the validated friendly ammo/identity
filter and records raw placement return, wait byte, deadline, concrete component
type and native code caller. It accepts only the mapped virtual method/overrides,
requires the weapon's current placement back-pointer and unchanged identity, and
limits records to transitions or one per simulation second per identity. Its
identity map is bounded to 128 and the existing event/time budgets still apply.
The raw records do not promote policy aim readiness or claim accuracy benefits.

Initial live trial `tactical_scenario_20260907_110641_245969` ran to its observation
deadline with reload activity but zero placement records under a narrower concrete
type filter. All 16 hook sites restored. The filter was then broadened to the mapped
base method and three overrides. Repeat `tactical_scenario_20260907_110818_761350`
refused the now-completed match before observation; all hooks restored. The current
filter still needs a live repeat in an active scene. The earlier timeout summary's
loading-cycle wording is retained as historical output; current aim timeouts state
insufficient placement observations.

Three combined native-memory cases verify raw placement fields, an unsupported
method and invalidated identity, all with zero orders. All 269 tests pass
(`tactical_full_suite_20260907_placement_probe.log`), including the 137-case production
bridge harness and 143-case combined friendly diagnostic harness. The report now
retains placement sample counts and raw state distributions without calling them
a readiness pass.

## Live aimer dispatch and shooter correlation mapping

Fresh bot match `run_20260907_071239_424676` used normal completed-match recovery.
The initial observation `tactical_scenario_20260907_111343_324929` collected 275
samples without combat/reload or placement events; all 16 hook sites restored.
Later observation `tactical_scenario_20260907_111909_653202` captured 450 placement
results: 115 code 5, 197 code 3, 121 code 4, 15 code 7 and two code 6. The raw wait
byte remained zero. Four complete friendly reload cycles included 8-, 20- and
30-round weapons. The full retained stream, including the final match-completion
snapshot, contains 455 results from 16 identities: 440 from type `0xdf59f4` through
caller `0x8411ea`, and 15 from type `0xdf5ad4` through override caller `0x855443`.
Four code-3 results occurred while native loading was true, demonstrating that
prepare success alone cannot mean loaded/ready. These counts are saved in
`tactical_aimer_dispatch_observations_20260907.json`.
The match completed during the trial, so its result remains failed for
lost match continuity, despite useful mapping evidence. Zero orders were issued;
all 16 hook sites restored. No aim/readiness capability was promoted.

`aimer_live_dispatch.txt` maps the caller to weaponry update `0x841010`: it stores
the virtual prepare result at aimer `+0xc`, then invokes the shooter update.
`shooter_aim_state.txt` and `shooter_state_transitions.txt` trace the supported
`0xdf57b4` shooter. Its firing routine `0x84d8a0` increments the cumulative count
at `+8`, decrements remaining burst count at `+0x10`, and calls the per-shot ammo
routine. The active byte at `+0xc` can persist during loading, so it alone is not
proof of a current shot. Earlier candidates in `aimer_state_dispatch.txt` were
unrelated helper constructors, not the aimer state dispatcher.

The diagnostic now records pre-call aimer state and supported shooter count,
active byte and burst remainder. These are explicitly raw preceding-work samples:
the caller's state store and shooter update happen after the prepare hook returns.
Unknown shooter types yield null counters. Reload metadata also records aimer
type, allowing the filter to be checked independently of prepare callbacks.
All 269 tests pass (`tactical_full_suite_20260907_aim_counters.log`); the newly added
shooter counter fields still require a live repeat.

Normal follow-up match `run_20260907_072251_807592` loaded after finish/save runs
`072157_964848` and `072211_551595`. Counter observations
`tactical_scenario_20260907_112349_051464` and `112504_879193` each reached their
bounded deadline without placement events during the early match. Both issued
zero orders and restored all 16 hook sites; they do not validate the new counters.
The combined fixture verifies the mapped raw counters and preceding aimer state;
all 269 tests still pass. `aimer_dispatch_abi.txt` preserves the caller assembly:
the shooter receives its activation boolean only after the aimer result is stored
and an additional aimer predicate is checked. The base-hook result for override
type `0xdf5ad4` is intermediate, not the override's final return.

## Live shooter counters and component replacement guard

Observation `tactical_scenario_20260907_112644_756813` captured 224 placement
results in the active bot match: 124 code 3, 81 code 4, 16 code 5 and three code 7.
There were 21 increases in the supported shooter's cumulative counter; 18 sampled
intervals matched the decrease in ammunition exactly while loading was false at
both endpoints. These are sampled correlations, not independent projectile/hit
attribution or a controlled weapon-switch trial. Six samples retained shooter
active byte 1 while native loading was true. Consequently neither that byte nor
prepare success is promoted to policy readiness. The bounded observation ended
normally with zero orders and all 16 hooks restored. Extracted intervals are in
`tactical_shooter_counter_observations_20260907.json`.

The aim diagnostic now revalidates the weapon/aimer links and concrete type after
the native call, in addition to the existing unit identity checks. A component
replaced within the call cannot produce a stale observation. The fixture exercises
replacement while preserving the soldier identity, alongside invalidated identity
and unsupported method cases. All 269 tests pass, with 137 production and 144
combined diagnostic memory cases (`tactical_full_suite_20260907_aimer_lifecycle.log`).
The weapon-query interpretation was corrected to acknowledge validated ammo/loading
while continuing to label settled aim and firing readiness unverified.

Live repeat `tactical_scenario_20260907_112905_044417` exercised the updated guard
with 517 placement observations (234 code 3, 218 code 4, 51 code 5, nine code 7,
five code 6). It completed its observation window normally, issued zero orders,
and restored all 16 hooks. No nonzero wait-byte sample was observed. This confirms
normal observation still works after the guard; the within-call replacement case
is fixture evidence, not a claimed live replacement event.

## Native cover assessment mapping

Read-only mapping traced the existing cover query `0x8a65f0` through request
initialization `0x8a6900`, candidate collection `0x8a6a50`, and assessment
`0x8a75a0`. The outer query selects by distance after assessment; finding a
candidate therefore does not establish that it scored well. Candidate admission
`0x8a72b0` includes point obstruction and nearby occupancy checks (`0x8a9f30`),
not by itself a demonstrated route from the actor.

The assessment does contain native path and threat components. `0x8a7d80` consults
a navigation cache, assigns an invalid-cost sentinel, then normalizes/clamps the
result into candidate `+0x58`. Zero is consequently not a unique unreachable
marker. `0x8a8a80` sources threat records from the actor's sensor vector `+0x34`,
filtered by raw flags `0x402` and `0x10`; their suitability for the policy's
visibility contract remains unverified. Later code combines components through
`+0x78` into the total score at `+0x7c`. These are not yet independently validated
protection, firing access or escape-route measures.

The bounded `cover_query` now exports `nativeAssessment`: raw cover type, flags
at `+0x4c`, and ten finite float values in offset order `+0x58..+0x7c`. This adds no
native calls and does not change selection or policy capability gates. Missing
cover produces null assessment. Existing normalized quality fields remain null.
All 269 tests pass (`tactical_full_suite_20260907_cover_assessment.log`). Mapping
files in `tactical_mapping_20260907` include `cover_candidate_selection.txt`,
`cover_candidate_filters.txt`, `cover_candidate_admission.txt`, `cover_geometry.txt`,
`cover_type_definitions.txt`, `cover_stance_tables.txt`, `cover_suitability_score.txt`
and `cover_threat_sources.txt`.

Purchase `tactical_scenario_20260907_113634_545328` created owned squad 133-144 in
the existing active bot match. Read-only queries `113655_588524` at unit 134's
spawn and `113729_758792` at a previously recorded nearby cover location both
returned no candidates, correctly yielding null assessments; all 12 hooks restored.
Inventory query `113750_458502` confirmed one available construction item for 134.

Construction `tactical_scenario_20260907_113808_904335` submitted one build order,
consumed one kit, and observed creation of `sandbag3` entity 59520 with native
cover candidates associated with that entity. It completed in 34.001 simulation
seconds. The initial assessment output exposed a further mapping constraint:
assembly at `0x8a6674` passes request `+0x68` to `0x8aa290(0)`, clearing all eight
scoring weights before the query. Thus this convenience API disables useful
scoring even though it invokes the assessment pipeline. A general native request
with meaningful weights must be observed/validated before using these components
for policy ranking; zeros and default ones here are not quality measurements.

`cover_assessment_initialization.txt` also establishes that only the low five
bits of candidate `+0x4c` are initialized. The query now masks to `0x1f` and
explicitly exports `scoringEnabled: false`. Historical build observations retain
the earlier full raw word; its high bits have no supported interpretation.
Corrected live query `tactical_scenario_20260907_114019_898827` returned three
candidates on entity 59520, type 5, flags 0, scoring disabled and finite default
components. It issued no orders and restored all 12 hook sites. All 269 tests
pass after the correction; no cover capability or quality field was promoted.

## Engine-generated cover assessment observer

Diagnostic `friendly_cover_watch` observes `0x8a75a0` requests generated by normal
gameplay. It neither invokes the request API nor changes its weights. Current
registry identity, ownership/friendly relation and non-death are checked before
and after the call. Records contain weights, caller, total candidate count and
at most eight raw candidate assessments, with no actor pointers or enemy positions.
Sampling is limited to once per two simulation seconds per identity, with 128
identities, validated vector size/alignment and the existing event/evidence bounds.
The 60-second scenario records observations only; even ten weighted samples are
not a suitability acceptance pass. The result summarizer preserves these counts.

Four additional native-memory fixture cases cover ordinary weighted output,
foreign ownership, identity invalidation during the call and oversized vectors.
All 269 tests pass, including 137 production and 148 combined diagnostic cases
(`tactical_full_suite_20260907_native_cover_watch.log`). First live attempt
`tactical_scenario_20260907_114345_525801` refused the completed match and restored
all 13 hook sites. Active-game assessment observations remain outstanding.

Normal completion/save/start runs `074419_974988`, `074451_516455` and
`074522_600308` prepared the next bot match. First active observation
`tactical_scenario_20260907_114619_078784` completed 274 snapshots without cover
events. Follow-up `114728_715211` captured ten weighted requests from two friendly
identities: two through caller `0x8a6ddb` with weights `[10,10,10,5,0,5,0,0]`, and
eight through `0x8a724a` with `[0,0,10,0,0,0,0,0]`. Sampled candidate types were 6
and 3; scores included 10, 23.3885, 23.9618 and 26.0821. Both trials issued zero
orders and restored all 13 hooks. The observer retains the first eight candidates
before native sorting, not the best eight. Aggregation is saved in
`tactical_native_cover_assessments_20260907.json`. This validates weighted-request
observation, not protection, reachability or firing-access semantics. Mapping
`native_cover_request_callers.txt` identifies the normal request call sites;
`cover_convenience_weights_abi.txt` preserves the convenience API's weight reset.

## Native scored cover query lifecycle

`scored_cover_request_lifetime.txt` and `scored_cover_request_abi.txt` map the
native request constructor `0x8a68a0` (thiscall, actor/point/float radius, `ret 0xc`),
query `0x8a6a50`, and destructor `0x513b80`. Native callers pair this constructor
and destructor; the destructor frees its internally allocated candidate vector
through `0x513c90` and does not free the enclosing request storage.

Diagnostic `cover_scored_query` uses that lifecycle on the existing validated
game callback, retaining default weights. It makes one radius-60 query at a
center within the existing 600-world-unit bound, returns at most eight candidates
plus total count, and validates vector bounds, finite values and source identities.
The native destructor runs in `finally`, including rejected/malformed output and
query errors. No scored fields become policy protection/reachability/firing access.
Four fixture cases verify empty/populated results and cleanup after invalid output
or query failure. All 269 tests pass, with 141 production and 152 combined native
memory cases (`tactical_full_suite_20260907_scored_cover_query.log`).

Purchase `tactical_scenario_20260907_115252_909430` created a new owned squad in the
active bot match. Live query `115310_642783` on soldier 146 returned default weights
`[10,10,10,5,0,5,0,0]` and no candidates at spawn, with all 12 hooks restored. A
populated-vector live query remains to be completed.

Construction `tactical_scenario_20260907_115335_951934` created sandbag entity
53216 and consumed one kit. Populated scored query `115457_312741` returned ten
candidates, retaining eight, in one millisecond. Scores were 21.2987 on one side
and 20.1402 on the other, with differing native path-score components. The bridge
now also verifies that the native destructor cleared all three vector pointers
and reports `requestVectorReleased: true` only after that check. This is an
observed lifecycle check, not a general heap-leak measurement. All 12 hook sites
restored and the query issued no orders.

Diagnostic `scored_cover` selects from that native query, reuses existing source
identity/slot revalidation for the ordinary cover command, verifies actual native
cover arrival, and returns the soldier to its original position. Live case
`tactical_scenario_20260907_115611_829886` passed on soldier 146 and entity 53216;
the selected score was 21.2987. Actual cover state and subsequent return were
observed with continuing simulation ticks, and all hooks restored. This is one
local route/arrival case; it does not validate protection from a threat, firing
access, alternate blocked routes, or multiplayer replication. All 269 tests pass
after the query/cleanup integration (`tactical_full_suite_20260907_scored_cover_query.log`).

## Scored-query admission and assessment context

The scored query now explicitly requires the supported manager's active-match
state before constructing a native request. A fifth lifecycle fixture confirms
completed-match rejection with no constructor, query, destructor or order call.
Live repeat `tactical_scenario_20260907_120212_516049` encountered the completed
match and returned that known admission rejection, rather than querying stale
match navigation state. This does not invalidate the earlier active-match result.

`cover_detector_semantics.txt` extends the mapping of `0x8a8020`: it evaluates
candidate positions using detectors associated with the threat records. This is
not a demonstrated outgoing-fire predicate for the controlled soldier. Raw
candidate flags and composite scores remain unsuitable as direct policy firing
access booleans.

Scored queries and the passive native observer now include `inputRecordCountRaw`
and `hasTargetRecordRaw`. The count mirrors only `0x8a8a80`'s bounded sensor-vector
filter (`+0x34`, flags `0x402`, excluding `0x10`, non-null subject); it does not
claim current visibility or enemy classification. Unknown sensor types produce
null counts. No sensor positions or actor pointers are exported. This context
will distinguish default scores in a no-input scene from assessments with native
threat inputs. The count filter is tested with included and excluded records;
active-scene validation of these new context fields remains outstanding.
All 269 tests pass, including 142 production and 153 combined native-memory cases
(`tactical_full_suite_20260907_cover_context.log`).

## Construction direction support

The native barricade packet previously used a fixed secondary endpoint one world
unit along +X. It now accepts an optional two-component `buildDirection`, rejects
nonfinite/zero vectors and unrelated actions, and normalizes it to a one-unit
segment before serialization. The default remains +X; destination and kit guards
are unchanged. The scenario CLI exposes `--direction DX DY` for barricade trials
and retains requested and normalized directions in configuration/submission
evidence. This supports testing defense orientation without editing entity transforms.

Five added bridge cases exercise vertical/diagonal normalization, zero/nonfinite
rejection and use on an unrelated action. All 269 tests pass, with 147 production
and 158 combined native-memory cases (`tactical_full_suite_20260907_build_direction.log`).
Actual rotation remains to be checked live before claiming support for oriented
physical defenses. `entity_orientation.txt` maps the rotation-matrix helper for
reference; the bridge does not invoke it or directly rotate constructed objects.

## Disk-full interruption during direction validation

Normal finish/save runs `080619_144825` and `080700_090637` succeeded.
Start `080754_887061` failed before issuing a game command because C: was full.
The process remained alive. Live direction validation is outstanding.

An attempted in-place lossless compression failed and truncated raw observations
in `tactical_scenario_20260907_092139_052528/observations.jsonl`. Its summary is
retained and explicitly marked `evidenceLoss`; that trial no longer has complete
raw evidence. This was an agent error, not a successful archive operation.
The auxiliary mapping log `implementation_commands.log` was successfully gzip
compressed and verified at `implementation_commands.log.gz`.

A full copy of `validation/stability_20260905_225058` now exists at
`validation/local_archive/stability_20260905_225058`; all 16 files,
totaling 3,710,305,782 bytes, were SHA-256 verified. Its adjacent manifest records
all hashes. Automatic approval review rejected replacing the original directory
with a junction to that verified archive; the stated reason was only blocked by
policy. That replacement did not execute: the original directory remains intact.
NTFS compression did not recover space. No other source data was deleted.


## Live construction orientation validation

New evidence is written to `validation/local_archive/new_runs`
through the scenario `--output` and host `--evidence-root` options. Python
TEMP/TMP also point to D:. Original validation directories remain intact.
The result summarizer excludes empty or explicitly lost evidence from complete
passes. All 270 offline tests passed after these storage/report changes; see
`validation/local_archive/tactical_full_suite_20260907_evidence_storage.log`.

Fresh PID 14984 loaded the controlled two-bot match successfully in host run
`082611_744539`. Purchase `083127_786798` supplied eligible owned infantry.
Vertical build `083147_222909` used soldier 114 and direction [0,1]; horizontal
comparison `083313_115997` used soldier 118 and direction [1,0]. Both completed,
consumed exactly one combined inventory kit, and produced source-identified native
cover (entities 35235 and 47328 respectively). Vertical completion took 34.58
simulation seconds. Read-only current-registry resolution verified both IDs and
entity flags before reading their final matrices. The vertical matrix equals a
90-degree Z rotation within 4.38e-8; the horizontal matrix is identity. The layout
matches the mapped native rotation helper. No entity transform was written.
Raw bytes, expected matrices and source-summary hashes are retained in
`validation/local_archive/construction_direction_comparison_20260907.json`.

Scored-cover trial `083403_977703` passed native cover arrival and return using
soldier 114 at the rotated defense. This establishes local physical orientation,
resource consumption and cover use, not protection quality or independent-client
replication. Production construction/cover gates remain disabled. Full-plan
acceptance, including reclamation, identity lifecycle, autonomous integration and
multiplayer replication, remains incomplete.


## Cover sampling with native input context

Passive live run `validation/local_archive/new_runs/tactical_scenario_20260907_083555_357086`
captured 20 deduplicated assessments, including ten weighted nonempty requests.
One friendly combat subject (97) had 14 raw input records and a target record;
its candidate flags were 28 and its weighted score was zero. Nearby idle subject
118 had no inputs/target and scored ten. This validates the context fields in an
active match and demonstrates why idle default scores cannot establish protection.
Extracted input-bearing evidence and raw-trace hash are retained in
`validation/local_archive/cover_input_context_20260907.json`.

The passive scenario now counts weighted requests with inputs and target records
separately, and stops early only after ten weighted nonempty requests with inputs.
The existing 60-second and 2048-event bounds remain. Unknown or boolean input counts
do not qualify, repeated event keys do not inflate counters, and the result stays
`observed`; no quality capability is enabled. The result summarizer preserves both
new counts. A regression checks idle, unknown, boolean and actual input counts.
All 271 tests pass (`validation/local_archive/tactical_full_suite_20260907_cover_sampling.log`).

Follow-up `083830_687672` was refused because the match was no longer active;
all 13 hook sites were restored. Collection under the revised stopping rule still
needs an active combat run. Native protection/firing access and runtime cover
integration remain incomplete; no raw score is substituted for those predicates.
