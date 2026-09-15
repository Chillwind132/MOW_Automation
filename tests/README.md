# Regression tests

Current documentation: [start here](../docs/INDEX.md).

Run `py tests/run.py` from the project root, or use the runner's absolute path.
Append module names to select tests. `py -m unittest discover -s tests` also works
from the project root. Node is required for tests of the production Frida JavaScript.

`fixtures/` contains anonymized captured inputs. Replay stream fixtures retain
only synthetic completion framing, with no original gameplay packets; the result
blobs preserve numeric statistics with synthetic identities. See
[public-release notes](../docs/PUBLISHING.md). `statistics_probe_harness.js` executes the
actual bridge reader against synthetic memory backed by those fixtures.
`_test_paths.py` resolves active code and fixtures. Tests use temporary databases;
they do not host games or send real chat.

The campaign-specific handoff test moved with its obsolete script to
`archive/experiments/test_resumed_run_handoff.py` and is excluded from this active suite.
