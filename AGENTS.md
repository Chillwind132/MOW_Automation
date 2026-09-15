# MOW Automation: start here

## Locate the current project

Resolve the project root from this file's directory; do not assume a user path.
The docs are in `docs/` underneath it. `Applications/MOW/_Automation` and
`headless/_host.py` are not paths in this checkout. Confirm paths on disk when a
pasted command uses those spellings; do not create a duplicate project to match them.

Read [docs/INDEX.md](docs/INDEX.md), then [current status](docs/STATUS.md) and the
[operating guide](docs/README.md). Use [structure](docs/STRUCTURE.md) for placement
and [reference](docs/REFERENCE.md) for status, stop and read-only data commands.

## Sources of truth

- The root `headless_host.py` is the supported CLI entry point, forwarding to
  `headless/headless_host.py`. Modify the implementation, not a copied root module.
- Host orchestration, the guarded Frida bridge and GM prompt live in `headless/`.
  Shared data readers/writers live in `modules/live_game_data/` and
  `modules/end_game_results/`; see [module contracts](docs/MODULES.md).
  Optional diagnostic/campaign utilities live in `diagnostics/`.
- Current code defines behavior. Dated run evidence establishes what was actually
  observed. Tests establish offline checks, not live-game stability.
- `archive/` contains superseded implementations and notes. Read its status banner
  and index before using it; old plans, commands and claims are not current instructions.
- Keep `data/` and `validation/` paths stable: stored records and patch manifests refer
  to them. Find any moved source through `archive/reorganization/moves.json`.

## Behavior to preserve

- **Tactical AI architecture, user decision September 7, 2026:** act as the local
  player through the ordinary native player-command/transport path, including
  when joining another host. Read
  [the migration and validation plan](docs/TACTICAL_PLAYER_COMMAND_MIGRATION_PLAN.md)
  before tactical/native changes. Keep policy and scoring external; observe
  existing owned/team-visible state. Do not add extra live native cover/path/AI
  evaluations, direct gameplay-property edits, checksum spoofing or sync bypasses.
  This supersedes older plan suggestions for native queries/brain edits. A query
  name does not establish read-only behavior. Preserve closed capability gates;
  ordinary-command fidelity and independent-client agreement must be validated
  per role/action before claiming synchronization safety. Do not simply re-enable
  the previously failed `asPlayerCommand` experiment. See the plan for replacement
  cover/navigation behavior, negative tests and multiplayer acceptance gates.

- Native browser `numplayers` is not overridden. Internal start readiness excludes spectators.
- `--record-only` rejects game actions in Python and JavaScript. It still attaches
  Frida and installs observation hooks; it is not a zero-instrumentation mode.
- Ordinary auto-start requires the configured player count, balanced ready teams and valid
  map/settings/identity checks. Unanimous `/start` votes allow fewer/uneven human
  players with all players ready and both teams occupied. Preserve vote invalidation,
  durable recovery and native start guards.
- Normal hosting/recording does not run experimental audio resets, heap cleanup,
  or automatic crash relaunch. Direct CLI launch uses `-no_reload_caching`; an
  existing process keeps its original launch arguments. Automatic human friends-host
  replaces MOW after each replay-saved completed match and confirmed lobby return;
  this planned restart is separate from crash recovery. Players must rejoin.
- Greetings are plain and once per player/lobby initially, then once per newly
  completed game on an observed post-game rejoin, with the automated-lobby
  welcome, database game count and explicit rating state (no stored rating: unrated;
  available ratings retain their provisional marker). Definite native no-send
  rejections may retry after a later same-lobby entry; uncertain sends may not.
  Early-start voting has explicit offer/progress/reset notifications; ordinary
  readiness checks have no separate countdown or rating announcements. GM defaults and aliases are in the CLI
  parser and `headless/game_master.py`; keep the guide synchronized with both.

## Validate and report

Use `py tests/run.py` (or append selected module names) and
`node --check headless/headless_host.js` as appropriate. The runner works from any
working directory. CLI `--help` and `matches --json` can verify paths without
launching or attaching to the game. Do not launch games just to test imports or help.

Before changing files used by a running controller, inspect its actual process
command line. A running process retains loaded code until restarted. Keep changes
small; do not combine routine fixes with experimental native memory operations.
Update relevant docs when behavior or paths change. Report exactly what was tested,
and distinguish an exited process from a proven crash or proven cause.
