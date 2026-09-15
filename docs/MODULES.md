# Shared match data modules

`modules/live_game_data/` owns native live reads, participant identity validation,
match association, snapshots and departure observations. `bridge.js` reads existing
counters; `compose_bridge()` inserts it into the guarded host bridge during attachment.
A missing or repeated include marker fails before injection. Do not inject the host
JS file directly: load it through `compose_bridge()`.

`modules/end_game_results/` owns replay discovery, parsing, identity validation,
archiving and final-result persistence. Public APIs include `ReplayImporter`,
`load_result()`, `wait_for_match()` and `ensure_watcher()`. It has no game attachment
or UI dependency. `legacy.py` retains historical UI decoding for existing records
and diagnostics; active final results come exclusively from replay `battleInfoTotal`.

All controller attachments compose the same live reader and ensure the independent
replay watcher is running. Automatic friends hosting, record-only observation,
AI cycles and watch use the shared snapshots and participation API. Solo/run modes
also associate their loaded native generation through the shared observer. Game
start/exit permissions and durable command recovery remain in the host/controller.
Neither data module authorizes native game actions.

Public APIs are exported by each package. Older `headless/live_statistics.py`,
`match_telemetry.py`, `match_participation.py`, `match_metadata.py`, `match_results.py`
and `replay_results.py` are compatibility shims, not alternate implementations.
The root host CLI and all existing data/evidence locations remain unchanged.

```
py -m modules.end_game_results           # import completed persisted replays
py -m modules.end_game_results --watch   # independent singleton watcher
py -m modules.end_game_results --stop    # stop watcher, no game action
py tests/run.py
```

Final rows never borrow live/UI fields. Incomplete or identity-mismatched replays
remain pending. Live counters remain observations until an authoritative replay
is available; missing fields remain unavailable.

## Validation - September 8, 2026

All 437 regression tests passed (`validation/module_migration_tests.log`), including
standalone package/legacy CLI imports, bridge composition, replay-only lookups,
transient database startup retries and shared live-observer dispatch.
`node --check headless/headless_host.js` also passed.

Two local Heroic 1v1 bot games ran at 75 VP on 3v3 Big Desert Town, PID 46980:

- `e6fc2138-c0a4-4ca2-ad78-93b01fc143a6`: natural completion at 75-0, automatic
  replay import and lobby cleanup. 82 snapshots; all eight player-statistic fields
  in the last live snapshot matched the replay. The opposing random-faction bot
  recorded no resource spending or combat, so the next game used fixed factions.
- `b3aaa101-71c7-4faf-b891-f7e307d1efa1`: fixed ger_ss/usa bots. Host to watch to
  record-only to host preserved one match identity with no recording errors. Watch
  and record-only issued probes only. After 124 snapshots, this longer test was
  ended through the ordinary game menu while record-only observed. The replay
  imported automatically and matched the visible game statistics: infantry
  70/56 and 55/71; vehicles 0/1 and 0/0; scores 2730 and 1218; resources 829/0
  and 3464/0. This was an interrupted match, not a natural finish.

Evidence: `validation/module_bot_first_result.json`, `module_bot_second_result.json`,
`module_handoff_result.json`, and `module_bot_second_statistics.png`. Both archived
replay pairs remain under `data/replays/`. The game was left in the lobby and test
controllers stopped; the independent replay watcher remains running. The manual
menu exit required visible UI interaction, so that final observer run is not a
background-window validation. These are local bot checks, not a multi-client
synchronization or overnight-stability claim.
