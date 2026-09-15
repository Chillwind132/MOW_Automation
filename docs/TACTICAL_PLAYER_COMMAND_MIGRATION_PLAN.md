# Plan: tactical AI through ordinary player commands

September 7, 2026. User-selected architecture; implementation and multiplayer
validation pending. This plan governs tactical integration and supersedes earlier
proposals to call native AI/cover/pathfinding routines or edit brain properties
locally. The [original tactical plan](TACTICAL_AI_IMPLEMENTATION_PLAN.md) remains
the behavior specification; the [audit](TACTICAL_SYNC_AUDIT.md) records current risks.

## Objective and architecture

Migrate the entire current tactical controller to behave as the local player,
including when joining another person's host. Preserve autonomous goals, spacing,
retreat, support, target commitment, AT response, purchasing and manual reclamation.
Retain cover and construction as requirements, with individual capability gates
until their replacement paths pass validation. No camera, selection, screen
coordinates or input focus dependency; no LLM in the real-time decision loop.

The intended flow is:

1. Read verified owned-unit and team-visible observations into bounded snapshots.
2. Run tactical decisions, memory, reservations and scoring outside native simulation.
3. Submit a validated ordinary player order or purchase request through the game's
   existing command interface and transport.
4. Let normal native execution perform navigation, cover occupation, firing,
   reloading, inventory consumption, spawning and construction on participants.
5. Observe acceptance, execution and completion separately; compare independent
   clients to validate synchronization.

The AI's private decisions need not be shared or reproduced by other clients.
Only ordinary game commands cross the engine boundary. Being host is not an
exemption from replicated execution. Other players should not need our AI code
or an altered protocol; diagnostic observers may be installed on controlled test
clients to collect evidence. Final trials must also cover an unmodified peer.

"Sync safe" is an acceptance target, not a guarantee derived from an API name,
serialization return, clean local match, or passing mocks.

## Phase 1: freeze the boundary and inventory all entry points

Deliver one inventory of every native call, hook, engine-memory write and action
reachable from `tactical_bridge.js`, `tactical_controller.py`, `BotSupply` and the
scenario extensions. Label each as observation, ordinary command, prohibited
extra simulation work, or unresolved. Include constructors, destructors and
availability checks, not just functions named query.

Allow only verified observation operations and individually admitted player
command paths in multiplayer. Remove live cover/path search dependencies from
that profile, including cover's hidden re-query during submission. Unvalidated
actions remain disabled at the bridge as well as the Python adapter. Diagnostic
overrides must not silently enable them in a multiplayer match.

Preserve executable/identity/ownership/revision checks and record-only behavior.
No health, ammo, position, squad-membership, retreat-property or RNG edits. No
checksum forgery, suppressed sync checks, or native state save/restore trick.
Optional RE experiments remain separate from normal multiplayer execution.

Pass: every reachable native boundary is classified; negative tests demonstrate
that blocked paths cannot invoke native functions even through direct RPC calls.

## Phase 2: map actual player commands on host and joining client

Trace an ordinary manual move, stance, mode and attack on each role. Then map
purchase, cover and construction separately. Capture command creation, flags,
actor/entity/action IDs, values, queueing, transport, receiver decoding, execution,
native buffer ownership and thread/lock requirements. Verify singleton leader
expansion and paired-recipient behavior.

Use the highest suitable selection-independent ordinary command entry point.
Retain the current `0xaa9b20` route only where trace evidence establishes that
our constructed payload and lifecycle match normal player submission. Purchases
may legitimately use their separate native session request path.

The existing `asPlayerCommand` experiment is disabled after a native command-stream
failure. This architecture does NOT authorize simply re-enabling that flag or
replaying the failed helper. Establish the correct entry independently.

Replace host-only diagnostic assumptions with validated local-player identity
and ownership admission for joining clients only after tracing that role. Do not
weaken ownership, roster-generation or stale-command guards to accomplish this.

Pass: a small bounded command produces the expected native execution and matching
results on the independent peer for each admitted action and role. No feature
inherits validation solely because another action uses the same serializer.

## Phase 3: migrate all existing behavior

| Current behavior | Replacement and retained requirements |
| --- | --- |
| Observation, contacts, ammunition, deaths | Copy verified existing fields/events; retain visibility, freshness, incarnation and ownership checks. Avoid getters with unverified native side effects. |
| Goals, spacing, reserves, threat memory, force estimates, target commitment | Keep pure Python policy and local caches. Preserve bounded work and simulation-time semantics. |
| Ordinary movement and leader following | Use admitted player move commands with exact recipient scope. Let the engine navigate; observe displacement, arrival and stalls. |
| Retreat, friendly support, AT reposition, supported advance | Remove extra `path_query`. Use bounded external candidate selection and ordinary move attempts, with failure/backoff. Until this replacement passes, withhold the affected behavior; do not label routes reachable without evidence. |
| Cover choice and occupation | Obtain candidates by passively observing engine-generated results or extracting map geometry. Score externally; invalidate destroyed/reused sources and occupied/stale slots. Submit an independently validated ordinary cover order without a local native search. A move near a wall is not proof of occupation/protection. |
| Attack/AT and fire discipline | Preserve personal visibility, supported weapon/ammo checks and native firing/reload observation. Submit ordinary attack commands. No direct fire, reload, ammo-switch, damage or weapon-stat calls. |
| Move-at-will/hold, stance, manual takeover | Use ordinary mode/stance commands; preserve explicit re-enrollment, squad scope, deselection behavior, direct-control suspension and cancellation before dispatch. |
| Purchasing and recruit adoption | Keep external composition planning. Map the standard player purchase request and its prerequisites; replace unnecessary native polling with verified observations. Audit unavoidable availability calls independently. Observe spending and actual spawns; no speculative retries. |
| Construction and grenade/smoke diagnostics | Keep unsupported actions off. Map ordinary player commands and observe placement, inventory/resource consumption, cancellation and results before enabling. Do not call native installation/throw executors directly. |
| Stop, timeout, match end and host integration | Expire pending work, detach cleanly, preserve native orders already accepted. A timeout is uncertain, never permission to replay. Keep lobby/maintenance work outside active tactical simulation. |

Prefer passive cover results first; add an external map index if coverage is
insufficient. Treat extracted static geometry as candidate data, not proof of
current protection or reachability. A pure external evaluator is an optional
later extension. Do not execute queries against shallow copies whose pointers
still reference the live engine.

Implement incrementally in the existing modules, preserving the policy interface
where useful. Add one command-boundary module only if it materially improves
enforcement. Do not duplicate the controller or rewrite working tactical policy.

Pass: every current behavior has a migrated implementation and evidence, or an
explicit unresolved capability gate. Temporarily disabled features are unfinished,
not removed from the overall objective.

## Phase 4: automated tests for the boundary

Extend `tests/tactical_bridge_harness.js` and the existing tactical test modules.

| Test layer | Required checks | What it establishes |
| --- | --- | --- |
| Native-call boundary | Mock native calls behind a deny-by-default registry. Run complete observation, policy, submission and supply cycles; fail unexpected calls. Explicitly attempt all forbidden cover/path RPCs in host and client profiles. | The tested paths cannot quietly reintroduce prohibited engine calls. |
| Memory and hooks | Track bridge-owned allocations; reject writes outside them in fixture runs. Reject native return-value/argument/context edits except explicitly reviewed command integration. Do not count normal fixture setup or native execution writes as bridge writes. | Direct gameplay-state edits are caught in the tested bridge code. |
| Commands | Compare payload fields and decoded meaning with saved ordinary-player traces. Normalize process-local pointers, IDs/times only where the contract permits. Check target resolution, owner, recipients, flags and buffer lifetime. | Command contract fidelity; not network execution. |
| Lifecycle/failure | Stale generation, reused IDs, ownership transfer, manual takeover, pause, duplicate sequence, expired queue, lost acknowledgement, uncertain timeout, stop and new match. Assert zero unauthorized/duplicate dispatches. | Correct admission and bounded failure handling. |
| Policy preservation | Existing retreat, dispersion, target commitment, AT, supply and cover-lease scenarios plus replacement route-failure cases. | The migration preserves tactical intent. |
| Monitoring | Old/partial/missing/replaced/truncated logs, explicit desync, stalled ticks and missing remote evidence. Fail/inconclusive results must never become synchronization passes. | Honest test verdicts and stop behavior. |
| Scale | Existing 128/256/512/1024-unit fixtures; measure observation/decision/submission budgets and fair concurrent service. | Offline scale bounds only. |

Use source/AST checks as supplemental guardrails for new native bindings or engine
writes; a regex or mocked allowlist is not proof about native callees. Do not
create tests that merely assert implementation text without testing behavior.

Pass: all relevant existing tests plus the new negative/contract tests pass;
native side effects and network agreement remain explicitly unverified at this layer.

## Phase 5: independent-client synchronization harness

Extend the existing scenario runner and sync monitor rather than building a second
framework. Run one AI controller, with at least one independent game client. Test
both AI-as-host and, as a required release condition, AI-as-joining-client.

Each trial records executable and loaded mod/map/settings identities, source hashes,
roster, action profile, simulation timestamps, command evidence, resource outcomes
and synchronized native checks. Correlate states at the same simulation quant;
never compare arbitrary wall-clock snapshots. Process pointers and UI/camera state
must not enter semantic comparisons. If matching-quant evidence cannot be acquired,
report the comparison unavailable rather than infer agreement.

Capture positions/orders, ownership, deaths, ammunition where applicable, purchase
cost/spawns and construction entities/inventory. Validate what the native checksum
fields represent before naming them; capture both regardless. Positive repeated
agreement is required; absence of an error log is insufficient. A coarse selection
of matching entities alone cannot certify complete engine agreement.

For controlled sync trials, a detected desync stops new actions and preserves
evidence. Missing/unassociated monitoring or lost required peer evidence stops
new trial actions and yields inconclusive. Already accepted native orders cannot
be undone by stopping Python. Record any in-flight uncertainty, do not replay.

Start with uninstrumented and observation-only baselines. Add ordinary moves,
stance/mode, purchase observation/submission, attack, replacement retreat/support,
cover and construction individually; then test combined behavior. Include empty
cover results, blocked routes, combat, destruction, death/ownership changes,
manual reclamation, purchases and match transitions. Use controlled peers, not
an unrelated public match. Keep host maintenance and other injectors out of the
baseline; test the intended recorder combination separately afterward.

Minimum initial acceptance: three fresh successful runs per action family per
supported role, each spanning execution/completion and repeated native agreement
checks; then three complete mixed-feature matches per role. Repeat at the highest
practical native population and record the measured limit. These are minimum
evidence gates, not a statistical guarantee. Unsupported 1024-unit native load
must not inherit the offline scale result. Expand repetition when evidence warrants.

Pass: zero observed checksum or semantic-state divergence, zero wrong-owner/stale
or duplicate orders, completed required effects and complete monitoring evidence.
A missing second client leaves multiplayer validation pending; continue useful
offline work without claiming the release gate passed.

## Phase 6: release and persistent handoff

Promote capabilities independently for the tested executable/mod configuration,
host/client role and feature set. Unknown builds or changed data invalidate the
relevant admission evidence. Keep observation-only available on failed admission.
Do not globally flip `synchronization: true` based on one movement trial or bypass
production gates with battle diagnostic overrides.

Update current status, operating commands and the original plan to distinguish
migrated, locally tested, independently validated and still disabled features.
Each future session should read the root `AGENTS.md` reminder and this plan before
changing tactical/native code, then continue at the first incomplete gate using
existing evidence. Preserve the user-selected player-command architecture.

Completion means every current enabled AI behavior uses this boundary, joining
client operation is validated, all required offline and multiplayer gates pass,
and remaining unsupported planned features are clearly reported. Until then,
describe the build as designed for synchronization safety, not proven sync safe.
