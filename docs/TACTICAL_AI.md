# Upgraded Move at will: feasibility and validation

Follow-up: [live unit/function mapping and ranked implementation suggestions](TACTICAL_AI_MAPPING.md).
The report below records the earlier preliminary inspection; the follow-up adds
live selected-marine state, movement transitions and native order traces.

Inspected September 6, 2026 local time (September 7 UTC), using local files only.
No AI behavior changes, process writes, injection, or game commands were applied.

## Evidence from this session

- Running `mowas_2.exe`: PID 18552 at inspection, image base `0x400000`,
  Windows file version `3.2.6.2`. Rediscover PID/base before another probe.
- Profile options list Robz realism mod 1.30.10. This does not establish exhaustive
  runtime asset precedence or the selected soldiers' effective properties.
- Installed Robz `properties/human.ext` contains `advance_ratio 10.0`,
  `retreat_ratio 0`, `no_retreat 1`, `move_radius 50.0`, `look_around 1`, and
  `control user` in the human brain Properties block. These are uncommented.
  The corresponding base-game file lacks this block.
- Both inspected human definitions contain `ManualAccuracy 1.5`. Robz also
  changes movement-dependent accuracy and settling time. The exact manual
  multiplier formula and its contribution to observed hit rate remain unverified.
- Weapon dispersion is defined separately in `set/small.firearms.accuracy`.
  Target selectors use distance, threat/attacking state and weapon/class filters;
  they are not evidence of a head-bone aiming interface.
- Base `script/multiplayer/bot.lua` issues squad CaptureFlag orders. Changing that
  commander logic does not establish control over human-owned Move-at-will units.
- Bounded external ReadProcessMemory checks matched the historical executable
  dump exactly: 324 bytes at `0x914ea0`, 1616 bytes at `0x95b3e0`, and 42 bytes
  at `0xdfc01c`. Historical decompilation associates these code ranges with
  brain properties. This validates reference-code identity, not active unit
  values, exact decision formulas, or a callable tactical API.

[Captured sources, hashes and live checks](../validation/ai_feasibility_20260907_032126_974177/report.json).
[Historical static review](../archive/reverse_engineering/analysis/ai_review/REVIEW.md).

## What is possible, and what is still a hypothesis

| Requested improvement | Established basis | Validation still required |
|---|---|---|
| More useful target priorities | Installed selectors already express threat/range/weapon priorities | Controlled target-choice comparison; effective overrides |
| Less reckless advance and useful retreat | Native properties and Robz's no-retreat configuration exist | Selected-unit instance, property interpretation, stronger/weaker opposition comparison |
| Better shooting | Separate spread, motion accuracy and manual accuracy settings exist | Equal weapon/range/stance/veterancy A/B shots; hit locations and ammunition used |
| Duck behind useful cover and advance between cover | Human brain and stance state-machine resources exist | Cover candidates, path reachability, line-of-fire queries and stance/order interface |
| Remember enemies and react to their direction | Can be implemented in a custom decision layer once observations exist | Visible-unit IDs, position, facing, simulation time and loss-of-visibility semantics |
| Coordinate squad movement and fire | Custom squad policy is technically plausible | Membership, per-unit native orders, player override and conflict handling |
| Direct-control precision for multiple autonomous soldiers | Manual aiming exists in the game | Per-unit aim-point path, ballistic limits and control ownership; simultaneous direct control is unproven |
| Multiplayer operation | Existing host instrumentation works | Tactical command authority and synchronization; bot-only success cannot establish remote-client correctness |

These are feasibility levels, not claims that every requested behavior is implemented.
Editing shared human/weapon resources would have broader scope than an opt-in
Move-at-will ability. A runtime controller needs a verified per-unit activation gate.

## Proposed controller

Retain native navigation, animation and ballistic execution. Add a tactical layer
that ranks cover, movement, fire, healing/reload and withdrawal actions for each
eligible soldier. Add a squad layer to reserve cover positions, spread units and
alternate moving and covering groups. Use visible enemies and remembered last-seen
positions with decaying confidence; do not confuse world-state access with perception.

Use simulation time and bounded updates. Account for friendly support, threat
direction, health/ammunition, exposure, weapon range, objective distance and recent
orders. Commit to actions long enough to prevent constant advance/retreat oscillation.
Player orders and direct control must revoke AI ownership immediately.

Accurate fire is a separate policy: settle movement, choose an exposed aim point,
check line of fire, and fire when worthwhile. Headshots are not guaranteed by an
aim-point decision because spread, obstruction and target motion still matter.

## Next experimental gates

1. Resolve selected unit IDs, ownership and brain instances. Observe Hold position
   versus Move at will and verify the actual transition field; do not guess offsets.
2. Map current order, visible threats, position, health and weapon state. Compare
   observations with a small controlled scene before generating any orders.
3. Prove one reversible native stance/move order on one soldier on the correct
   simulation thread, including immediate player override and unit-death handling.
4. Compare default and modified retreat behavior while keeping weapon/grenade
   settings fixed. Measure exposure, losses and withdrawal time.
5. Separately compare native firing, manual firing and any aiming intervention
   under matched conditions. Record shots, hits, hit locations and time to kill.
6. Add cover/advance and squad coordination only after their inputs and actions
   pass individual tests. Validate synchronization separately before claiming
   multiplayer readiness.

The read-only probe is `diagnostics/ai_feasibility_probe.py`. Without PID/base it
captures installed source files only. With both arguments it performs the three
bounded native comparisons; it intentionally rejects relocated images.
