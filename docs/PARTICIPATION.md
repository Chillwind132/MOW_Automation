# Departures and reconnect evidence

Implemented 2026-09-05 in `headless/match_participation.py`, both active-match runner loops, and the passive native hook in `headless/headless_host.js`. This is evidence collection only: no strikes, bans, cooldowns or rating deductions are applied. The existing rating policy is unchanged; participation evidence is not yet an automatic eligibility override. A leave/rejoin can therefore require manual review even if final rosters match.

## What is captured

### Durable progress and session events (September 7)

`headless/match_telemetry.py` is shared by record-only, automatic friends hosting,
and the controller's `watch` loop. `match_snapshots` stores an append-only initial
snapshot, then one every 30 seconds of successful observation by default
(`--snapshot-seconds` changes this). Each snapshot has a match ID, original sample
time, database recording time, reason, match metadata, full roster and raw live
HUD values. A restart starts a new observation segment. Invalid probes and
different lobby/generation samples are rejected. Missing live per-player counters
are explicit; HUD values are still unmapped to team identities.

Participation changes and membership callbacks immediately flush the latest
valid sample. `match_observation_events` records return to lobby, return to the
Internet browser/main menu, changed native generation (manual observer), game
process termination, instrumentation detachment, observation failure and orderly
controller shutdown. Steam membership evidence identifies whether the affected
identity was the starting host, including a spectator host. Same-lobby callbacks
outside gameplay may appear in the session timeline but are not claimed to be
in-match player departures. A browser transition records that the local client
left the match session; it does not prove which person closed it or why.

An event can arrive after the last readable gameplay sample. The saved sample
retains its original timestamp instead of pretending its counters were sampled
at the time of failure. Sudden controller termination or power loss cannot run
the final flush; the last committed snapshot survives. Disk errors are reported
as `match_telemetry_error`; no successful save is implied. These observers add no
native calls, UI actions, or automatic penalties. Existing lifecycle recovery
guards are unchanged.

The HTML review includes progress-only matches as having no confirmed winner,
with a snapshot selector and session-event details. Final captures take precedence
without creating duplicate matches. Progress tables are not rating inputs; a
result or explicit user adjudication is still required. The September 7 change
passed 359 offline tests and bridge syntax validation; fresh live validation is
pending. Restart the running controller to load it.

- At approximately one-second successful gameplay polls: disappearance from the expected human roster, restoration, Steam identity ambiguity, changed native member binding, and changed team/role. Matching uses Steam IDs, not names. Playing participants exclude spectators and AI.
- Match ID, Steam ID, observed timestamps, native match epoch, before/after states and the full roster at each change. Multiple simultaneous absences retain a shared count for outage review. Times are observation times, not exact disconnect or participation durations.
- Observer startup, restart or a polling gap exceeding five seconds is explicit. A player already missing at first observation is not claimed to have left during observation. Invalid probes and mismatched match/lobby generations do not become departure events.
- Once the native manager reports terminal state, the observer marks the finish and stops inferring departures. Cleanup at that boundary is not counted as an early exit. Any last-second transition missed between polls remains unknown.
- Raw Steam lobby membership callback data: lobby ID, changed Steam ID, actor Steam ID, flags, receipt time, callback page/manager state, and 28 payload bytes. Flags decode to entered, left, disconnected, kicked, banned, or combinations. Events outside active gameplay are retained without a match association. In-match association uses the controller's active match and same lobby; the Steam payload itself has no AS2 match generation. The controller epoch and participant role are preserved as context.

`participation_state` stores durable observer state; `participation_events` is the timeline. New events also appear in each run's `events.jsonl`. Regenerate match review to inspect **Departure / rejoin evidence (no penalties)**. All stored events are available through:

```powershell
py headless/match_participation.py
py headless/match_participation.py --match-id MATCH_ID
py headless_host.py review --no-open
```

The history commands open SQLite read-only. No retrospective events were invented for the two historical rated matches.

## Native investigation

In the local dumped retail executable, registration at `0x66ffe0` pushes callback **506**, binding handler `0x670740`. This handler reads the changed Steam ID at payload `+8` and tests byte `+0x18` against mask `0x1e`, matching leave/disconnect/kick/ban flags. The observer reads the three 64-bit IDs followed by the 32-bit flags. The passive hook checks the handler prologue and the flag-test instruction; the controller also retains its supported executable hash check. A hook mismatch disables this optional signal and logs the reason, leaving roster observation available. It never invokes Steam or game departure functions.

[Disassembly evidence](../validation/participation_20260905/native_callback_disassembly.txt). Earlier proxy notes label callback IDs one position off; those labels were not used as authoritative evidence.

Steam documents `Left` as leaving the lobby and `Disconnected` as disconnecting without first leaving. These describe the mechanism, not motivation. A crash, application shutdown or network failure cannot reliably be distinguished from deliberate abandonment from that flag alone. Leaving a Steam lobby also need not equal leaving the running game. Correlate it with the in-game roster and match state. [Steamworks ISteamMatchmaking reference](https://partner.steamgames.com/doc/api/ISteamMatchmaking#EChatMemberStateChange).

The game may retain disconnected players in its session roster; whether it does so, whether a returning player can resume actual play, and which callbacks appear on explicit in-game Exit all need live confirmation. Do not interpret absence of a captured event as proof nobody disconnected.

## Historical validation and the next real incident

The test counts below describe the September 5 milestone, not the current suite.
See [current status](STATUS.md) for the latest recorded validation.

Baseline 98 tests passed; 12 departure-tracking tests added; final suite **110 tests passed**. Coverage includes departure/return deduplication, stable Steam identity through binding changes, spectators, terminal cleanup, unknown probes, generation mismatch, startup/restart gaps, multiple missing players, every Steam flag, raw callback routing, and read-only history. Native bridge syntax and existing match-review rendering checks passed. No real player was disconnected, no chat was sent and no rating was changed by this work.

A bounded read-only attachment was attempted; it returned **Game is not running**, so hook installation and real callbacks remain **not live-verified**. The previous controller's saved status was stopped with a service-probe error. The new capture is armed only when a new controller process is running; changing files does not update an already-running process.

For a manually played match, run from the project directory:

```powershell
py headless_host.py friends-host --record-only --rating-profile robz-battle-zones
```

Automatic `friends-host` mode also includes the tracker. Run only one controller. If someone leaves, note the player name and approximate time, and tell the assistant what was visibly observed. After the match, keep the Game Result tab visible for result capture. Review the timeline alongside the finish; the event log remains useful even if incomplete participant results cannot be normalized.

Without another player, synthetic tests can verify bookkeeping and code inspection can identify signals, but neither proves remote quit-versus-disconnect behavior. The next supervised test should compare (1) explicit in-game Exit, (2) abrupt client/process/network loss, (3) a return if AS2 supports it, and (4) ordinary departures after a natural finish. Confirm the host remains healthy, the observed Steam identities agree, and departure events precede the native finish. These require a consenting second client; do not disrupt a real match to manufacture a test.

## Proposed discipline policy — not enabled

Use a rolling **90-day** window and at most one reviewed abandonment incident per player per match. Keep evidence, adjudication and any reversible discipline ledger separate from the skill estimate.

| Reviewed event | Proposed consequence |
|---|---|
| First confirmed voluntary abandonment within 90 days | Warning |
| Second | 24-hour rated-lobby cooldown |
| Third and later | 72-hour cooldown, with review before longer suspensions |
| Connection loss, unknown cause, or Steam `left` without corroboration | Record only; no automatic skill deduction |
| Repeated unresolved disconnects | Reliability review; consider a short cooldown only after excluding host/shared outages |
| Kick, host failure, shared outage, post-finish departure | No player abandonment strike |

If reconnecting into active play is supported and can be verified, allow approximately two minutes to return before considering an absence unresolved. A return to the Steam lobby alone is insufficient. Until reconnect behavior is verified, use that time only to collect evidence, not as an automatic strike deadline.

A hard deduction from matchmaking skill is a poor punishment: it can grant a strong quitter easier future opponents and distort team balancing. If a visible points consequence is desired, a possible second-offense policy is **−100 separate conduct/ladder points**, alongside the cooldown, without changing TrueSkill mean or uncertainty. Such a ladder ledger and enforcement do not currently exist. Confirmed voluntary abandonment needs an independently verified in-game signal or manual adjudication; current telemetry alone does not establish intent. Any future policy should be versioned, reversible, announced before enforcement, and should not retroactively penalize the historical games.
