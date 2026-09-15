# Public source and local data

The public source includes an [anonymized SQLite sample](../examples/README.md).
Live databases, chat history, run evidence, archives, installed tools, game dumps,
credentials, build output, and caches are excluded by `.gitignore`.

Keep your local `data/` folder to retain results, ratings, and archived replays.
Run `py headless_host.py review --serve` from the project root to review them.
Only `examples/rankbot.sqlite3` is intended for public distribution.

## Publish a clean snapshot

This public repository starts from a clean source snapshot with fresh Git history.
Older private development history is not included. Continue to keep live data,
test captures, and local credentials out of future commits: `.gitignore` does not
remove files that have already been tracked.

## Fixtures and historical evidence

Test fixture names, player IDs, and lobby IDs are anonymized consistently with
their assertions, including split numeric IDs and compressed replay result blobs.
Fixture `.qm` files contain synthetic begin/end framing without original gameplay
packets. They exercise importer validation and are not playable replays. Numeric
statistics are retained for regression coverage.

Historical documentation uses anonymized player labels. Links into `archive/`
and `validation/` refer to local evidence omitted from the public source.
Offline test results do not establish current live-game stability.
