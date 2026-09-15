# Extra controls and data

These run without attaching to or changing the game:

| Action | One-line PowerShell command |
|---|---|
| Stop controller | `py "headless_host.py" friends-stop` |
| Hold automatic starts | `py "headless_host.py" friends-hold` |
| Resume automatic starts | `py "headless_host.py" friends-resume` |
| List saved matches | `py "headless_host.py" matches` |
| Query saved data as JSON | `py "headless_host.py" matches --json` |

Hold/resume never enables game automation in record-only mode. Wait for the controller to stop before switching modes. Automatic mode currently stops for attention after a manual mid-match exit; record-only can save the lobby results.

## AI test lobby isolation

For isolated AI validation, with only the local human and bots in the lobby:

```powershell
py headless_host.py ai-joinability --pid 41072 --joinability closed --minimize
```

Use the current game PID. `--joinability open` restores joining when testing is
finished. This requests Steam's native lobby admission setting and records its
acceptance in the durable journal; it does not remove current members or change
game rules. A new lobby defaults to joinable, so isolation is scoped to its lobby
ID. Remote humans and record-only mode are refused. See
[Steam's admission contract](https://partner.steamgames.com/doc/api/ISteamMatchmaking#SetLobbyJoinable).

For longer tactical validation, `configure-ai --ai-victory-points 200` selects
the native 200 VP / 10000 manpower profile. Pass `--ai-victory-points 200` to
`start-ai` as well; a mismatch is refused. Both commands default to 75 VP. The
native score range, controlled roster, host authority, readiness and durable start
guards still apply. `ai-cycle` retains its 75-point profile.

## SQLite

`review --serve` enables manual winner buttons on the localhost page. Decisions
are immutable through this UI and stored independently in `match_adjudications`:

```sql
SELECT match_id,
       json_extract(adjudication_json, '$.winning_team') AS winner,
       json_extract(adjudication_json, '$.reason') AS reason,
       json_extract(adjudication_json, '$.confirmed_at') AS confirmed_at
FROM match_adjudications;
```

The table is created on the first saved decision. The regular `review` and
`matches` commands remain read-only against SQLite.

Both friends-host modes also write `match_snapshots` (initial, periodic, and
event-triggered raw progress) and `match_observation_events` (session/controller
events). Progress-only matches are undetermined and do not feed ratings. Inspect
their timeline in the generated review, or query:

```sql
SELECT match_id, recorded_at, sampled_at, reason
FROM match_snapshots ORDER BY sequence DESC LIMIT 30;
SELECT match_id, observed_at, kind, evidence_json
FROM match_observation_events ORDER BY observed_at DESC LIMIT 30;
```

Database: `data\rankbot.sqlite3`. The browser review and `matches` commands open it read-only. The HTML is a local snapshot, with no server or extra packages needed.

If using a SQLite application, open this file and run these read-only queries:

Saved matches and outcomes:

```sql
SELECT m.match_id, COALESCE(json_extract(m.observation_json, '$.map'), json_extract(m.observation_json, '$.starting_roster.map')) AS map, json_extract(m.observation_json, '$.trigger') AS finish_reason, json_extract(r.normalized_json, '$.engine_outcome.winning_team') AS winning_team FROM matches m JOIN results r USING (match_id);
```

Player counters, preserving the displayed pairs:

```sql
SELECT r.match_id, json_extract(p.value, '$.fields.player.text') AS player, json_extract(p.value, '$.steam_id') AS steam_id, json_extract(p.value, '$.fields.score.values_in_display_order[0]') AS score, json_extract(p.value, '$.fields.infantry.values_in_display_order') AS infantry_pair, json_extract(p.value, '$.fields.resources.values_in_display_order') AS resource_pair FROM results r, json_each(r.normalized_json, '$.rows') p WHERE json_extract(p.value, '$.kind') = 'player';
```

`matches` stores observed match metadata; `results` stores normalized and raw results, joined by `match_id`. Local command/lifecycle journals and completion captures retain additional evidence. Files are also kept in `validation\run_*`.

No winner is inferred from a mid-match quit. Automatic mod metadata and other result layouts remain unverified. Remote joins/rejoins have since been observed; see [current status](STATUS.md) for the limits of that evidence. [Manual live-test evidence](../validation/run_20260905_162115_115244/manual_validation_summary.json).
