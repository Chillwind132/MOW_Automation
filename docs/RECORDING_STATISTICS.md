# Battle-statistics recording - September 8, 2026

The recorder now reads existing combat counters and score/resource data during
gameplay. It makes no new native function calls and does not build a scoreboard
or modify simulation state. Normal snapshots retain these observations in
`match_snapshots`; the default interval remains 30 seconds. This investigation
uses `--snapshot-seconds 5`.

Player association checks the durable match generation, native member ID,
Steam identity, AI flag and team. The native game-player slot is a separate ID;
it must not be confused with the lobby slot or member ID. An absent structure or
failed identity check produces unavailable data, never invented zeros. A changed
HUD ownership chain discards that HUD sample and retries on the next poll,
without terminating match/finish observation.

The review puts the latest valid progress snapshot into the main results table
until final replay results are available. Native team VP values
are mapped by their team keys. Generic HUD observations retain their original
unmapped labels. The local browser page refreshes automatically every five seconds.

## Final results: replay only

Per the user's September 8 decision, `modules/end_game_results/replays.py` is the only
active final-results importer. Neither UI rows nor live counters fill replay
fields. Completion-overlay reads only identify a safe native Exit action;
they no longer publish final rows or ratings.

An independent watcher starts on controller attachment and polls once per second.
It survives game/controller exit, requires two stable observations and complete QM
begin/end markers matching SS start/end times, and checks the engine version,
compressed statistics and member/Steam/team identities. It reads `battleInfoTotal`.
Recorded matches are associated by generation, map and all participant identities.
A replay without a recorded start receives a deterministic replay-derived match
identity. Ambiguous or conflicting associations stay pending.

Both files are archived atomically under `data/replays/<SS SHA256>/`. Final rows
are committed transactionally to `results`. Superseded UI exports and metadata
remain in `superseded_results`; old completion captures remain historical evidence.
Ratings and review use the replay when present, including an unavailable outcome,
without borrowing the older UI winner. Historical matches without an available
replay retain their legacy records.

Run `py -m modules.end_game_results` for an offline import, add `--watch` for a
continuous watcher, or use `--stop` to stop it. No game launch or attachment is
involved. Default discovery is under Documents/My Games/men of war - assault
squad 2/profiles; `--profiles` overrides it. Log: `data/replay_importer.log`.
Incomplete or unsupported files remain pending. A crash may leave no complete
replay; this policy cannot reconstruct final results from such a file. UI `export`
now rejects imports. A controller starts the watcher again on its next attachment.

## Field evidence

Retail executable 3.262.1; existing executable identity checks remain required.
Read-only Ghidra outputs are under
`validation/tactical_mapping_20260907/recording_stats_*.txt` and
`recording_resources.txt` (the diagnostic tool's existing output directory).

| Field | Native evidence |
| --- | --- |
| Infantry pair | `9D4650` serializes `enemy` and `lost`; `BC2D20` copies counter offsets `+8/+14` into result `+58/+60`; `AD1BF0` displays them in that order. |
| Vehicle pair | Same path, counter `+2C/+38`, result `+5C/+64`. |
| Score | `BC28C0` truncates the keyed manager score entry's float `+8` into result `+4C`; `AD1BF0` displays it. |
| Team VP | `BC28C0` uses the team-keyed float `+4`, truncated into result `+48`. |
| Resource pair | `AD1BF0` sums resource-detail amounts `+48`, truncating each addition, grouped by category unequal/equal to `special`. The live reader walks the corresponding bounded resource tree in the same order. This is not the current MP wallet. |

The combat-statistics owner is `[FE41D8]+114`, with vtable `E07E08`.
Combat counters have vtable `E07DB4`; resource tables have `E07DEC`.
The manager is `[FED0C4]`, with identity vector `+68` and score vector `+8C`.
All offsets refer to this executable only. Native getter/build functions were
decompiled for understanding; they are not called by the new observation code.

## Live validation

Match `55709720-7be9-4491-8f71-49b6bf5ac748`, Player21 versus Heroic AI,
was already running when the observer attached. The first observer stopped on
`Live HUD ownership changed`; the game remained alive. The fix resumed the same
durable match. Runs `run_20260908_182807_266753` and
`run_20260908_183243_948443` contain live native counters; consult current control
status for the exact active evidence path.

A saved live sample showed Player21 infantry 34/9, score 690, resources 960/0;
the AI had infantry 9/34, score 224, resources 684/0. The user then exercised
vehicles and special resources and left the match after 22:19. The complete
replay and replay Results screenshot agree:

| Player | Infantry | Vehicles | Score | Resources |
| --- | --- | --- | --- | --- |
| Player21 | 109 / 41 | 0 / 2 | 2288 | 2045 / 4 |
| Heroic AI | 40 / 109 | 2 / 0 | 1601 | 1694 / 0 |

Team B has 86 VP and Team A 26. The replay outcome key records **A**; higher VP
is not used to determine the winner. This was a manual exit, not an observed
natural finish. This local-player/AI test does not establish spectator-host or
remote-client completeness.

The previous Player20/Player07 match `61c49e25-d30e-421d-829a-a76f7c144423`
has zeros in its persisted replay as well as its historical UI captures. Player20
has resources 0/0; Player07 has 881/0. Both have zero infantry/vehicle/score values.
These are saved replay values, not missing fields defaulted to zero. Replay-only
import cannot recover combat statistics the engine did not persist.

## Replay format evidence and checks

Reader `BC34F0` supplies the serialized field order. Strings use the `7278F0`
short/24-bit length prefix; B64 blobs use zlib compression. Resources are read in
stored order with native single-precision/integer accumulation. Optional unit
vectors follow `9D48B0`. The native writer reuses its buffer: shorter rows retain
unused trailing bytes from earlier rows. Counted vectors bound the record; the
tail is not interpreted as counters.

`BC4020` serializes the collection outcome key; `BC5060` restores it. `BC3F90`
resolves it to a row. `BC4360` and `BC4880` use that row's team as outcome 1 and
the opposite team as 0 for native rating calculation. This verifies the outcome
field independently of VP ordering. Read-only decompilation artifacts are in
`validation/tactical_mapping_20260907/replay_*.txt`. No native functions are called
by the replay importer.

Real replay fixtures cover nonzero vehicles/special resources, original zero
values, interrupted-file retry, association failures, source precedence and
idempotent promotion. All 430 offline tests pass after the review-page polish. Final output: `validation/replay_results_tests.log`.
Bridge syntax: `node --check headless/headless_host.js`.
Pre-promotion database backup:
`data/backups/rankbot.before_replay_authority_20260908.sqlite3`.
