# Player handoff verification and next-session handoff

Prepared September 7, 2026. The full tactical AI is unfinished and production
`run` remains disabled. The native Move at will setting alone does not activate
the new controller. Better combat performance against normal bots is an intended
outcome, not a demonstrated result.

Resumed-session update: automatic `input` now passes on both a leader and an
ordinary nonleader after allowing 750 ms between keys. `manual_move` also passed
real player-origin reclamation and stale-unit-revision rejection on nonleader 22.
The historical manual scene below is no longer required for those checks.
See the resumed implementation section in [progress](TACTICAL_AI_PROGRESS.md)
for source/evidence details and headless 120-unit trials. Same-value explicit
re-enrollment, full identity lifecycle and independent-client synchronization
still need their own validation; a fresh attachment is not same-session re-enrollment.

## Prepare the direct-control test

1. Use a multiplayer match against bots, with your own infantry available.
   Keep Windows unlocked and the game unpaused.
2. Put two owned infantry groups safely away from combat. The second group is
   a control for unintended changes to unrelated enrollment.
3. Set both groups to Move at will. Then select exactly one ordinary soldier
   from the first group, not its squad leader, a vehicle, or an allied bot's unit.
4. Leave direct control off. Keep that soldier selected and leave the game visible.
5. Tell the agent that the scene is ready. During the short automated test,
   do not press keys, click, change selection, or switch applications.

The agent must resolve the current game PID rather than reuse a historical PID.
Run `diagnostics/tactical_scenarios.py input --pid <current-pid> --output <new-path>`
from the project root. Set process TEMP/TMP to
`validation/local_archive/test_tmp`, use `py -B`, and use a unique
output directory under `validation/local_archive/new_runs`.

The existing scenario checks the installed bindings before sending input:
`]` for the mapped mode toggle and `E` for direct control. It requires real game
focus. Do not use `posted_input` or the obsolete `handoff` scenario as substitutes;
the latter's experimental player-emitter request is deliberately rejected.

## Expected evidence

The automatic sequence must demonstrate:

- Hold position clears enrollment.
- Move at will enables enrollment.
- Entering direct control sets the native control lock and clears enrollment.
- Leaving direct control clears the lock but does not re-enroll the soldier.
- Explicit Hold followed by Move at will restores enrollment.
- Unrelated units retain their enrollment, and native hooks restore on detach.

This checks control handoff. It does not measure combat strength or prove that
a previously pending order cannot execute. On failure, preserve the evidence and
inspect the soldier's actual mode; do not assume the original state was restored.

## Follow-up checks

Use a continuously attached observer while the user performs separately prompted
manual actions. A new attachment can adopt native Move-at-will units again, so
reattachment must not be mistaken for same-session re-enrollment.

Verify manual move and attack reclamation; deselection without reclamation;
an explicit same-value Move-at-will command after suspension; squad-wide scope;
and stale pending-order rejection after takeover. Do not claim these checks from
the direct-control sequence alone. Independent-client replication remains a
separate required test.

## Current evidence and outstanding work

The latest full offline suite passed 304 tests. Local native movement, stance,
cover arrival, shooting, reload cycles, pause/resume, one owned death transition,
and physical sandbag construction/orientation have evidence. Full ownership/ID
lifecycle, player reclamation, multiplayer replication, native cover quality,
runtime cover/build integration and combined tactical performance remain incomplete.
Native path queries now distinguish a requested endpoint from the engine's
boundary-clamped success result. A blocked-boundary preflight issued zero moves;
a valid route was followed to arrival. Withdrawal uses this preflight in the
guarded bot diagnostic, with bounded local legs. One native withdrawal arrival
and subsequent regrouping now have local bot-trial evidence. Combat superiority
remains unproven; see the latest progress entry for pending refinements.

Latest passive cover run `tactical_scenario_20260907_084445_183748` recorded 274
snapshots, 19 assessments, nine weighted requests with input records and ten with
target records. It issued zero orders, restored all 13 hooks, and timed out below
the ten-input-sample threshold. Result: observed, not a suitability pass.

C: previously filled, but the latest status check found 152,655,998,976 bytes free.
Keep new evidence on D: for continuity. The previously lost raw trace remains
lost and excluded from complete-evidence passes; freeing disk space does not
recover it. See TACTICAL_AI_PROGRESS.md for historical failures and limitations.

## User-assisted result, September 7

Recording: `validation/local_archive/new_runs/manual_handoff_20260907_090754_835785`.
The user selected Rifleman (AT), native ID 79, incarnation 1. The engine classified
this soldier as a squad leader; do not describe this as a nonleader runtime test.
The observer issued no autonomous orders. Native transitions were:

| Simulation tick | Observed result |
|---|---|
| 786804 | Move at will: enrolled, revision 1 |
| 789684 | Direct-control lock 1: suspended, revision 2 |
| 792144 | Lock cleared: still suspended, revision 2 |
| 802264 | Manual type-1 command while already suspended: revision 3 |
| 803584 | Hold position: suspended, revision 4 |
| 804244 | Explicit Move at will: enrolled, revision 5 |
| 807984 | Deselected: still enrolled, revision 5 |

Persistent unrelated units showed no enrollment/revision changes in the inspected
recording. This is positive live evidence for direct-control suspension, retained
suspension after release, explicit re-enrollment and selection independence.
It does not prove manual move/attack takeover from an enrolled state, same-value
re-enrollment without an intervening Hold, queued-order invalidation, nonleader
runtime behavior, squad-wide scope, or independent-client replication.

Automatic `input` runs `085655_616381` and `085802_193272` both observed Hold but
timed out on the second toggle, before direct control. A 200 ms key-release gap
did not resolve that failure. Prefer user input until this transport is understood.

The manual recorder's launcher was interrupted after the user finished, but its
Python child continued to its configured deadline. Interim hook checks therefore
found active hooks. Final completion/cleanup must be read from the recording's
summary and `manual_verification.json`; do not treat launcher exit as recorder exit.
The full goal remains incomplete and production run mode stays disabled.
