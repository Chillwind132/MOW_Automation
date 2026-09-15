# First human-opponent trial: September 7, 2026

The user explicitly authorized local army automation against human opponents and
manually started native match `0x6a9f71ef`. The live roster placed local member 4
on German team B with two built-in AIs; team A had two humans and one built-in AI.
The roster was not a pure one-controller-versus-two-humans match. No lobby edits
were performed after Start. The controller only enrolled local-owned units.

`bot_battle --human-opponents` is an explicit diagnostic scope. The original
AI-only guard remains the default. The human scope preserves native local-host
authority, rejects human teammates and more than three human opponents, freezes
the observed roster/ownership identity and preserves manual reclamation. It does
not establish cross-client replication correctness. Automatic AI-only completion
exit is not invoked for this manually started human match.

Evidence directory:
`validation/local_archive/new_runs/human_opponent_battle_20260907_1`.
The controller purchased and adopted eight single riflemen, issued 32 moves and
one stance order, and observed 72.08 seconds of simulation progress before the
game stopped progressing. The user reported the native out-of-sync screen.
STOP then completed; all 12 hook sites matched their original bytes after detach.

## Synchronization evidence

`game_after_desync.log` records agreement among all three human clients at quant
204039. At quant 205059 both remote clients reported the same pair of checksums,
while the host differed in the first value:

| Quant | Host | Both remote clients |
| --- | --- | --- |
| 204039 | C03B7E69 6BEDCAC4 | C03B7E69 6BEDCAC4 |
| 205059 | 1EF1E002 64C838B3 | 1B8731A9 64C838B3 |

The meanings of the two checksum columns are not established here. This evidence
does not identify a bad network connection or prove which operation caused the
divergence.

Subsequent static analysis shows that even an empty cover result enters scoring
at `0x8a75a0`, which calls navigation scoring (`0x8a7d80`) and detector processing
(`0x8a8020`) before its candidate loop. The latter temporarily edits detector
fields; this is not a plain table read. These findings are in
`validation/tactical_mapping_20260907/cover_empty_query_sync_20260907.txt` and
`cover_sync_side_effects_20260907.txt`. Shared scratch/cache writes alone do not
prove a simulation divergence. `sync_checksum_columns_20260907.txt` confirms
the two printed fields but does not establish their meanings.

Within that interval, observations record a move after sample 204159, the run's
first and only native `cover_scored_query` at 204399, and a rifle purchase after
sample 204839. The cover query had one input record and zero returned candidates.
Earlier moves and purchases occurred while checksum checks continued to agree.
The first cover query is therefore a strong investigation lead, not established
causation. No correlated remote entity-state dump is available.

For the next explicitly authorized human trial, native cover entry and both
cover queries are withheld at the bridge, and `nativeCover` is excluded from
the diagnostic capability overrides. This isolates the suspected path; it is
not proof that the remaining actions are synchronized. The desynchronized match
has not been resumed and no retry has been launched.

Battle runners now monitor only new bytes appended to the native game log. A
new desync quant within the observed trial interval stops the runtime before
further purchases/orders and saves `synchronization_failure.json`; the outcome
remains interrupted even if a terminal state is present in the same observation.
Historical lines are excluded. Reads and partial-line storage are bounded; a
missing, replaced or truncated log is reported as unavailable/unassociated rather
than as a desync. This does not detect a failure already logged before attachment.
Unit and runtime integration tests cover partial writes, old errors, truncation,
bounded reads and stopping before any order. Live auto-stop validation is pending.

At the subsequent process inspection the game PID was absent; no crash cause is
inferred. The review service remained running. No game relaunch was performed.

## Purchase correction

The hurried German template mapping selected catalog 1030, `riflemans2(ger)`,
which is one `ger_grenadier_rifle_44`, costing 10 in the installed definition.
That was a poor default for rapidly building an army and explains the user's
observation. The next-run mapping now selects catalog 994, `grenadiers_44(ger)`:
nine soldiers comprising a leader, Obergrenadier, semiautomatic rifleman,
rifleman, rifle-grenadier, two Panzerfaust soldiers, MG gunner and assistant.
The installed definition costs 152. Native availability and ownership checks
remain required; no MP value is patched.

Both IDs/names were read from the live catalog. Composition was checked in
`resource/gamelogic.pak`, `set/multiplayer/units/ger/squads_44.set`, under the
installed Robz workshop item 610304528. The corrected squad purchase has not yet
been exercised live. German special-weapon tactical behavior remains unverified;
the native engine may use their ordinary automatic behavior.
