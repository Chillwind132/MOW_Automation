# Robz ratings and spectator loop

The match review header's **ELO** button opens a compact visual guide to the
current TrueSkill calculation: team result, both teams' strength, uncertainty
and team size. It includes expandable formula and provisional-rating notes. Close with the close button, Escape or the backdrop.

Source paths are relative to the project root. See [current status](STATUS.md)
for the current suite and runtime limits; dated validation sections below are historical.

The user approved the outcome-only TrueSkill fallback on 2026-09-05. This is not Elo or a fitted TrueSkill 2 performance model. The two historical matches are sufficient for calculation checks, not for fitting or validating individual score effects. Score, counter pairs and games-played badges do not affect skill.

`headless/match_ratings.py` implements the two-team Gaussian moment update directly, with no additional runtime dependency. The model is `robz-outcome-v1`, pool `robz-battle-zones`: starting mean 25, uncertainty 25/3, performance noise 25/6, per-match drift 25/300, no draw margin. Display is `1000 + 40*(mean - 25)`; uncertainty above 6 is provisional. These are fixed initial settings, not fitted AS2 parameters. Draws and unknown winners are excluded. Uncertainty is retained for future balancing; automatic team balancing is not implemented.

Battle Zones automatic outcomes now require the recorded winning team to reach Final VP, with the other team below the target. Missing target or team totals and early replay winner flags are excluded unless an explicit manual decision exists. Archived replay settings take precedence over lobby metadata. This outcome policy participates in the rebuild digest; old rating runs and raw evidence are preserved.

Eligible matches require equal-sized human teams, stable Steam identities, complete matching result identities, a confirmed natural winner, Battle Zones and an explicit Robz declaration. Spectators and AI never receive ratings. Changed final teams, unresolved participation, missing identities and conflicting finish/lobby captures are excluded. Full per-player participation time and reconnect history are not measured; roster agreement is a documented initial approximation. Known attached-in-progress captures are excluded.

The two historical IDs in `HISTORICAL_ROBZ` record the user's identification of River Valley and Kalinina as eligible Robz games. Their original metadata remains unchanged. Future runs use `--rating-profile robz-battle-zones`, an operator declaration that Robz is loaded, not automatic native mod/version detection. Do not change the mod during a declared run. Unknown profiles remain unrated. The initial pool combines Robz versions and equal team sizes; there is not yet reliable version telemetry to separate them automatically.

Finish capture and lobby export trigger processing. Lobby observation retries processing after restarts before reading ratings. Match review shows per-match skill, change, provisional status, model and eligibility audit; plain lobby greetings include the available skill rating and its provisional status, or `Rating: unrated.`. Lobby history JSON and CLI include current Robz skill. Existing quiet-chat, cooldown and at-most-once greeting behavior remains in force, so there is no per-player post-match message burst.

Each rebuild reads all saved inputs chronologically under one SQLite transaction. An immutable `rating_runs` snapshot contains frozen parameters, before/after values and inclusion/exclusion reasons; `rating_head` switches to that snapshot atomically. Duplicate captures cannot double-rate. Late Resources exports are merged by match ID and compared on shared counters. Corrected earlier inputs replay subsequent matches rather than patching a total. Prior runs remain available for audit. Source tables are never rewritten. With this small history, full replay is simpler than maintaining incremental dependencies.

Offline commands from the project directory:

```powershell
py headless/match_ratings.py --dry-run
py headless/match_ratings.py
py headless_host.py review --no-open
py headless_host.py lobby-history
```

The first command is read-only. The second publishes a deterministic rebuild. The review command remains read-only against SQLite and regenerates the HTML snapshot. Both rating commands accept `--database`.

## Validation on 2026-09-05

### Explicitly adjudicated early exits (added September 7)

The `review --serve` page now records these decisions in the separate
`match_adjudications` table. A decision includes match ID, winning team, required
reason, timestamp, UUID, source and optional Robz confirmation. Native result and
metadata rows are preserved. The reader overlays the decision for display and
rating evaluation, retaining compatibility with older metadata-based declarations.
Insertion and rating publication share one transaction. An identical retry is a
no-op for the decision; conflicting submissions or an already-confirmed native
winner are rejected. A later conflicting native capture remains preserved and
excludes the match from ratings. No per-player counters are invented for a manual
decision. Progress-only matches can receive a winner/reason but remain unrated
when result identity evidence is incomplete.

An operator may explicitly confirm the winning team and Robz pool for a particular
match after an early exit. Store that declaration separately from native evidence
as `operator_adjudication` in match metadata, with `source` set to
`explicit_user_confirmation`, the exact `match_id`, `winning_team`, and `pool`.
The rating audit identifies the user-confirmed outcome and mod source. This allows
the early-exit outcome exclusion to be resolved without inventing a native finish
or missing player counters. Human identity, equal-team, capture-conflict and
attached-in-progress guards still apply. A point lead alone never creates this
declaration. Original raw captures remain unchanged.

- Baseline: 82 tests passed. Final: 98 tests passed; native bridge syntax checked with Node.
- Added reference moments, invariance, extreme upset numerical checks, no score bonus, eligibility/identity failures, capture conflicts, concurrent/repeated rebuilds, late Resources, interrupted transactions, frozen parameters, corrected chronological history, review and greeting lookup coverage.
- Two real-match regression fixtures: 8v8 River Valley, then 6v6 Kalinina; 21 distinct players, seven appearing in both. All remain provisional. Six other saved matches are excluded.
- River Valley: Team B probability 50%; winners 1059.47, losers 940.53 from a 1000 prior. Kalinina: Team B probability 44.4632% using only River Valley history; Team B wins. Examples: Player09 940.53 → 1015.14; Player17 1059.47 → 984.86; Player02 1059.47 → 1134.08.
- [Detailed audit](../validation/rating_20260905/report.json), [historical regression inputs](../tests/fixtures/rating_history.json), and a SQLite pre-rating backup are preserved. Every pre-existing source-table hash was unchanged after publication; dry-run, published and repeated rebuild outputs matched.
- No live chat was sent or game started during this implementation. Rating lookup integration is tested offline; actual greeting transport was tested in the earlier lobby-social work.

## Desert Town loop

Load Robz and select **3v3 Big Desert Town / Battle Zones** in the game. The bot uses the game's remembered map. The expected-map option prevents automatic starts on another map; it does not select a map for you.

```powershell
py "headless_host.py" friends-host --minimize --min-players 2 --rating-profile robz-battle-zones --expected-map "multi/3v3_big_desert_town:battle_zones"
```

This launches/reuses the game, prepares Alliances and spectator settings, moves the host to spectators, waits for equal human teams with everyone ready, starts after the stable countdown, observes natural completion, saves results, exits and returns to the lobby for the next match. It runs until Ctrl+C or `friends-stop`. Change `--min-players 2` to `6` to wait for a full 3v3; the spectator host does not count. A stopped recorder does not keep observing; start the command above to run the new code.

```powershell
py headless_host.py friends-status --follow
py headless_host.py friends-hold
py headless_host.py friends-resume
py headless_host.py friends-stop
```

The next operational gate is a **supervised multi-cycle spectator run with real clients**, including natural completion, result saving/dismissal, the next ready/start cycle, and disconnect/restart recovery. A long unattended soak has not been demonstrated. Ambiguous native state, manual early exit, incomplete results or game failure stop for attention; automatic crash relaunch and unconditional recovery are not implemented. Rating calculations do not remove these lifecycle limitations. Begin supervised looping with the command above; do not yet treat it as a proven unattended service.

The individual-performance TrueSkill 2 model remains deferred by the user's fallback decision. It needs reliable telemetry, parameter fitting and chronological held-out evaluation before publication. Reference: [Microsoft's TrueSkill 2 paper](https://www.microsoft.com/en-us/research/wp-content/uploads/2018/03/trueskill2.pdf).
