# Public-source preparation — 2026-09-14

- Root README has record-only, automatic Robz hosting, and review-server commands.
- Personal checkout paths and captured player names/identities are anonymized
  in published documentation and fixtures, including compressed replay results.
- `examples/rankbot.sqlite3` contains 93 real saved matches, including six rated
  matches. Identifying fields are anonymized; chat, command logs, private paths,
  raw captures, and original gameplay packets are omitted.
- Sample outcomes, victory-point targets, and army modes match the local original.
- Original local SQLite database files were verified unchanged with SHA-256.
- Live data, evidence, archives, tools, credentials, and generated output are
  ignored. Previously tracked editor/build output was removed from the index.
- Pattern-based checks of public text, SQLite fields, compressed replay results,
  and split numeric identities found no matching credentials, personal paths,
  or original player IDs. This is a scoped scan, not a guarantee against every
  possible secret format.
- All 475 regression tests passed. Bridge syntax and CLI help passed. Sample
  SQLite integrity/foreign-key checks passed; the real review server returned
  successful HTML and JSON responses for all 93 matches.

## Live README command checks

The release copy was tested on Windows with Python 3.14 in a new virtual
environment installed from `requirements.txt`; all 475 tests passed.
The exact review command opened the browser and served 93 sample matches.

Record-only successfully cold-launched the game, attached Frida, observed the
main menu, and subsequently observed a live lobby without game-control actions.
Automatic hosting created the lobby, moved the host to spectator, configured
four playing slots, verified the requested map and Russian Guards/Germany team
armies, and remained minimized. A subsequent run observed a joining remote
player, sent the normal greeting, and waited for player readiness.
All four timed hosting runs returned successful summaries and stopped cleanly.

These checks used `--run-seconds` to bound hosting duration. No complete match
was played, so end-to-end match completion and the restart loop remain unverified
in this release check. Raw live evidence stays private and is not committed.

The public repository starts with a new root commit; private development history
is not included. See [publishing](PUBLISHING.md).

Local build/cache directory deletion was rejected by automatic approval review
as “blocked by policy.” Those directories remain local and are excluded from the
public source and ZIP.
