# Run → play → review

Start with the [documentation index](INDEX.md) and [current status](STATUS.md).
Run commands below from the project root. For setup and the three main commands,
see the [project README](../README.md).

Run one command in PowerShell. It launches the game, or uses the game already running. Keep the terminal open.

**Play/host manually; only record results:**

```powershell
py "headless_host.py" friends-host --record-only
```

Do everything else in-game. Final results are imported only from completed saved replays; you do not need to keep Game Result visible. An independent replay watcher starts automatically and continues after the game or controller closes. It checks once per second and waits for stable files and complete replay markers. The recorder never changes settings, starts matches or closes results.

Replay archives are kept in `data/replays/`; watcher activity is in `data/replay_importer.log`. To import existing replays without attaching to the game, run `py -m modules.end_game_results`. Add `--watch` to watch continuously, or use `--stop` to stop the watcher. A controller starts it again on its next attachment. Missing or incomplete replays remain pending; UI and live counters are never substituted as final results.

Both `friends-host` modes now save progress to SQLite on the first valid gameplay
observation and every **30 seconds** afterward. Add `--snapshot-seconds 15` (or
another positive number) to either command to change that interval. Participation
changes, return to lobby/browser, game-process exit and controller shutdown also
flush the latest available sample immediately. These samples preserve roster and
raw HUD observations and native per-player kills/losses, score and resource pairs
when the native data and player identities can be verified. Missing counters
remain unavailable. The review shows the latest live counters in the main results table, then
replaces them with final replay results. The local page refreshes every five
seconds and preserves the selected match and filters. See [field mapping and validation](RECORDING_STATISTICS.md).
Snapshots never determine a winner or change ratings.
The review's left navigation switches between **Saved Games** and **Player Rating**.
Player Rating lists rated humans by their current published Robz rating. Select a
player for their rating trend, rated win rate, recent change (up to five rated
matches), and saved match history. Unrated results remain marked as such; they do
not affect rating statistics. Click a map in the history to open its saved game.
Each view keeps its search while switching, and live refresh preserves the view
and selected player. Restart the review service after updating its page code.
Unfinished matches appear in `review` with their latest observed counters. Final
results, or an explicit user adjudication, remain separate from progress data.
Restart the controller to enable this on an existing run. See
[participation and closure evidence](PARTICIPATION.md) for attribution limits.

**Automatic spectator host:**

```powershell
py "headless_host.py" friends-host --minimize --min-players 2 --rating-profile robz-battle-zones --expected-map "multi/3v3_big_desert_town:battle_zones"
```

Load Robz and select 3v3 Big Desert Town / Battle Zones first. Sets Alliances and spectator hosting; starts when everyone is ready on equal-sized teams. The map guard waits if another map is selected. Change `2` to your expected player count. Run before friends join.

To have the host select **Teams** mode with **Team A = Waffen-SS** and
**Team B = USA**, use both nation options:

```powershell
py "headless_host.py" friends-host --minimize --min-players 4 --rating-profile robz-battle-zones --expected-map "multi/3v3_big_desert_town:battle_zones" --team-a-army ger_ss --team-b-army usa
```

Run in a hosted lobby before other players join. The host configures the team
nations, enables spectators and sets four playing slots. Players inherit their
team's nation. Automatic starts recheck Teams mode and both configured nations;
changed settings stop the countdown. Omitting both flags retains Alliances mode unless
`--army-selection` is supplied.

For **Players** mode, allowing each player to choose any nation available in the
loaded mod, omit both team-army flags and use:

```powershell
py "headless_host.py" friends-host --minimize --min-players 4 --rating-profile robz-battle-zones --expected-map "multi/3v3_big_desert_town:battle_zones" --army-selection players
```

Start before other players join. The host sets Players mode and verifies it again
before automatic or unanimous-vote starts; every player must have a nation and
be ready. `--army-selection alliances` explicitly selects Alliances; `teams`
requires both team-army flags. Restart an existing controller to load this option.
Players mode has offline guard coverage; live hosting remains to be verified.

Automatic hosting allows up to ten minutes for player loading and a new native
match generation (`--loading-timeout 600`). This is separate from the ordinary
command/setup timeout. The gameplay page can appear before all clients finish
loading; the host still requires a new generation and the acknowledged roster
before associating the match. Expiry preserves the game for recovery.

The host now includes `-no_reload_caching` whenever it launches the game
executable. This survives closing and reopening the game through this command.
Attaching to an already-running game does not change its launch arguments.
If executable launch fails and the host falls back to Steam, it reports that
the flag is not guaranteed; add `-no_reload_caching` in Steam's launch options
for that path or for launching manually through Steam.

Automatic human `friends-host` now **restarts MOW after every completed match**.
It first imports the completed replay, saves results, and confirms return to the
lobby. It then terminates that verified game process, waits for its exit, and
launches the same executable minimized with `-no_reload_caching`. The controller
reattaches and prepares a new spectator lobby using the remembered map and the
same CLI capacity, army-selection, map guard, rating and lobby-name settings.
**Players must rejoin the new lobby.** No additional flag is needed.

Hold remains in effect across the restart; Stop cancels further restart/setup work
at the next poll. Stopping the controller still leaves any currently running game
open. A missing replay, uncertain lifecycle, failed exit or failed launch stops
hosting for attention; there is no automatic crash-relaunch loop. Record-only
mode and diagnostic AI runs do not use this restart policy. Restart the controller
to load this change. Offline restart tests pass; live multi-match validation is
still required. Experimental cache/audio/heap resets remain disabled.

Lobby observation now records each human's games played and games-played badge tier, plus the separate ranked-games count when its tooltip is available. Both hosting modes save lobby chat snapshots every five seconds. Record-only mode never sends chat.

Automatic hosting greets each remote human on their first visit to a Steam lobby, with a random
1–3 second initial delay and 5–12 second spacing:
`Hi PLAYERNAME! This is automated MOW lobby. The match will start as soon as lobby is full. Games: 8. Rating: 1200.`
Games counts saved matches in our database where that Steam ID played as a human,
including unrated results; duplicate captures count once, and unfinished matches
and spectating do not count. The native lifetime games badge is separate.
Every greeting includes the rating state. Without a stored rating it ends with
`Rating: unrated.`, including zero-game players. Available ratings include their
value and `(provisional)` when the rating model marks uncertainty as provisional.
When every playing human has checked Ready and both teams have a player, the bot
invites each player to type `/start`. Unanimous votes allow an early start (1v1,
2v1, etc.) without filling the lobby. Spectators do not vote. Ordinary full-lobby
automatic starts still require balanced ready teams; map/settings, identity,
recovery and native Start guards apply to both paths.

Votes reset on roster, team, name, nation, settings, map or readiness changes,
Hold, observation gaps, controller restart, and each new match. Old chat and
repeated votes do not count; ambiguous display names cannot vote. Notifications
report the team sizes, vote count, cancellation, and any wait for the native Start
gate. Messages share the five-second chat rate limit and preserve typed input.
Chat is sampled every five seconds, so commands can take that long to appear.
A full lobby can still start automatically without votes.
After a newly completed game is saved, leaving and rejoining the lobby allows
one new greeting with the current saved game count and database rating. Native
Steam entry events detect fast rejoins between social polls. Staying in the lobby
or reconnecting repeatedly without another completed game does not repeat it.
The previous greeting is archived; uncertain sends are not retried for that game.
A native rejection explicitly reporting `mutationStarted: false` is stored as
`not_sent`; a later observed entry into the same lobby permits a fresh greeting
without requiring another completed game. Restarting alone does not permit a retry.
The replay must be imported before a repeat greeting is eligible.
Holding pauses greetings and starts. The bot preserves text being typed and never
retries an uncertain greeting after reconnecting.
Record-only mode never sends chat. Restart an existing controller to load changes.

The game publishes its normal lobby player count. The spectator-excluding
`numplayers` override was removed on September 6; neither hosting mode changes
that value. The host's internal readiness check still excludes spectators.

To advertise **★ ROBZ 2v2 ★** in red, append these options to the automatic host command:

```powershell
--lobby-name "★ ROBZ 2v2 ★" --lobby-color ff0000
```

This overrides only this host's Steam lobby `hostname` metadata, preserving the
Steam profile nickname. Native metadata refreshes retain the override while
the controller runs. Omit both flags for the game's normal name on future
launches. Color takes six RGB hex digits; names must be plain text (1–64
characters). The native lobby-list preview verified the red text and star
glyphs; a separate Steam lobby-list query verified the published hostname.
Automatic hosting also accepts the already-open Internet lobby browser.

### Optional game master

Chat behavior is defined in `headless/game_master_prompt.md`: a strict playbook
for map/mode requests ("we playing this"), other settings ("keeping these settings"),
spectator questions, invitations to play ("i'm hosting"), start requests and match
size. Kick/ban requests, pushback after rejected changes, bot questions, insults,
bait and all other topics get silence. Replies cannot change maps or settings. Each generation launches
a fresh child that reads this prompt; prompt-only edits apply on the next request
(an already-running generation may still use the previous text).

```powershell
py "headless_host.py" friends-host --minimize --min-players 4 --rating-profile robz-battle-zones --expected-map "multi/3v3_big_desert_town:battle_zones" --team-a-army ger_ss --team-b-army usa --game-master --gm-model gpt-6-astra --gm-reasoning low --gm-mode ambient --gm-cooldown 20 --gm-timeout 45 --gm-context 12 --gm-max-chars 120
```

Uses the installed `codex exec` and existing **ChatGPT sign-in**; run `codex login`
if needed. Tokens are not copied into this project or passed on the command line.
API-key environment overrides are removed for the child, and ChatGPT authentication
is required. The implementation requires ChatGPT sign-in and has no API-key fallback;
account/model access still applies. Model generation happens through OpenAI, not
locally on the game machine. Recent player display names, chat and lobby settings
are sent as context. Steam IDs are kept out of model input.

| Option | Default | Meaning |
|---|---|---|
| `--gm-model` | `gpt-6-astra` | Exact model passed to Codex; unavailable models do not silently fall back |
| `--gm-reasoning` | `low` | Reasoning effort; support depends on the chosen model |
| `--gm-mode` | `ambient` | Considers general new player chat; `addressed` currently acts as a legacy alias for ambient |
| `--gm-cooldown` | `20` | Minimum seconds between requests, plus 0–5 seconds of jitter; new messages can be deferred |
| `--gm-timeout` | `45` | Generation deadline in seconds; a failure stays silent |
| `--gm-context` | `12` | Recent chat messages (allowed 1–30), each capped at 400 characters |
| `--gm-max-chars` | `120` | Reply character limit, maximum 128 |
| `--gm-dry-run` | off | Generate and log without sending model replies; ordinary greetings still run |
| `--gm-quiet` | off | Suppress game-master console traces; evidence logs remain |

Game-master console traces are on by default: `[GM HH:MM:SS]` lines show startup,
incoming request, model, context count, generation duration, proposed text,
submission, silence, discarded replies and errors. `[CHAT]` lines show greeting
scheduling and sending. These are operational events, not private model reasoning
or credential dumps. Player text is JSON-escaped for safe console display.
Replies pause 1–4 seconds after generation; request cooldown adds 0–5 seconds
of variation. Context and Hold/Stop are checked again after the delay.

The personality is in [game_master_prompt.md](../headless/game_master_prompt.md). It favors
brief, relaxed conversation, silence when appropriate and honest answers about
being automated. Early-start vote notifications are sent by the controller independently of the GM.
The model can propose a reply or silence; it has no game-control actions. Codex
runs asynchronously with user config/rules excluded, read-only sandboxing, and
shell, web search, apps, image tools, hooks and multi-agent features disabled.
Only validated JSON replies can reach the existing guarded native chat sender.

Replies are dropped if their context becomes stale, players leave, the host is
held/stopped, or the chat input is busy. Duplicate/ambiguous display names are
skipped. Existing history is ignored on attachment. `game_master_replies` in
`data/rankbot.sqlite3` records requested/submitted/dry-run/failed states; uncertain
sends are not retried. This is lobby chat only, not in-match chat.

The local authentication check and exact child CLI arguments are defined in
[game_master.py](../headless/game_master.py).

**Review captured player experience and recent lobby chat:**

```powershell
py "headless_host.py" lobby-history
```

Add `--json` for timestamps, source information, lobby IDs, and greeting status. This reads the database without attaching to the game. Tables: `player_experience`, `lobby_chat`, and `lobby_greetings` in `data/rankbot.sqlite3`. Chat history contains messages still present in the native lobby UI at each poll; messages removed between polls can be missed. Sender names are preserved, but historic chat messages are not guessed onto Steam IDs.

**Review saved matches visually:**

```powershell
py "headless_host.py" review
```

Opens a searchable browser snapshot. Rerun to include new matches. Data persists in `data\rankbot.sqlite3`; eligible matches use the
[outcome-only rating policy](RATINGS.md), not Elo.

To record a winner and a required reason from the review page, start the local
review service in a separate terminal:

```powershell
py "headless_host.py" review --serve
```

Keep that terminal open. The page refreshes results every five seconds.
"Players only" is the default filter.

For Battle Zones, an automatic winner must have reached the recorded **Final VP**
target, with the other team below it. The archived replay's `scoreFinal` takes
precedence over recorded lobby settings. Early results and missing target/team VP
evidence show **Winner undetermined**, even when the raw replay contains a winner
flag. Raw evidence remains unchanged.

Click the gear button on a match tile to open winner settings in a side panel.
Choose **Team A** or **Team B**, enter the required reason, then click **Confirm
winner**. Selecting a team or typing a reason does not save. Confirmed manual
outcomes have a **Manual winner** label on the tile and a reason card below the
results table, including the chosen team and confirmation time. Closing the panel
keeps the unsaved draft while the page remains open.

Decisions are immutable and commit with eligible rating updates in one SQLite
transaction. Other tabs receive the update. Completed automatic winners and
existing manual decisions can be inspected in the panel but not overwritten.
Missing identities or an undeclared Robz profile can still exclude manual results
from ratings.

`review --no-open` remains a static file export. Static files show recorded
decisions but cannot write SQLite; use the service page for the buttons. The
service has no game attachment or game-control actions. Ctrl+C stops only the
review service. Restart an older recorder once to load support for reading manual
decisions during its future rating rebuilds.

**Live status** (second terminal):

```powershell
py "headless_host.py" friends-status --follow
```

**Stop:** Ctrl+C in the controller terminal. The game stays open.

Manual quit recording has prior live evidence. Other result layouts and unattended
human multi-match stability require further validation; see [current status](STATUS.md). [Extra controls and SQL queries](REFERENCE.md).


[Departure/rejoin capture and proposed discipline policy](PARTICIPATION.md): both runner modes now preserve participation evidence. Penalties are disabled; the native quit/disconnect signal still needs a real-client live test.

## Diagnostics and source layout

The root `headless_host.py` command forwards to `headless/headless_host.py`.
The database remains under project-root `data/`. New run evidence defaults to
`validation/`; `--evidence-root PATH` selects another directory or drive without
moving existing evidence. For a full system drive, the invoking process's `TEMP`
and `TMP` may also need a writable location for instrumentation temporary files.
A timestamped `[HOST]` heartbeat prints once per minute. On failure, the console
and run evidence report process exit information, the last command and chat-read
step, and available tracebacks. Read-only chat scans have a time budget and discard
stale snapshots on failure. These checks do not guarantee crash-free operation.

See [project structure](STRUCTURE.md) for active code, tests, diagnostics and archives.


For closed tactical testing, `start-ai --ai-victory-points 200` also accepts one
local host against exactly three opposing Heroic bots. It preserves the ordinary
native start gate, 10000 total manpower setting and exact roster approval. The
standalone production tactical `run` gate remains disabled pending validation;
see [tactical progress](TACTICAL_AI_PROGRESS.md) for diagnostic scope and results.

### Match-review presentation (September 8)

The page uses one results table: rank, nation, counters, skill/change and departure
status. "Players only" is the default filter and requires at least one human participant on each opposing team; bots may also participate.
The in-game rank icons are the original `ur_rank_00..10` assets from
`resource/interface.pak`, converted losslessly from TGA to PNG. Hover or focus the
rank image to inspect its exact recorded games-played count; unknown counts show
a dash. Historical ranks use the count recorded for that match.

Only active-play departure evidence marks a player as Leaver. Native callbacks
supply disconnected/kicked/banned/left reasons; a continuous roster disappearance
without a callback says the reason is unavailable. Observation gaps and normal
post-match lobby departures do not become leaver labels. Rejoins are shown too.
The former summary cards, progress-history panel and raw/debug sections have been
removed from the page; their underlying records are preserved.
