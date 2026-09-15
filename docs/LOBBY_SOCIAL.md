# Lobby experience and chat capture

Reviewed 2026-09-06. See [current status](STATUS.md) for later runtime evidence.
The captures below are historical observations from September 5.

Implementation: `headless/lobby_social.py`, native probes in `headless/headless_host.js`, and both recorder/automatic runner loops.

Live evidence:

- `validation/social_capture_live/raw.json` and `normalized.json`: Player17, Steam ID 76561190000001022, 1044 Games played, 0 Ranked games played; Test123 retained verbatim.
- `validation/social_debug.json`: Player07, Steam ID 76561190000001024, 193 Games played, 0 Ranked games played. Both observations persisted in SQLite.
- `validation/social_greeting_live/verified.json`: one authorized greeting sent through the native lobby chat handler and observed back in the native chat UI. No game start, settings change, or focus change was used for this test. Later player joins/rejoins were observed in the run linked from current status; this local echo alone does not prove remote delivery.

Native bindings (retail executable hash remains checked by the controller):

- Chat panel `mp_steamsessionchat`, vtable E0B1D4, channel vector +F4/+F8, stride 8. Select only Steam lobby channel vtable E0BE90; never the global/friends channel.
- Channel member list +D0, message list +D4, owner panel +D8. UI tooltip is std::string at +6C. Member row names contain native member IDs, which are joined to the session roster's Steam identity; no display-name joins for experience.
- Human session member +148 is the displayed games-played count, corroborated against Player17 1044 and Player07 193. It is included in future match participant snapshots, including during gameplay. Ranked-games normalization uses the actual tooltip, not an assumed native offset.
- A059E0 chooses unranked/ranked badge assets from counts using thresholds 1, 10, 25, 50, 100, 200, 400, 800, 1500, 2000. We store tier 0–10, not invented military rank names. These are experience badges, not our skill ratings.
- Text edit panel +EC, vtable E0DF10, text +44, setter A2A800 at virtual +54. Native handler A0BFB0 receives event code E and uses the lobby channel's normal message processing. The bridge revalidates lobby, local hosting, recipient Steam ID, and an empty input before writing. Native calls run in the existing engine-thread command queue.

Persistence and limits:

- Experience observations are deduplicated by lobby and evidence; first and last observation timestamps are retained.
- Chat stores the exact body and formatted header, with a deduplication key incorporating sender/header/body and occurrence. UI history has time-of-day rather than a durable server message ID. Identical repeated messages with identical timestamps after history truncation cannot always be distinguished. This is five-second UI polling, not a lossless transport hook.
- Greetings are claimed durably before dispatch. A newly completed recorded game plus a native post-game lobby-entry event allows a new greeting with updated DB values; prior claims are archived in `lobby_greeting_history`. Otherwise at most one attempt per lobby/Steam ID survives restarts, including uncertain attempts; definite native rejections (`mutationStarted: false`) are stored as `not_sent` and can retry after a later native entry into the same lobby. A submitted message is marked observed when its local UI echo is captured. This does not claim every remote client received it.
- Automatic mode skips its own host and all AI, pauses greetings while held, and rate limits to one per five seconds. Read-only mode only captures. Rating lookup defaults to the stored Robz outcome-only TrueSkill rating, with provisional status; players without a stored rating are greeted with `Rating: unrated.`, and available provisional ratings include `(provisional)`. Experience badges stay independent. See [rating policy and validation](RATINGS.md).
- Early-start voting now offers `/start` when all humans are ready on opposing teams. Controller notifications use the guarded chat-reply sender with exact roster approval; the legacy chat-announcement action remains disabled. See the operating guide for resets and limitations.
- Greetings include the automated-lobby welcome, saved game count and explicit rating state, with a 1–3 second initial delay and 5–12 second spacing. The native sender rechecks recipient presence before touching chat input.
- The optional GM is limited to lobby replies. Its current mode/defaults are documented in the [operating guide](README.md); record-only rejects GM activation.
- Current reads have a traversal time budget, prune chat descendants during panel lookup, and omit unused raw headers. Failed polls clear the cached snapshot; they do not send from stale chat.
- Old matches are not rewritten or assigned today's experience counts.

Static analysis evidence is in `validation/decompile_social4.txt`, `decompile_chat_setter.txt`, and `decompile_chat_transport.txt`.
