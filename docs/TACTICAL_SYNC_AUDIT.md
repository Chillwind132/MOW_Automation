# Tactical synchronization audit

September 7, 2026. Static audit of the current checkout and the saved first
human-opponent run. No game was launched or attached; no runtime behavior changed.
This identifies exposure and validation gaps, not additional proven desync causes.

## Scope and result

Reviewed `headless/tactical_bridge.js`, `tactical_controller.py`, tactical policy
and operations integration, `diagnostics/tactical_scenarios.py`, the companion
`headless/headless_host.js` mutation/observation boundary, saved native mapping,
and synchronization tests. Optional diagnostic scripts are distinguished from
what `bot_battle --human-opponents` actually loads. Archived implementations and
the complete transitive native engine call graph are outside this audit.

The main additional exposure is explicit native pathfinding before some moves.
Purchasing takes a separate native session-request path and needs independent
validation. Current normal observations and tactical decisions do not directly
patch soldiers, ammunition, health, retreat properties or positions.

At process inspection, the only matching Python process was PID 15264 running
`headless_host.py review --serve`; no matching tactical controller was found.
This is a point-in-time observation, not a reconstruction of prior processes.

## Ranked findings

### 1. Extra pathfinding calls remain enabled in human battles

Priority: high for isolation; synchronization side effects unproven.

`tactical_controller.py:521` requests `path_query` for withdrawal, friendly support,
AT firing reposition and supported advance. Ordinary objective movement skips
this preflight. `tactical_scenarios.py:522` grants `pathQuery` to combat trials;
the human-trial adjustment removes native cover, not path queries.

`tactical_bridge.js:304` constructs a descriptor/task and calls native `0x8c3c40`,
then frees its output vector. The native wrapper invokes endpoint adjustment,
navigation setup/evaluation and a virtual task branch. It is not merely reading
an existing route. Correct output cleanup does not prove that every nested call
leaves simulation-relevant engine state unchanged.

Evidence: `validation/tactical_mapping_20260907/native_path_inputs.txt` and
`native_path_request_owner.txt` (function `008c3c40`). The saved mapping does not
complete a write/RNG audit of all its callees.

Recommendation: isolate path preflight from movement in the next controlled
multi-client test. A path-disabled diagnostic must also withhold actions whose
admission requires that proof, or explicitly validate a separate ordinary-move
fallback. Do not silently label an unchecked route reachable.

### 2. Purchases and purchase-availability queries need their own test

Priority: medium; weaker suspect than cover.

`tactical_bridge.js:482` calls `purchaseEntry` and `purchaseAvailable`; `:494`
calls `purchaseNative` at `0xba7c00`. The entry point checks availability again
and forwards to `0xb57e90`. That routine creates native message type `0x2a`,
includes simulation time and purchase fields, and dispatches through the session.
This is positive evidence of the normal request path, not a direct spawn or MP
patch. It is separate from tactical order serializer `0xaa9b20`.

Availability uses service lookup, roster/catalog lookup and resource checks.
Reviewed bodies mostly read state; deeper virtual/helper behavior is not fully
audited. There is no demonstrated purchase-query mutation causing desync.

Evidence: `purchase_ui_path.txt`, `purchase_callers.txt`, `purchase_validation.txt`
and `purchase_resources.txt` in the mapping directory. Prior purchases coexisted
with checksum agreement, but that does not prove all templates and conditions.

Recommendation: test availability-only polling and actual purchases separately,
including squad spawn, expenditure, cooldowns and ownership on both clients.
Keep the existing single-purchase-in-flight and uncertain-outcome/no-replay rules.

### 3. Hand-built serialized orders still require receiver validation

Priority: medium validation risk; no new local-only execution found.

Move, stance, attack, movement mode and barricade orders build temporary command
buffers and call the native serializer (`tactical_bridge.js:642`). Writes to
those Frida-allocated buffers are not direct writes to actor state. The mapped
serializer converts actor/action references to IDs and values.

Attack preflight reads perception and ammunition; it does not call a native
shot, reload or damage routine. Paired leader following sends two real recipients
in one serialized command. It does not edit squad membership. These paths need
tests of recipient scope, receiver reconstruction, execution and outcomes; a
local `serialized` acknowledgement is not remote confirmation.

Construction additionally calls native inventory/availability helpers before
serialization. Grenade inventory diagnostics call those helpers too. Neither
construction nor grenade queries are automatically driven by the ordinary human
battle policy in the audited integration. Their transitive side effects remain
unverified; enabling them requires a separate test. Purposeful grenade throwing
is explicitly unsupported.

### 4. Observation hooks and scheduling are lower-priority exposures

The normal bridge hooks unit lifecycle/ownership, bullets, installation events,
commands, mode changes and executor callbacks. Their callbacks read native state
and update JavaScript bookkeeping; the reviewed event hooks do not replace return
values or write actor properties. Snapshot contacts, ammunition and readiness are
memory reads plus local calculations. Native actions run through queued executor
work under the mapped lock.

Instrumentation still changes machine code at hook sites and adds work inside
native callbacks. Hook/ABI defects could damage execution; observation overhead
can cause stalls. Neither possibility establishes a desync here. Wall-clock
policy scheduling alone need not be identical across clients when only one
controller chooses and submits normal synchronized commands.

The path, reload, aim, pause and native-cover observer extensions are selected by
specific diagnostic scenarios; they are not all loaded in `bot_battle`. The
human battle loads the normal bridge plus `BOT_TRIAL_JS`. That extension validates
the roster and changes local enrollment/capability bookkeeping, not native modes
directly. Mode changes still use serialized orders.

Recommendation: establish an instrumented observation-only baseline, then add
native action families individually. Avoid concurrent experimental injectors in
the baseline so hook interactions do not confound the result.

### 5. Monitoring and admission cannot currently certify a clean run

These are detection/validation gaps, not mechanisms that create divergence:

- `SyncLogMonitor` starts at the existing log end. A pre-attachment failure is
  excluded. A missing log is not subsequently acquired; replacement/truncation
  invalidates association. The battle records monitor status but continues when
  monitoring becomes unavailable. No detected error therefore does not prove sync.
- Monitoring polls once per outer observation, before the runtime, cover and
  supply work. A newly logged failure can occur during that batch; stopping is
  not atomic with every individual RPC. Cancelling a Python transport wait cannot
  undo an already executing native function.
- Production authority/synchronization gates remain false. Diagnostic battle
  execution uses the trial interface and explicit capability overrides. Local
  host/ownership validation establishes permission to act, not replicated effects.
- `rpc.exports.identity()` reports `activeMods: null`. Executable hashes and
  signature checks do not establish identical loaded mod/script/data content
  between clients. Mod agreement needs separate evidence.
- The human-opponent harness branch tests nine roster/ownership cases and returns
  before the general action fixtures. It does not directly exercise rejection of
  all three cover actions. The guard exists in source; dedicated guard tests and
  a live no-cover run are still needed.

Recommendation: mark a synchronization trial inconclusive and stop new actions
when monitoring is unavailable; capture remote checks and build/mod identities.
Add narrow negative tests that prove blocked action families never enter native
functions. More offline fixtures cannot replace independent-client validation.

## Other host processes and maintenance

The review HTTP service and external evidence/SQLite processing do not perform
tactical native calls. The tactical battle has no normal dependency on a running
lobby-host bridge. Automatic result collection uses a separate host subprocess
after guarded completion/detachment; the CLI excludes that flow for human trials.

`headless_host.js` contains actual lobby configuration writes and native setup
calls. These are distinct from observation and subject to lobby/identity guards;
record-only mode rejects mutation commands. Its observation hooks still mean
record-only is instrumented, not an unmodified baseline.

Resource cleanup and audio reset are explicit experiments guarded by a local bot
lobby and an unloaded world (`headless_host.js:661`). Heap optimization is an
explicit local-bot-lobby operation (`:700`). They are not automatically called
by normal tactical battles or normal human recording. No evidence connects them
to the first tactical desync. Keep them out of synchronization trials. Local
gameplay-data patches or mismatched mods would be relevant if separately applied;
this audit did not inspect every installed archive or remote client filesystem.

## What the failed run actually exercised

Re-read the complete saved `observations.jsonl` under
`validation/local_archive/new_runs/human_opponent_battle_20260907_1`.
It contains 915 observations, 32 native move submissions, one stance submission,
eight observed purchases, and one scored-cover probe at quant 204399 with one
input record and zero candidates. There are no recorded `nativePathPreflight`
or attack-preflight events. Pathfinding preflight is therefore not supported as
the explanation for this run. Do not confuse its current availability with proof
that it ran before that failure. See [the checksum evidence](TACTICAL_HUMAN_TRIAL.md).

## Recommended isolation order and validation

Use fresh controlled matches and an independent client: uninstrumented baseline;
observation-only; ordinary moves; stance/mode; availability-only; purchases;
path-only; attack; then separately investigate cover and construction. Preserve
matched initial conditions and native/remote logs. Test interaction only after
isolating each family. The sequence is diagnostic, not a claim that isolated
success guarantees every later combination.

Ran all eight tactical/bot test modules: **207 tests passed** in 2.699 seconds.
Both `node --check headless/tactical_bridge.js` and
`node --check headless/headless_host.js` passed. Native routines are mocked by
these fixtures; no fresh multiplayer or transitive native side-effect proof was
produced. No runtime source or configuration was changed by this audit.
