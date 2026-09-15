# Real match data, anonymized for sharing

`rankbot.sqlite3` is a standalone sample with **93 saved matches** and recorded
ratings, including six rated matches. Statistics, teams, outcomes, and timestamps
come from real games. Player names and Steam/lobby identities are replaced with
consistent synthetic values. This is a visual reference, not a live rating pool.

On a fresh installation, create `data/` and copy `examples/rankbot.sqlite3` to
`data/rankbot.sqlite3`, then run `py headless_host.py review --serve` from the
project root. Do not overwrite an existing local database.

The sample retains match/result records, rating history, player experience, and
participation events. Chat, credentials, local paths, command logs, raw UI captures,
and playable replays are omitted. Replay-derived display settings are retained
in match metadata so the review does not require the original replay files.

The working installation's `data/` folder remains private and unchanged.
