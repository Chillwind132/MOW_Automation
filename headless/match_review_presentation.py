"""Presentation only: observed progress never changes persisted final results."""
import base64
from functools import lru_cache
from pathlib import Path

from lobby_social import badge_tier


@lru_cache(maxsize=1)
def rank_icons():
    folder=Path(__file__).parent/'assets/ranks'
    return {str(tier):'data:image/png;base64,'+base64.b64encode(
        (folder/f'ur_rank_{tier:02}.png').read_bytes()).decode('ascii') for tier in range(11)}


def recorded_games(match,database):
    counts={}
    # Replay member metadata is a fallback for games imported without a recorder.
    digest=(match.get('replay') or {}).get('ss_sha256')
    if digest and len(digest)==64 and all(c in '0123456789abcdef' for c in digest):
        try:
            from modules.end_game_results.replays import tree,section,value
            nodes=tree((Path(database).parent/'replays'/digest/'replay.ss').read_text(encoding='utf-8-sig'))
            for member in section(nodes,'members'):
                if value(member,'type')=='player':
                    counts[value(member,'steamId')]=int(value(section(member,'steamInfo'),'gamesPlayed'))
        except (OSError,ValueError,KeyError):pass
    metadata=match.get('metadata') or {}
    for name in ('starting_roster','loaded_roster'):
        for r in (metadata.get(name) or {}).get('rows',[]):
            words=r.get('identityWordsRaw') or []
            n=r.get('gamesPlayedRaw')
            if len(words)==2 and type(n) is int and n>=0:
                counts[str((words[1]<<32)|words[0])]=n
    for p in match.get('participants',[]):
        n=p.get('games_played')
        if p.get('steam_id') and type(n) is int and n>=0:counts[p['steam_id']]=n
    return {steam:dict(games_played=n,tier=badge_tier(n)) for steam,n in counts.items() if n>=0}


def departures(events):
    result={}
    for event in sorted(events,key=lambda e:e.get('observed_at',0)):
        steam=event.get('steam_id');kind=event.get('kind');e=event.get('evidence') or {}
        if not steam:continue
        if kind=='steam_lobby_membership':
            # Only callbacks associated with active play establish a departure.
            if e.get('association')!='active_controller_match_and_same_lobby':continue
            flags=e.get('flags',0)
            if flags & 30:
                reason=('Banned' if flags&16 else 'Kicked' if flags&8 else
                        'Disconnected' if flags&4 else 'Left the lobby')
                result[steam]=dict(label='Leaver',reason=reason,returned=False)
            elif flags&1 and steam in result:result[steam]['returned']=True
        elif kind=='roster_missing' and (e.get('before') or {}).get('status')=='present':
            # Do not replace a specific native reason with the later polling event.
            if steam not in result or result[steam]['returned']:
                result[steam]=dict(label='Leaver',reason='Left the player roster; reason unavailable',returned=False)
        elif kind=='roster_restored' and steam in result:result[steam]['returned']=True
    return result


def _decorate_statistics(match,database):
    match['ranks']=recorded_games(match,database)
    match['departures']=departures(match.get('participation_events',[]))
    match['display_rows']=match['rows']
    team_rows=[r for r in match['rows'] if r.get('kind')=='team' and r.get('row_id') in ('ta','tb')]
    if team_rows:
        people={p['participant_key']:p for p in match.get('participants',[]) if p.get('participant_key')}
        teams={p['steam_id']:p.get('starting_team') for p in match.get('participants',[]) if p.get('steam_id')}
        ordered=[]
        for team in sorted(team_rows,key=lambda r:r['row_id']!='t'+str(match.get('winner'))):
            ordered.append(team)
            ordered.extend(r for r in match['rows'] if r.get('kind')=='player' and
                (people.get(r.get('participant_key'),{}).get('starting_team') or teams.get(r.get('steam_id')))==team['row_id'][1:])
        ordered.extend(r for r in match['rows'] if r not in ordered)
        match['display_rows']=ordered
    match['display_sampled_at']=None
    match['display_source']='replay' if match.get('replay') else 'saved'
    if match.get('replay') or match['capture_stage']!='progress_snapshot':return
    match['display_source']='progress'
    snapshots=match.get('progress_snapshots',[])
    latest=next((s for s in reversed(snapshots) if (s.get('player_statistics') or {}).get('status') in ('observed','partial')),None)
    if latest is None:return
    stats=latest['player_statistics']
    def fields(name,values):
        output={'player':dict(text=name)}
        for key in ('victory_points','infantry','vehicles','score','resources'):
            val=values.get(key)
            output[key]=None if val is None else dict(values_in_display_order=val if isinstance(val,list) else [val])
        return output
    rows=[]
    for team in stats['teams']:
        rows.append(dict(kind='team',row_id='t'+team['team'],steam_id=None,
                         fields=fields('Team '+team['team'].upper(),team)))
        for player in stats['players']:
            if player['team']!=team['team']:continue
            rows.append(dict(kind='player',row_id=player['participant_key'],participant_key=player['participant_key'],
                             steam_id=player['steam_id'],team=player['team'],fields=fields(player['display_name'],player)))
    match['display_rows']=rows
    match['display_sampled_at']=latest.get('sampled_at')


ARMY_NAMES = {'usa':'U.S. Army', 'ger':'Wehrmacht', 'ger2':'Wehrmacht',
              'ger_ss':'Waffen-SS', 'rus':'Red Army', 'rus_guard':'Soviet Guards',
              'eng':'British Army', 'jap':'Imperial Japanese Army', 'axis_minor':'Axis Minors'}
ALLIANCE_NAMES = {'axis':'AXIS', 'allies':'ALLIES/SOVIET'}


def army_settings(match,database):
    """Use the archived replay's selection rules, falling back to recorded settings."""
    settings=match.get('settings') or {}
    mode=settings.get('armySelectionMode')
    teams=settings.get('teamArmies') or {}
    alliances=settings.get('teamAlliances') or {}
    digest=(match.get('replay') or {}).get('ss_sha256')
    if digest and len(digest)==64 and all(c in '0123456789abcdef' for c in digest):
        try:
            from modules.end_game_results.replays import tree,section,value
            nodes=tree((Path(database).parent/'replays'/digest/'replay.ss').read_text(encoding='utf-8-sig'))
            mode=value(section(nodes,'main'),'armySelectionMode')
            teams,alliances={},{}
            for team in section(nodes,'teams'):
                name=value(team,'name')
                for key,target in (('army',teams),('alliance',alliances)):
                    try:target[name]=value(team,key)
                    except ValueError:pass
        except (OSError,ValueError,KeyError):pass
    label={2:'Players',1:'Teams',3:'Alliances','player':'Players','team':'Teams',
           'alliance':'Alliances'}.get(mode)
    return dict(mode=label,teams=teams,alliances=alliances)


def has_human_opponents(match):
    """At least one distinct, identified human participant on each opposing team."""
    teams={'a':set(),'b':set()}
    for person in match.get('participants',[]):
        team=person.get('starting_team')
        steam=person.get('steam_id')
        if (team in teams and person.get('role')=='participant' and steam and steam!='0'
                and person.get('controller_kind') in ('local_host','remote_human')):
            teams[team].add(steam)
    return bool(teams['a'] and teams['b'] and len(teams['a'] | teams['b'])>=2)


def decorate(match,database):
    _decorate_statistics(match,database)
    selection=army_settings(match,database)
    match['army_mode']=selection['mode']
    match['has_human_opponents']=has_human_opponents(match)
    participants=match.get('participants',[])
    team_rows={r['row_id'][1:]:r for r in match['display_rows'] if r.get('kind')=='team' and r.get('row_id') in ('ta','tb')}
    rows=[]
    for row in match['display_rows']:
        if row.get('kind')!='player':continue
        person=next((p for p in participants if
            (row.get('participant_key') and row['participant_key']==p.get('participant_key')) or
            (row.get('steam_id') and row['steam_id']==p.get('steam_id'))),{})
        team=person.get('starting_team') or row.get('team')
        army=row.get('army') or person.get('army') or person.get('nation')
        if selection['mode']=='Teams':army=selection['teams'].get(team) or army
        nation=ARMY_NAMES.get(army,army) if army and army!='random' else None
        if selection['mode']=='Alliances':
            alliance=selection['alliances'].get(team)
            label=ALLIANCE_NAMES.get(alliance,alliance)
            # Older observations may only retain the game's displayed team label.
            if not label:label=(team_rows.get(team,{}).get('fields',{}).get('player') or {}).get('text')
            if label in ('Team A','Team B'):label=None
            text=label
        else:text=nation if selection['mode']=='Teams' else None
        own_team=(team.upper()+(' · '+text if text else '')) if team in ('a','b') else None
        fields=dict(row.get('fields',{}))
        fields['victory_points']=team_rows.get(team,{}).get('fields',{}).get('victory_points') or fields.get('victory_points')
        rows.append(dict(row,fields=fields,player_army=nation,team=team,team_label=own_team))
    match['player_rows']=rows
