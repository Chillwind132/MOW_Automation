# Documentation index

Reviewed against the current checkout on **2026-09-06**.
Canonical folder: `docs`.
All short source paths in these docs are relative to the project root.

## Start here

1. [Current status and known limits](STATUS.md): implemented behavior, validation and unresolved failures.
2. [Operating guide](README.md): manual recording, automatic hosting, GM options and troubleshooting.
3. [CLI quick notes](notes.txt): copyable commands for the current machine.
4. [Controls and data](REFERENCE.md): stop/hold/status commands and SQLite queries.
5. [Project structure](STRUCTURE.md): source placement and stable data/evidence paths.

[Shared data module contracts](MODULES.md) cover live observations and replay-only finals.

## Find the implementation

[Autonomous Move-at-will implementation plan](TACTICAL_AI_IMPLEMENTATION_PLAN.md)
covers tactical behavior, operational goals, fortification and self-validation.
The user-selected [player-command migration plan](TACTICAL_PLAYER_COMMAND_MIGRATION_PLAN.md)
governs future tactical integration, joining-client support and synchronization tests.
The [synchronization audit](TACTICAL_SYNC_AUDIT.md) ranks native-call risks beyond
cover, distinguishes active battle paths from optional diagnostics, and records
the remaining multi-client validation gaps.
See [tactical implementation progress](TACTICAL_AI_PROGRESS.md) for implemented
code, local native trials and the remaining release gates.
The [army operations update](TACTICAL_ARMY_OPERATIONS.md) tracks utilization,
cover, AT engagements, adaptive purchasing, reserves and their validation limits.
Use [player handoff verification](TACTICAL_AI_HANDOFF_TEST.md) for the current
user-assisted direct-control test and next-session handoff.

| Topic | Source | Documentation / tests |
| --- | --- | --- |
| CLI, launch, attachment, failure diagnostics | [host](../headless/headless_host.py), [process diagnostics](../headless/host_diagnostics.py) | [host tests](../tests/test_headless_host.py), [exit tests](../tests/test_host_diagnostics.py) |
| Native bridge and observation hooks | [Frida JS](../headless/headless_host.js) | [statistics tests](../tests/test_statistics_summary.py) |
| Automatic spectator hosting and readiness | [friends host](../headless/friends_host.py) | [readiness tests](../tests/test_friends_host.py) |
| Manual recording and match identity | [recorder](../headless/match_recorder.py), [journal](../headless/match_journal.py) | [record-only tests](../tests/test_match_recorder.py) |
| Lobby experience, chat and greetings | [social](../headless/lobby_social.py) | [chat guide](LOBBY_SOCIAL.md), [tests](../tests/test_lobby_social.py) |
| Optional game master | [GM](../headless/game_master.py), [prompt](../headless/game_master_prompt.md) | [operating guide](README.md), [tests](../tests/test_game_master.py) |
| Results and ratings | [replay results](../modules/end_game_results/replays.py), [ratings](../headless/match_ratings.py) | [rating policy](RATINGS.md) |
| Departure and reconnect evidence | [participation](../modules/live_game_data/participation.py) | [participation guide](PARTICIPATION.md) |
| Memory experiments and resource patches | [diagnostic tools](../diagnostics/README.md) | [historical investigations](../archive/README.md) |
| Move-at-will AI feasibility | [read-only probe](../diagnostics/ai_feasibility_probe.py) | [evidence and validation gates](TACTICAL_AI.md) |

New agents should also read the root [AGENTS.md](../AGENTS.md). Historical notes are
indexed under [archive](../archive/README.md); do not treat their old launch commands
or superseded success claims as the current operating guide.
