# Current implementation and evidence

Reviewed **2026-09-06** against this checkout. This is a handoff, not a live status feed.
Use `py headless_host.py friends-status --json` and the actual process command line
to inspect a running instance. Restart the controller to load source changes.

## Planned restart after completed human matches (September 10)

Automatic human `friends-host` now saves the authoritative replay and confirms
lobby return before replacing the game process. Windows process creation identity
is checked on the termination handle, exit is confirmed before direct minimized
launch, and the existing controller reattaches and prepares the new lobby with
its CLI policy intact. Players must rejoin. Hold/Stop use the same control session;
restart/setup polling keeps its heartbeat alive. Launch/exit/save failures stop
for attention rather than retrying indefinitely. Record-only and diagnostic AI
runs retain their existing behavior. No native heap/cache cleanup was added.
Offline guard and lifecycle tests cover this change; live validation is pending.

## Players-mode crash correction (September 9)

Run `run_20260909_210457_100686` crashed during lobby settings refresh after
configuring Players with the incorrect enum 0. The installed executable's
native table identifies `player` as **2**; 0 has no label. This matches the
reported null read at `0x0043f75a`. Configuration, readiness and review display
now use 2, and the bridge validates the native enum label before setting it.
Regression tests read the executable table independently and check rejection
before mutation. Live hosting after this correction remains unverified.
See [crash evidence](../validation/run_20260909_210457_100686/players_enum_crash_analysis.md).
Restart the controller and crashed game before using `--army-selection players`.

## Implemented

- September 9 greetings: definite native rejections (`mutationStarted: false`)
  are stored as `not_sent` and retry only after a later same-lobby native entry.
  Uncertain delivery remains protected against duplicates. Greetings always show
  the rating value (with its provisional marker) or `Rating: unrated.`; initial
  delay is now 1–3 seconds, with existing message spacing and native recipient
  checks preserved. All 467 offline tests and JavaScript syntax validation passed.
  Player08's September 9 17:47:14 rejection was reclassified using the recorded native
  no-mutation result; its original record was archived. Controller restart and
  live rejoin/delivery validation remain required.


- September 8 early-start live verification: match
  `ac790427-ac54-4350-950e-e5290fcc7de3` started once after both human votes,
  ended naturally at Team B 160–41, archived and imported its replay, updated
  both DB ratings, and returned to the lobby. The review API served replay finals.
  A stale cancellation notice appeared after completion: the successful Start
  used the same reset path as cancelled votes. Successful starts and active matches
  now clear votes silently; genuine lobby cancellations still notify. All 33
  early-start/host tests passed. Existing controllers need a restart for this fix.


- September 8 early-start voting: all ready human players on opposing teams may
  unanimously type `/start` to start with fewer or uneven players. Exact voter
  identities and roster approval reach the native guard. Votes reset on changed
  context, Hold, lost observations and restart. Existing automatic starts still
  require a full balanced lobby. Offline validation only; the currently running
  host must be restarted to load this feature. The full 455-test suite passed;
  after the final generation guard and three additional tests, all 31 focused
  early-start/host tests and JavaScript syntax validation passed. See the operating guide.


- September 8 winner policy and editor: Battle Zones automatic winners require
  the recorded winning team to reach Final VP, using archived replay settings
  before lobby metadata. Early or incomplete evidence stays undetermined. Tile
  gear buttons open a side panel for Team A/B, a required reason and confirmation;
  manual decisions have a tile badge and a reason card below results. Raw evidence
  and previous rating runs are preserved. The 445-test suite passed, plus the
  archive-to-rating integration check; desktop/mobile Edge save and reload flows
  passed against a temporary database copy. Existing controllers retain loaded
  rating code until their next restart.

- Review army columns: player rows lead with Player, Rank, Army Mode, Player Army,
  Team. Players mode preserves individual nation choices; Teams uses the
  configured nation; Alliances shows the recorded alliance; Player Army shows the chosen nation.
  Team VP remains explicit. Archived replay settings take precedence over older
  lobby metadata for this display; unavailable settings are not guessed.

- Rank-icon serving fix: the localhost CSP explicitly permits embedded `data:`
  images. The prior default blocked the valid PNGs in served review pages.
  All 14 review-service tests pass; all 11 embedded PNGs validate.

- September 8 module migration: shared native observations, identities, snapshots
  and participation are in `modules/live_game_data/`; replay parsing, archiving
  and final persistence are in `modules/end_game_results/`. Host/observer/bot
  modes use these APIs; old source paths remain compatibility shims. Solo/run
  modes now associate loaded generations with durable recording identities.
  All 437 tests passed. Two bot games verified natural and manual-exit replay
  imports; host/watch/record-only handoffs preserved one match ID. See
  [module contracts and evidence](MODULES.md) for entry points and validation.

- September 8 review polish: one table for live/replay results, five-second
  automatic refresh, filter requiring a human on each opposing team, original game rank images with exact
  recorded games-played tooltips, and evidence-based leaver reasons. Summary cards
  and diagnostic panels are removed. All 430 tests passed; desktop rendering and
  filter/tooltip/refresh interactions checked.

- September 8 recording: live snapshots now include validated native player
  infantry/vehicle kills and losses, score, resources and team VP. Final results
  come only from completed persisted replays, imported by a separate one-second
  watcher that survives game/controller exit. All five current replay files were
  imported; original UI records are archived, never used to fill replay fields.
  The Player21/AI test matches the replay screenshot, including vehicles and special
  resources. Player20's original replay itself contains the reported zeros.
  HUD ownership changes now invalidate/retry the sample instead of stopping the
  recorder. See [recording evidence and field mapping](RECORDING_STATISTICS.md).

- September 7 tactical follow-up: movement progress recovery, defensive cover
  retention, bounded AT repositioning, corrected native purchase composition and
  age-based scheduling are covered by 402 passing tests. A match against three
  Heroic bots ended in a verified 200–110 victory, with controller restarts during
  the match. Subsequent paired-group continuation and immediate result cleanup
  changes remain offline-tested. Guarded archival recovery subsequently saved the
  hidden final statistics and restored the lobby lifecycle; its full suite passed
  405 tests. A fresh AI-only trial was then refused because remote humans had joined.
  See [army operations](TACTICAL_ARMY_OPERATIONS.md)
  for source-version limits, evidence and remaining native feature gates.

- `review --serve` now runs a small standard-library localhost service, separate
  from the recorder. Unresolved matches have Team A/B winner buttons and a required
  reason. Immutable manual decisions and rating publication commit together in
  SQLite; captured evidence is preserved. Browser refresh reads current data;
  there is no automatic polling. The generic transport and review routes are
  separate modules. All 372 tests passed, including real local HTTP requests and
  the page-script button flow with a DOM test double. Native-game behavior was
  not exercised by these service tests. Existing recorder processes need a restart
  to read the new adjudication table during future rating rebuilds.

- Both friends-host modes and `watch` now persist initial and periodic roster/HUD
  snapshots to SQLite (30 seconds by default; `--snapshot-seconds` is configurable).
  Participation and session events flush the latest valid sample immediately.
  Snapshot times distinguish sampling from later failure/closure recording. Review
  shows unfinished matches and progress history; snapshots never feed ratings.
  Per-player live statistics were unavailable in that build (added September 8);
  automatic rage-quit attribution remains unavailable.
  The full 359-test offline suite, CLI help from outside the checkout and bridge
  syntax check passed on September 7. Live validation and controller restart remain
  required. See [participation](PARTICIPATION.md).

- Automatic human spectator hosting and manual `--record-only` recording share the
  current Frida bridge. Only automatic mode configures the lobby or starts/exits matches.
- The spectator-excluding browser count override was removed. Neither mode writes
  `numplayers`; internal readiness still excludes spectators and requires the exact
  configured playing capacity (`--min-players`, despite its name).
- A cold startup with no engine/page waits for a recognized page and a moving heartbeat.
  Human match loading has a separate ten-minute default allowance. In run
  `20260906_185445_294297`, the second match's generation appeared after the old
  two-minute timeout; a subsequent read-only probe confirmed active gameplay and
  a changed generation. Generation and roster identity guards remain required.
- Once-per-minute `[HOST]` output includes PID, tick count and page. Failure evidence
  includes the Windows exit code when available, last command, social-read step,
  last sampled engine state, source hashes and tracebacks.
  CLI stdout/stderr now escape characters unsupported by the current encoding.
  In live run `20260906_141415_519008`, a Unicode player name caused the cp1252
  roster print to terminate the controller at 18:52:29; the game stayed alive.
  Twenty-nine host tests passed after the output fix, including cp1252 and UTF-8
  regression checks. Player names in stored records are unchanged.
- Chat scans avoid rescanning the chat panel while locating it, omit unused raw
  headers, and have a 100 ms traversal budget. Failed social polls invalidate cached
  chat snapshots. This reduces scan work; it is not proof of crash prevention.
  The locator now checks only direct lobby-page children. During live run
  `20260906_132510_882801`, an unrelated user-profile panel exceeded the general
  512-child bound and caused repeated `Invalid UI children` errors during chat
  lookup. The scoped lookup avoids that subtree and retains panel uniqueness,
  ownership, vector and channel checks. Seventeen relevant offline tests passed;
  three-game live validation is still pending.
- Greetings name each joining player, explain automatic lobby start, and append
  saved game counts and available ratings (zero games: provisional). There are no
  separate ready/countdown announcements. Optional GM replies consider general new player chat. Current
  defaults are `ambient`, 12 context messages, 20-second cooldown, 45-second timeout,
  and 120 characters. `addressed` is currently accepted as a legacy alias for ambient.
- The rating model is the outcome-only `robz-outcome-v1` pool, with explicit eligibility
  checks. Participation evidence does not automatically impose conduct penalties.

## Memory behavior

Direct CLI launch includes `-no_reload_caching`. Attaching cannot change an existing
process's launch arguments; a Steam fallback does not guarantee this flag.
Normal human hosting and recording do not call experimental cache resets or heap
cleanup. Diagnostic tools must be invoked explicitly.

The low-texture setting and short replacement Robz menu-music asset were observed
installed on 2026-09-06. They are persistent installation/preferences state, not
changes applied by `--record-only`. Recheck before relying on that observation.

## Validation and limits

On September 7, record-only match `c0b0abf5-bb1d-489a-833c-4164ec8b11f4`
retained its journal and raw evidence but missed the final scoreboard. Two full
UI discovery scans delayed the first statistics read by about nine seconds after
lobby detection; that read had no player UI rows. The next read lost the dialog.
Record-only capture now scans only for statistics, reuses that discovery for the
read, defers social polling while a match is pending, and retries after 250 ms
plus scan/read time. Raw reads are also saved under the match ID before parsing.
Native reads recheck dialog visibility and type. Restart the controller to load
the change. Brief-dialog live validation remains pending; this is not a guarantee
that every five-second results display can be captured.

The reorganization passed **173 active tests**, plus one archived handoff test in
isolation. CLI help, diagnostic entry points and a read-only database query passed
from `C:\Windows\System32`. See the [saved validation report](../archive/reorganization/validation.json).
These are offline/path checks; they do not establish a successful live match after
all subsequent edits. The user reported two successful record-only games before
these changes; that is not a fresh validation of the current build.

In [run 20260906_115624_154818](../validation/run_20260906_115624_154818/), remote
players joined and rejoined. No Start command was issued. At 12:46:27 local time,
Frida reported `process-terminated` and the host reported `script has been destroyed`.
The last command was a social probe. No matching Windows crash report or new dump
was found in that investigation. The termination cause remains unknown; the last
probe is a lead, not proof of causation. The newer diagnostics were added afterward.

There is no automatic crash relaunch or established guarantee for unattended human
multi-match stability. Do not turn old AI campaign batch sizes into a memory-safety
threshold. Keep results visible until saved; incomplete identity or result evidence
can stop recording for attention.
