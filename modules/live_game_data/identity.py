"""Convert native roster observations into stable participant identities.

Example using a roster probe and your durable match ID:
    from modules.live_game_data import participants
    records = participants(roster, match_id)
    updated = participants(next_roster, match_id, previous=records)

Keep the same match ID across samples; AI keys are scoped to that match.
Invalid or ambiguous identities raise ValueError.
"""
import time
from headless.lobby_social import badge_tier


def participants(roster, match_id, previous=()):
    old = {p['slot_id']:p for p in previous if p['slot_id'] is not None}
    output = []
    seen = set()
    for row in roster['rows']:
        member = row['memberIdRaw']
        if member in seen:
            raise ValueError('Duplicate native member ID')
        seen.add(member)
        slots = [s for s in roster.get('slots',[]) if s['memberIdRaw'] == member]
        if len(slots)>1:
            raise ValueError('Member assigned to multiple slots')
        slot = slots[0] if slots else None
        slot_id = slot['slotIdRaw'] if slot else None
        kind = 'ai' if row['typeRaw']==2 else (
            'local_host' if member==roster['localMemberIdRaw']==roster['hostMemberIdRaw'] else 'remote_human'
        ) if row['typeRaw'] in (1,4) else 'unknown'
        steam_id = str((row['identityWordsRaw'][1]<<32)|row['identityWordsRaw'][0]) if row['typeRaw'] in (1,4) else None
        if steam_id is not None and (len(steam_id)!=17 or steam_id=='0'):
            raise ValueError('Unsupported human Steam identity')
        prior = old.get(slot_id)
        same = prior and prior['native_member_id']==member and prior['controller_kind']==kind and prior['steam_id']==steam_id
        generation = prior['slot_generation'] + (0 if same else 1) if prior else 1
        key = f'ai:{match_id}:{slot_id}:{generation}' if kind=='ai' else f'steam:{steam_id}' if steam_id else f'unknown:{match_id}:{member}'
        if kind=='ai' and slot_id is None:
            raise ValueError('AI has no established playing slot')
        output.append({'participant_key':key,'native_member_id':member,'slot_id':slot_id,
            'slot_generation':generation,'slot_index_base':1 if slot else None,
            'team_slot_index':slot.get('teamSlotIndexRaw') if slot else None,
            'display_name':row.get('displayName') or next((s['value'] for s in row.get('strings',[]) if s['offset']==12),None),
            'starting_team':slot['teamRaw'] if slot else None,'army':(roster.get('settings',{}).get('teamArmies',{}).get(slot['teamRaw']) if slot and roster.get('settings',{}).get('armySelectionMode')==1 else row.get('armyRaw')),
            'role':'spectator' if row['typeRaw']==4 and row.get('teamRaw')=='spectator' and slot is None else 'participant' if slot and slot['teamRaw'] in ('a','b') else 'unknown',
            'controller_kind':kind,'steam_id':steam_id,'ready':bool(row['readyRaw']),
            'games_played':row.get('gamesPlayedRaw'),
            'games_played_badge_tier':badge_tier(row.get('gamesPlayedRaw')),
            'games_played_source':'native_session_member_0x148' if row.get('gamesPlayedRaw') is not None else None,
            'ai_difficulty':row.get('aiDifficultyRaw') if kind=='ai' else None,
            'ai_difficulty_raw':row.get('aiDifficultyRaw') if kind=='ai' else None,
            'observed_at':time.time(),'source':'guarded_native_member_and_slot_vectors'})
    if len({p['participant_key'] for p in output})!=len(output):
        raise ValueError('Participant identity collision')
    return output


def controlled_ai(roster):
    humans = [r for r in roster['rows'] if r['typeRaw']!=2]
    bots = [r for r in roster['rows'] if r['typeRaw']==2]
    teams = {r['memberIdRaw']: [s['teamRaw'] for s in roster['slots']
             if s['memberIdRaw']==r['memberIdRaw']] for r in roster['rows']}
    if (len(teams) != len(roster['rows']) or
            any(len(t)!=1 or t[0] not in ('a','b') for t in teams.values())):
        return False
    bot_teams = {teams[r['memberIdRaw']][0] for r in bots}
    solo_heroic = (len(humans)==1 and len(bots)==3
                   and all(r.get('aiDifficultyRaw')=='heroic' for r in bots)
                   and bot_teams == ({'a','b'} - set(teams[humans[0]['memberIdRaw']])))
    return (len(humans)==1 and humans[0]['typeRaw']==1
            and humans[0]['memberIdRaw']==roster['localMemberIdRaw']==roster['hostMemberIdRaw']
            and all(r['typeRaw'] in (1,2) for r in roster['rows'])
            and (bot_teams=={'a','b'} or solo_heroic)
            and all(any(s['memberIdRaw']==r['memberIdRaw'] and s['teamRaw'] in ('a','b') for s in roster['slots']) for r in roster['rows']))
