"""Bind an already-loaded native game to a durable recording identity.

Example with an attached, session-bound controller and no active match:
    from modules.live_game_data import associate_loaded
    roster = controller.command("probe", target="roster")["probe"]
    created = associate_loaded(controller, roster, hosting_mode="observe")

Sets controller.active_match and journals the identity; never starts a game.
Existing unresolved generations raise ValueError and require reconciliation.
"""
import json
import time
import uuid
from .identity import participants

def associate_loaded(c,roster,prior=None,hosting_mode="record_only"):
    epoch=roster['gameStartTimeRaw']
    if not epoch:
        raise ValueError('Loaded match has no native generation')
    for record in c.journal.inspect(c.process_key)['matches']:
        if record['session_id']==c.host_session_id and record['latest_match_observation'].get('native_game_start_time')==epoch:
            if record['state'] in ('lobby_returned','failed'):
                return False
            raise ValueError('Existing match generation requires reconciliation')
    mid=str(uuid.uuid4())
    records=participants(roster,mid)
    if not any(p['role']=='participant' for p in records) or any(p['role']=='unknown' for p in records):
        raise ValueError('Playing participant identities are incomplete')
    prior_matches=prior is not None and prior['steamLobbyId']==roster['steamLobbyId']
    match={'match_id':mid,'hosting_mode':hosting_mode,'process_identity':c.identity,
           'host_session_id':c.host_session_id,'native_game_start_time':epoch,
           'starting_roster':roster,'pre_start_lobby_observation':prior if prior_matches else None,
           'starting_roster_source':'first_loaded_roster','loaded_roster':roster,
           'participants':records,'effective_settings':roster['settings'],'map':roster['map'],
           'created_at':time.time(),'loaded_at':time.time(),'engine_outcome':None,
           'mods':None,'mods_status':'not_yet_captured','rating_status':'not_applied',
           'start_observation':'lobby_then_loaded' if prior_matches else 'attached_in_progress'}
    from headless.match_ratings import capture_profile
    match['rating_profile']=capture_profile(c)
    c.match_id=c.journal.new_match(c.host_session_id,match,mid)
    c.journal.transition(mid,'lobby','playing',match)
    c.active_match=match
    (c.directory/f'{mid}_match.json').write_text(json.dumps(match,indent=2),encoding='utf-8')
    c.record('manual_match_associated',match=match)
    return True
