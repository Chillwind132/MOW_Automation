# Replay analytics investigation — September 8, 2026

Inspected the two-file engine 3.262.1 replay format offline, including the
Player21/Heroic AI fixture matching the supplied screenshots and seven archived pairs.
No game attachment, database imports or production-reader changes were made.

## Confirmed additional data

- `.qm` contains length-prefixed formatted History text, followed by a uint32
  elapsed-seconds value and a length-prefixed event-icon path. A signature scan
  recovered kill, sniper and flag messages. The first seven times in the screenshot
  match exactly: 107, 108, 132, 135, 139, 140, 141 seconds.
- Kill messages identify attacker display name, weapon, victim display name and
  victim unit label. Environmental deaths occur as `world {crush}`. A sniper kill
  uses a separate icon; counting only `kill_*` would miss it.
- The existing SS resource ledger contains purchase identifiers, localization
  keys, amount, ordinary/special category, cumulative spending and a time field
  currently named `tick`. Do not conflate expenditure with wallet balance or
  purchase time with physical spawn/arrival. Resource-time units still require
  native confirmation before precise lifetime calculations.
- The skipped `battleInfoTotal/game` blob parses with the existing row decoder.
  In the screenshot fixture it contains 154 unit-detail records and no unread
  bytes. It is an aggregate unit record collection, not the chronological history.
- Existing unit vectors contain model/localization identifiers, owner identity,
  army, a short identifier and numeric details. Some numeric details are float
  bit patterns currently exposed as unsigned integers. Their complete meanings,
  identity lifetime and aggregate-versus-individual semantics need mapping.
- SS records also include map, mod/version, teams, AI difficulty, army selection,
  game settings, random seed, checksums and historical player experience fields.

## Concrete screenshot-match findings

- 161 recovered history entries: 151 `kill_*`, one `sniper_*`, nine `flag_*`.
- Player21: 109 attributed weapon events, matching 109 infantry kills, zero vehicles.
  M1 Garand: 38; .30 cal M1919 A6: 18; Garand grenade-launcher label: 13;
  M1A1 Carbine: 13; M1 Carbine: 11; BAR: 10; M16: four; Springfield: one;
  Crocodile: one. These are kill attributions, not accuracy or shot counts.
- AI: 42 attributed events including the sniper event, matching 40 infantry and
  two vehicles. A separate world/crush death accounts for Player21's 41st infantry loss.
- At 1259 seconds (20:59), Panzerfaust 60 is credited with the M16 and three crew.
  At 1294 seconds (21:34), Panzerfaust 100 is credited with the Crocodile and four crew.
  Same-time events are a loss cluster, not proof of a particular number of shots.
- Player21's ledger has 11 purchases totaling 2045 ordinary / four special resources.
  AI has seven totaling 1694 / zero.

## Useful analyses and boundaries

Immediately practical: weapon kill breakdowns, casualty timelines, player-versus-
player attribution where names are unique, victim-class breakdowns, simultaneous
loss clusters, build order and expenditure curves, and capture-event timelines.
Across matches, compare openings and weapons by map/faction/mod/settings; distinguish
correlation from causal effectiveness and retain missing-data indicators.

Not yet established: flag identity or exact ownership duration from generic capture
messages; individual unit birth-to-death links; damage, accuracy, ammunition, repair,
inventory, direct control, APM, movement tracks or heatmaps. These need further QM
packet mapping or playback observation. Same display names (especially multiple
Heroic bots) cannot be treated as durable player IDs. Icon suffixes are not yet
mapped to absolute team identities across recording perspectives.

All seven archived pairs decoded without an exception. History and scoreboard totals
do not universally reconcile; the larger AI match needs further investigation before
history can be used as an exhaustive combat accounting source. Zero-stat replays
examined here also had no recovered kill messages.

## Reproduce

`py diagnostics/replay_inventory.py tests/fixtures/replays/replay2/replay2.ss`

The diagnostic only reads its inputs and prints JSON. It is an exploratory signature
scanner with validated string fields, not a complete QM packet parser. Saved output
for the fixture and seven archived pairs is under
`validation/replay_inventory_20260908/inventory.json`. Offline assertions verified
the seven screenshot timestamps and both attributed player totals above.
