# Tactical AI memory and function mapping

September 6, 2026 local / September 7 UTC. Local investigation only.

**Conclusion:** a tactical layer issuing native orders to individual soldiers is
well supported by the evidence. A complete autonomous controller, its combat
benefit, and synchronized multiplayer execution are not yet validated.

The selected marine was resolved through the game's own selection vector, with
the human-brain vtable and brain-to-actor backpointer independently checked.
The session observed real game/user-issued orders; it did not issue experimental
orders or change AI properties. Temporary Frida observation hooks were detached.
All nine final code comparisons matched the reference executable, including the
four hooked sites. The game was still running and responding.

## Live evidence

[Machine-readable summary](../validation/tactical_mapping_20260907/summary.json)
contains hashes, order types, transitions, counts and limitations.

- 898 selection samples over approximately three minutes; two samples were
  discarded because selection changed during the read. No stale sample was
  treated as a stable selection.
- For the same marine, movement bits changed `0 -> 0x1000 -> 0`, matching the
  requested Move at will / Hold position / Move at will exercise. The native UI
  label path independently associates zero with Move at will.
- Chassis stance values changed among 0, 1 and 2 during the stance exercise.
  Native UI conversion maps normal=0, crouch=1 and prone=2. The recorded sequence
  includes intermediate transitions and is not a frame-by-frame animation proof.
- 40 actor-order calls and 40 corresponding non-null actor-order returns were
  observed. These prove the native entry point accepted order objects; they do
  not prove every requested action completed successfully.
- Types: Advance 16, MoveTask 9, Examine 5, MovementChange 2, Attack 2, and one
  each of FortifySequence, Hideout, WeaponAiming, Leave, MoveToCover and Fight.
- All traced order calls used thread 15524 in this process. Re-identify the
  execution thread in another session; this is not a universal thread ID.
- Sensor vectors held 56, 18, 18 and 0 record pointers at inspection. Records
  include actor pointers, coordinates and flags. Membership, visibility and
  allied/enemy semantics are not fully verified.

## Memory map

Addresses below apply to the inspected non-relocated executable at base
`0x400000`. Heap addresses and thread/PID values are ephemeral. These are research
findings, not an unchecked patch recipe.

| Path / offset | Meaning and evidence |
|---|---|
| `*[0xFE6384]` | Game-control singleton; live `0x591ED290`, vtable `0xE12468` |
| `gameControl + 0x58` | Selection object; live `0x3B154B30`, vtable `0xE125B8` |
| `selection + 0x04/08/0C` | Begin/end/capacity of 8-byte selection entries; first word is actor pointer |
| Selected actor | Marine `0x562F2710`; actor vtable `0xDFB9B8` |
| `actor + 0x44/48/4C` | World position floats; corroborated by native distance calculations |
| `actor + 0x784` | `Actor::eFsm` pointer, vtable `0xDF4A38` |
| `actor + 0x788` | `Actor::eCover` pointer, vtable `0xDF8380` |
| `actor + 0x78C` | `Actor::eHumanBrain` pointer; live `0x54F1C590`, vtable `0xDFBED0` |
| `actor + 0x790` | `Actor::eSensor` pointer, vtable `0xDF7C04` |
| `actor + 0x794` | Weaponry-related component, used by native manual-control handling |
| `actor + 0x798` | `Actor::eChassisFoot` pointer, vtable `0xDF6990`; stance at component `+0x20` |
| `brain + 0x20` | Owning actor pointer; matched selected actor |
| `brain + 0x210`, mask `0x3000` | Movement mode: zero Move at will; `0x1000` Hold position; third engine value `0x2000` not behavior-tested |
| `brain + 0x7C` | Current order-related pointer; exact lifetime semantics require further mapping |
| `brain + 0x224` | Current target/contact record; native targeting code and live non-null values |
| `brain + 0x2C0/2C4` | Calculated local force values; native routine refreshes them from sensor data |
| `brain + 0x2C8/2C9` | `no_advance` / `no_retreat` bytes; marine values 0 / 1 |
| `brain + 0x2CC/2D0` | Advance / retreat ratios; marine values 10.0 / 0.0 |
| `brain + 0x2D4` | Tactical state enum; values 0..4 in native decision logic; do not assign all state names without branch tracing |
| `gameControl + 0x240` | Direct-control context pointer; useful takeover gate, but not sufficient as the only gate |

**Offset correction:** historical property serialization is relative to the
secondary interface at `brain + 0x0C`. Its `+0x2BD` no-retreat field is therefore
`brain + 0x2C9`, not `brain + 0x2BD`. The actual live values and decision code agree.

The initial raw dump labeled the low word at actor `+0x54` as a candidate entity
ID. Its identity/generation semantics are unverified: do not use it as a stable
controller identity. Likewise, the first observer's `basis_xy` field started at
`+0x1C` and includes flags; it is not validated facing telemetry. The helper now
starts transform sampling at `+0x20`; coordinate conventions still need testing.

## Native functions

| Address | Established role | Evidence / limit |
|---|---|---|
| `0xA642D0` | Single-selected-actor accessor | Native vector and actor-type checks; direct-control special case |
| `0xA63400` | Aggregates actor state for selection UI | Reads brain movement mask and stance-related state |
| `0xA89A30` | Move-mode UI action | Constructs command type 5, obtains next mode, submits it |
| `0xAAB320` | Movement-mode command handler | Iterates resolved actors and calls brain setter |
| `0x8E8C80` | Brain movement-mode setter, thiscall | Updates bits 12..13 and invalidates part of current order state |
| `0xAAA6F0` | Stance command handler | Makes MovementChange order and submits per actor |
| `0x8E0280` | MovementChange order factory | Allocates 0x2C bytes; pose/speed fields at order +0x20/+0x24 |
| `0x8317C0` | Actor order submission, thiscall | Live 40 accepted objects; checks actor eligibility and forwards to brain |
| `0x8EAC40` | Brain order submission, thiscall | Live trace; handles invalidation and delayed versus immediate queueing |
| `0x8EB130` | Immediate order routing | Flags choose insertion path; unhandled flags destroy the object |
| `0x916540` | Human tactical decision | Force values, ratios, cover state and no-retreat branch |
| `0x88C380` | Local force evaluation from sensor records | Distance/time-dependent terms; exact team/visibility semantics pending |
| `0x8A65F0` | Cover candidate query/selection helper | Native MoveToCover path; actor, point and a 0x80-byte output record; nearest candidate selection observed statically |
| `0x8C6C60` | MoveToCover factory | Copies 0x80-byte cover record into order; live MoveToCover type observed |
| `0x8C7680` | MoveToCover lifecycle | Queries cover, sets up native movement and manages child order |
| `0x8CC320` | WeaponAiming factory | Live WeaponAiming type observed during manual-control command path |
| `0x8CCAD0` | WeaponAiming lifecycle | Reads shared aiming context and spawns further preparation/aiming actions |
| `0xAAE9D0` | Manual-control command handler | Toggles brain/chassis/weaponry control state, submits WeaponAiming |
| `0x8E8720` | Brain control-lock counter change | Changes low six bits at brain +0x214; not a simple on/off boolean |

Decompiler prototypes are not all complete; several functions use ECX or stack
construction obscured by decompilation. Verify call sites/assembly and ownership
before invoking any function. Replaying the lower-level setter alone can bypass
the game's serialized command path.

The trace exposed an 8-byte order-parameter structure. Observed first words
included 1, 2 and 5, with a delay word commonly zero. Native code uses mask `0x4` for
state invalidation and masks `0x1`/`0x2` for insertion paths. Preserve the original command
semantics and allocator/destructor ownership rather than copying arbitrary bytes.

## Ranked implementation suggestions

Confidence here means confidence in building a prototype from mapped primitives,
not a measured combat improvement or multiplayer certification.

| Rank | Suggestion | Confidence | Relative effort | Why / remaining gate |
|---|---|---|---|---|
| 1 | Restore useful retreat and tune advance/retreat thresholds for opted-in units | High | Low–medium | Live disabled-retreat state and native branch confirmed. A/B test against stronger/weaker threats; preserve grenade handling. `advance_ratio=10` is a threshold, not proof of aggression. |
| 2 | Explicit AI ownership with immediate player override | High for prototype | Medium | Selected unit, movement mode, manual-control path and native order entry are mapped. Need robust unit identity, generation changes, and event-origin tracking. Build this before issuing autonomous orders. |
| 3 | Cover-aware repositioning and stance selection | Medium–high | Medium | Real MoveToCover and MovementChange orders observed; native cover query and factory mapped. Verify reachability, cover-facing quality, occupied slots and cancellation. |
| 4 | Stop, settle and fire; avoid pointless movement while engaging | Medium–high | Medium | Position/stance and movement/attack orders exist. Map weapon readiness, aim settling and target exposure before measuring hit rate. |
| 5 | Threat memory with decaying confidence and sensible target commitment | Medium | Medium | Existing sensor contacts and time-dependent force calculations provide a base. Map visible/remembered/dead/friendly flags before using contacts. |
| 6 | Squad spacing and alternating movement/covering groups | Medium | High | Individual native orders exist. Need membership/roles, shared cover reservations and coordinated cancellation; avoid repeated orders and congestion. |
| 7 | Suppression/health/ammo-aware retreat, healing and resupply | Medium–low currently | Medium–high | Useful policy, but health, ammunition, suppression and item-use interfaces were not mapped in this investigation. |
| 8 | Per-soldier exposed-body-part aiming with direct-control-like precision | Low–medium currently | High | Native aiming exists, but WeaponAiming consults shared state. Independent aiming contexts, bone visibility, prediction and spread formulas remain unverified. |

Recommended first build: ownership gate + conservative retreat experiment + one
native cover/stance action. Then measure exposure time, order churn, losses and
shots-to-hit against the default behavior. Do not begin with universal headshots.

## Remaining boundaries

- No agent-issued movement/stance call was tested. We observed the game's own
  command construction, dispatch, acceptance and associated live state changes.
- Thread identity is observed; a safe bounded callback point for autonomous
  command scheduling still needs a supervised validation.
- Multiple controlled units, entity deletion/reuse, match reloads and changes of
  player ownership need guards before a persistent controller is appropriate.
- Host-versus-client authority and multiplayer synchronization are unresolved.
  Serialization code exists, but local direct calls are not proven to replicate.
- Existing sensor records can represent more than currently visible enemies.
  Historical positions must come from validated perception semantics.
- No combat A/B experiment or accuracy measurement was performed.

## Reproducible tools and evidence

- `diagnostics/tactical_map.py` and `AnalyzeTactical.java`: local PE references,
  bounded memory reads and read-only Ghidra decompilation. The Ghidra project is
  opened with `-readOnly`; temporary function definitions are not saved.
- `diagnostics/tactical_observe.py`: bounded external selected-human observation,
  code/vtable/vector/backpointer checks, and rejected selection-race samples.
- `diagnostics/tactical_trace.py`: explicit bounded temporary Frida observation;
  checks code signatures and filters actor/brain events to the specified unit.
- [Evidence directory](../validation/tactical_mapping_20260907/): raw snapshots,
  decompilation, hook events and summary. Early exploratory decompilations include
  unresolved or mis-targeted addresses; use the curated mapping above.

Validation: successful live observation and trace, nine post-detach native byte
comparisons, Python compilation, and repeated successful Ghidra runs. These are
diagnostic helpers, not production unit-control APIs.

## September 7 follow-up: sensor and purchase discovery

Native relation follow-up: `9c9330` calls `9c9560` with ECX `fe37e0`
(`contact_relation_callsite.txt`, `contact_relations.txt`). That object contains
vector begin/end at +0/+4 and row stride at +8. Indexing is
`stride * subjectOwner + observerOwner`, and equal owners return 2. The supported
live table was 5x5: owners 2/3 returned 2 against each other; each returned 1
against owner 4. The bridge bounds the vector/stride to the native 18-owner limit.
`88d630` selects perceived versus actual ownership with record +4 bit 0x20;
`9c9330` recognizes perceived local ownership at actor +0x778 when that bit is
clear. The bridge mirrors this check and the subject +0x780 bit-8 precondition
without calling either native function. Raw actual-owner and sensor relations
remain separate. Unknown/neutral values do not become enemies or allies.
See the dated live query and scope in `TACTICAL_AI_PROGRESS.md`.

Later implementation trials are tracked in [current progress](TACTICAL_AI_PROGRESS.md).
The following are static findings unless a live observation is explicitly stated.

- Sensor vectors begin at `+0x28`, `+0x34`, `+0x40`, `+0x4c`; bounded live queries
  found 22 records in `+0x40` for leader 24 and none for detached soldier 18.
- Record actor pointer `+8`, recorded XYZ `+0x10`, position-update ticks `+0x44`.
  `0x88c150` copies a position, updates the clock, and sets flag `0x10000000`.
  Both event handling (`0x88cf40`) and target preparation (`0x889210`) call it.
  Therefore neither this flag nor a fresh timestamp proves visual contact.
- `0x88d630` sets relation flags using `0x9c9330`; relation value 2 includes self
  ownership and allies. Record `+4` bit `0x10` reflects actor eligibility flags,
  not a proven confirmed-death event. The live friendly records had value 77.
- Bot API Spawn is `0x629e90`. It looks up an entry, checks availability with
  `0xbe7670`, and serializes a native type `0x2a` message. Normal purchase submission
  `0xb57e90` uses the same serializer `0xbcc8f0`. Calling conventions, context,
  authority, completion and resource consumption still require validation.
- Native catalog vector object is `*[0xf3c930]`, begin/end at `+4/+8`. The live
  catalog had 2,056 entries with vtable `0xe31eb8`; serialized template ID is
  at `+0x388`. Read-only candidates include `mp/usa/usa_rifle` ID 166 and
  `mp/usa/usa_marine_rifle` ID 230. These are catalog entries, not evidence of
  current player availability or successful spawning.

Evidence: `validation/tactical_mapping_20260907/sensor_position_sources.txt`,
`sensor_record_updates.txt`, `native_purchase.txt`, `purchase_ui_path.txt`, and
`usa_purchase_candidates.json`. No purchase was issued during this discovery.
