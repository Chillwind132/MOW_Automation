"""Friends hosting policy and a local, durable CLI control/overview channel."""
from contextlib import closing
import json
import re
import sqlite3
import time
import uuid

from modules.live_game_data import participants
from lobby_social import LobbySocial
from early_start import EarlyStart, early_voters


class ReadinessChanged(RuntimeError):
    """Start was rejected before any native mutation; observe a fresh countdown."""


def readiness(roster, minimum=2, ai_test=False, expected_map=None, team_armies=None, early=False, army_selection=None):
    """Only playing members count; native approval/gate recheck at execution."""
    reasons=[]
    if not capacity_ready(roster,minimum):
        reasons.append(f'lobby must have exactly {minimum} playing slots split equally')
    if isinstance(expected_map,str) and roster.get('map')!=expected_map:
        reasons.append('select expected map: '+expected_map)
    rows=roster['rows']
    host=[r for r in rows if r['memberIdRaw']==roster['localMemberIdRaw']]
    if roster['hostMemberIdRaw']!=roster['localMemberIdRaw']:
        reasons.append('local process is not host')
    if len(host)!=1 or host[0]['typeRaw']!=4 or host[0].get('teamRaw')!='spectator':
        reasons.append('host must be a spectator')
    settings=roster['settings']
    if settings.get('armySelectionMode')!=army_selection_mode(team_armies,army_selection) or settings['enableSpectators']!=1:
        reasons.append({2:'Players',1:'Teams',3:'Alliances'}[army_selection_mode(team_armies,army_selection)]+' and spectators must be enabled')
    if team_armies and any(settings.get('teamArmies',{}).get(t)!=army for t,army in team_armies.items()):
        reasons.append('host team nations differ from requested configuration')
    players=[r for r in rows if r['typeRaw']!=4]
    if early and ai_test:
        reasons.append("early start requires human players")
    if len(players)<(2 if early else minimum):
        reasons.append(f'waiting for {minimum} players')
    elif len(players)>minimum:
        reasons.append(f'expecting exactly {minimum} players')
    allowed_types=(1,2) if ai_test=='mixed' else (2,) if ai_test else (1,)
    if any(r['typeRaw'] not in allowed_types for r in players):
        reasons.append('unexpected participant type')
    if any(r['readyRaw']!=1 for r in players if not ai_test or r['typeRaw']==1):
        reasons.append('players are not all ready')
    if not team_armies and any(not r.get('armyRaw') for r in players):
        reasons.append('player nation is missing')
    teams=set()
    for r in rows:
        slots=[s for s in roster['slots'] if s['memberIdRaw']==r['memberIdRaw']]
        if r['typeRaw']==4:
            if slots or r.get('teamRaw')!='spectator':
                reasons.append('spectator assignment is ambiguous')
        elif len(slots)!=1 or slots[0]['teamRaw'] not in ('a','b'):
            reasons.append('player slot is ambiguous')
        else:
            teams.add(slots[0]['teamRaw'])
    if teams!={'a','b'}:
        reasons.append('both teams need a player')
    counts=[sum(s['teamRaw']==t and any(r['memberIdRaw']==s['memberIdRaw'] and r['typeRaw']!=4 for r in players)
                for s in roster['slots']) for t in ('a','b')]
    if not early and counts[0]!=counts[1]:
        reasons.append('teams must have equal player counts')
    try:
        records=participants(roster,'readiness')
        if any(p['role']=='unknown' for p in records):
            reasons.append('unknown participant role')
    except (ValueError,KeyError) as error:
        reasons.append(str(error))
    return {'ready':not reasons,'reasons':list(dict.fromkeys(reasons)),
            'players':len(players),'ready_players':sum((ai_test and r['typeRaw']==2) or r['readyRaw']==1 for r in players)}


class ReadyWindow:
    def __init__(self, seconds):
        self.seconds=seconds
        self.signature=None
        self.since=None

    def update(self, signature, ready, now):
        if not ready:
            self.signature=self.since=None
            return False
        if signature!=self.signature:
            self.signature,self.since=signature,now
        return now-self.since>=self.seconds


class Control:
    """Separate from the game lock: CLI never attaches to an owned game process."""
    def __init__(self,path):
        self.path=path
        path.parent.mkdir(parents=True,exist_ok=True)
        with closing(self.connect()) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS runner (singleton INTEGER PRIMARY KEY CHECK(singleton=1), run_id TEXT, desired TEXT, sequence INTEGER, status_json TEXT, heartbeat REAL)')

    def connect(self):
        return sqlite3.connect(self.path,timeout=5)

    def begin(self,held=False):
        token=str(uuid.uuid4())
        with closing(self.connect()) as db,db:
            db.execute('INSERT OR REPLACE INTO runner VALUES (1,?,?,0,?,?)',
                       (token,'hold' if held else 'run',json.dumps({'phase':'starting','running':True}),time.time()))
        return token

    def desired(self,token):
        with closing(self.connect()) as db:
            row=db.execute('SELECT desired,sequence FROM runner WHERE run_id=?',(token,)).fetchone()
        if row is None:
            raise RuntimeError('Runner control ownership changed')
        return row

    def publish(self,token,status):
        with closing(self.connect()) as db,db:
            changed=db.execute('UPDATE runner SET status_json=?,heartbeat=? WHERE run_id=?',
                               (json.dumps(status),time.time(),token)).rowcount
            if changed!=1:
                raise RuntimeError('Runner control ownership changed')

    def status(self):
        with closing(self.connect()) as db:
            row=db.execute('SELECT run_id,desired,sequence,status_json,heartbeat FROM runner').fetchone()
        if row is None:
            return {'running':False,'phase':'not started'}
        status=json.loads(row[3])
        status.update(run_id=row[0],desired=row[1],requested_sequence=row[2],heartbeat_age_seconds=round(time.time()-row[4],1))
        status['stale']=status['heartbeat_age_seconds']>15
        return status

    def request(self,action):
        if action not in ('hold','run','stop'):
            raise ValueError('Unknown control action')
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT status_json,heartbeat FROM runner').fetchone()
            if not row or not json.loads(row[0]).get('running') or time.time()-row[1]>15:
                raise RuntimeError('No responsive friends controller; inspect friends-status')
            db.execute('UPDATE runner SET desired=?,sequence=sequence+1',(action,))
        return self.status()


def capacity_ready(roster,players):
    return (isinstance(players,int) and 2<=players<=32 and players%2==0
            and roster['settings'].get('maxPlayers')==players
            and all(sum(s['teamRaw']==t for s in roster['slots'])==players//2 for t in ('a','b')))


def requested_team_armies(c):
    value=getattr(c,'expected_team_armies',{})
    return value if isinstance(value,dict) else {}


def requested_army_selection(c):
    value=getattr(c,'expected_army_selection',None)
    return value if isinstance(value,str) else None


def army_selection_mode(armies,selection=None):
    if selection not in (None,'players','teams','alliances'):
        raise ValueError('Unsupported army selection')
    if selection is not None and (selection=='teams') != bool(armies):
        raise ValueError('Team armies must match army selection')
    return {'players':2,'teams':1,'alliances':3}.get(selection,1 if armies else 3)


def team_settings_ready(r,armies,army_selection=None):
    s=r['settings']
    return (s.get('armySelectionMode')==army_selection_mode(armies,army_selection) and s['enableSpectators']==1
            and all(s.get('teamArmies',{}).get(t)==army for t,army in armies.items()))


def prepare(controller,timeout,minimum=2):
    controller.host_lobby(timeout)
    controller.bind_session()
    if controller.active_match or controller.recovery['status']!='idle':
        raise RuntimeError('Existing match/results require reconciliation before preparation')
    a=controller.command('probe',target='approval')['probe']
    r=a['roster']
    local=[m for m in r['rows'] if m['memberIdRaw']==r['localMemberIdRaw']]
    if not team_settings_ready(r,requested_team_armies(controller),requested_army_selection(controller)):
        controller.command('configure-friends',approval=a['approval'],teamArmies=requested_team_armies(controller) or None,armySelection=requested_army_selection(controller))
        _verify_command(controller,'friends lobby settings applied',lambda s: _settings_ready(controller),timeout)
        a=controller.command('probe',target='approval')['probe']
    if len(local)!=1 or local[0]['typeRaw']!=4 or local[0].get('teamRaw')!='spectator':
        # Publishing enableSpectators updates the card before the lobby UI rebuilds.
        # Wait for the native destination, then approve the current roster again.
        controller.checkpoint('spectator section available',lambda s:any(
            n.get('name')=='spectator:spectator'
            for n in controller.command('probe',target='controls')['probe']['nodes']),timeout)
        a=controller.command('probe',target='approval')['probe']
        controller.command('spectate-host',approval=a['approval'])
        _verify_command(controller,'host moved to spectator',lambda s: _host_spectator(controller),timeout)
    r=controller.command('probe',target='roster')['probe']
    if not capacity_ready(r,minimum) or r.get('mapSelectionPlayersRaw',minimum)!=minimum:
        a=controller.command('probe',target='approval')['probe']
        expected=getattr(controller,'expected_map',None)
        controller.command('configure-capacity',approval=a['approval'],players=minimum,
                           expectedMap=expected if isinstance(expected,str) else None)
        _verify_command(controller,f'{minimum} playing slots configured',
                        lambda s:capacity_ready(controller.command('probe',target='roster')['probe'],minimum),timeout)
        r=controller.command('probe',target='roster')['probe']
    if not team_settings_ready(r,requested_team_armies(controller),requested_army_selection(controller)):
        a=controller.command('probe',target='approval')['probe']
        controller.command('configure-friends',approval=a['approval'],teamArmies=requested_team_armies(controller) or None,armySelection=requested_army_selection(controller))
        _verify_command(controller,'team nations restored after capacity setup',lambda s:_settings_ready(controller),timeout)
        r=controller.command('probe',target='roster')['probe']
    (controller.directory/'friends_profile.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
    return r


def _verify_command(c,label,predicate,timeout):
    request=c.last_request_id
    try:
        state=c.checkpoint(label,predicate,timeout)
        c.journal.command_state(request,'observed-complete',state)
    except BaseException as error:
        c.journal.command_state(request,'unknown',{'error':str(error)})
        raise


def _settings_ready(c):
    return team_settings_ready(c.command('probe',target='roster')['probe'],requested_team_armies(c),army_selection=requested_army_selection(c))


def _host_spectator(c):
    r=c.command('probe',target='roster')['probe']
    return any(m['memberIdRaw']==r['localMemberIdRaw'] and m['typeRaw']==4 and m.get('teamRaw')=='spectator' for m in r['rows']) and not any(s['memberIdRaw']==r['localMemberIdRaw'] for s in r['slots'])


def restore_bot_armies(c,approval,ai_test,timeout):
    expected_armies=getattr(c,'expected_bot_armies',{})
    changed=False
    for member in approval['roster']['rows']:
        expected=expected_armies.get(member.get('teamRaw'))
        if member['typeRaw']==2 and expected and member['armyRaw']!=expected:
            if ai_test is not True:
                raise RuntimeError('Automatic faction restoration requires an all-bot test')
            c.set_bot_army(member['memberIdRaw'],expected,timeout)
            changed=True
    # Every faction request invalidates the old approval token.
    return c.command('probe',target='approval')['probe'] if changed else approval


def start_match(c,approval,minimum,ai_test,timeout,early_votes=None):
    r=approval['roster']
    if not readiness(r,minimum,ai_test,getattr(c,'expected_map',None),requested_team_armies(c),early=early_votes is not None,army_selection=requested_army_selection(c))['ready']:
        raise RuntimeError('Friends roster is not ready')
    if early_votes is not None and set(early_votes)!=set(early_voters(r)):
        raise ReadinessChanged('Early-start voters changed')
    expected_armies=getattr(c,'expected_bot_armies',{})
    for member in r['rows']:
        expected=expected_armies.get(member.get('teamRaw'))
        if member['typeRaw']==2 and expected and member['armyRaw']!=expected:
            raise RuntimeError('Bot faction differs from the controlled test configuration')
    match={'match_id':str(uuid.uuid4()),'hosting_mode':'friends','ai_test':ai_test,
           'process_identity':c.identity,'host_session_id':c.host_session_id,
           'starting_roster':r,'effective_settings':r['settings'],'created_at':time.time(),
           'mods':None,'mods_status':'not_yet_captured','engine_outcome':None}
    if any(expected_armies.values()):match['expected_bot_armies']=expected_armies
    if early_votes is not None:match['early_start_votes']=sorted(early_votes)
    match['expected_army_selection']=requested_army_selection(c)
    match['expected_team_armies']=requested_team_armies(c)
    match['participants']=participants(r,match['match_id'])
    from match_ratings import capture_profile
    match['rating_profile']=capture_profile(c)
    c.match_id=c.journal.new_match(c.host_session_id,match,match['match_id'])
    c.journal.transition(c.match_id,'lobby','start_requested',approval)
    (c.directory/'match_observation.json').write_text(json.dumps(match,indent=2),encoding='utf-8')
    try:
        started=c.command('start',friends=True,approval=approval['approval'],minimum=minimum,aiTest=ai_test,teamArmies=requested_team_armies(c) or None,armySelection=requested_army_selection(c),earlyVotes=early_votes,expectedEpoch=r.get("gameStartTimeRaw"))
    except Exception as error:
        if not c.journal.inspect(c.process_key)['unresolved_commands']:
            c.journal.transition(c.match_id,'start_requested','failed',{'reason':'native precondition rejected'})
            c.match_id=None
            raise ReadinessChanged(str(error)) from error
        raise
    c.journal.transition(c.match_id,'start_requested','loading',started)
    c.active_match=match
    # Loading is observed in the runner loop so overview and stop remain responsive.
    return match


def run(c,control,minimum=2,ready_seconds=5,timeout=120,held=False,ai_test=False,duration=None,max_matches=None,loading_timeout=600,restart=False):
    token=control.begin(held)
    c.game_master_can_send=lambda:control.desired(token)[0]=='run'
    window=ReadyWindow(ready_seconds)
    status={'running':True,'phase':'starting','evidence':str(c.directory),'matches_saved':0}
    start=time.monotonic()
    loading_since=terminal_since=None
    last_print=None
    social=LobbySocial(c)
    early=EarlyStart()
    restart_pending=None

    def restart_poll():
        desired,sequence=control.desired(token)
        status.update(phase='restarting MOW / preparing new lobby',applied_sequence=sequence,held=desired=='hold')
        control.publish(token,status)
        if desired=='stop' or (duration is not None and time.monotonic()-start>=duration):
            raise KeyboardInterrupt

    try:
        if not c.active_match:
            prepare(c,timeout,minimum)
        else:
            record=c.journal.inspect(c.process_key)
            active=next(m for m in record['matches'] if m['match_id']==c.match_id)
            with closing(c.journal.connect()) as db:
                starts=db.execute("SELECT COUNT(*) FROM command_journal WHERE match_id=? AND action='start' AND status='observed-complete'",(c.match_id,)).fetchone()[0]
            pending_load=(active['state']=='loading' and active['session_id']==c.host_session_id and starts==1 and not record['unresolved_commands'])
            if c.active_match.get('hosting_mode')!='friends' or (c.recovery['status']=='needs_reconciliation' and not pending_load):
                raise RuntimeError('Active match requires reconciliation before friends hosting')
        while (duration is None or time.monotonic()-start<duration) and (max_matches is None or status['matches_saved']<max_matches):
            desired,sequence=control.desired(token)
            status.update(applied_sequence=sequence,held=desired=='hold',match_id=c.match_id)
            if desired=='stop':
                break
            if restart_pending:
                from host_restart import restart_after_match
                social.close()
                early.reset(notify=False)
                window.update(None,False,time.monotonic())
                restart_after_match(c,restart_pending,timeout,restart_poll)
                c.restart_poll=restart_poll
                try:
                    prepare(c,timeout,minimum)
                finally:
                    c.restart_poll=None
                social=LobbySocial(c)
                c.record('restart_complete',match_id=restart_pending,pid=c.pid)
                restart_pending=None
                loading_since=terminal_since=None
                status.pop('live',None)
                status.pop('roster',None)
                status.pop('lobby_id',None)
                continue
            state=c.state()
            if c.active_match and 'native_game_start_time' not in c.active_match and state['pageVtable']!=0xe2ae58:
                loading_since=loading_since or time.monotonic()
                status['phase']='loading (waiting for gameplay page)'
                control.publish(token,status)
                if time.monotonic()-loading_since>loading_timeout:
                    raise TimeoutError('Gameplay page did not become ready; game preserved')
                time.sleep(1)
                continue
            if not c.active_match and state['pageVtable']!=0xe2b2cc:
                if state['pageVtable']==0xe2ae58:
                    raise RuntimeError('Unassociated gameplay requires reconciliation')
                early.reset()
                window.update(None,False,time.monotonic())
                status['phase']='waiting for lobby / close map or settings dialog'
                control.publish(token,status)
                time.sleep(1)
                continue
            try:
                r=c.command('probe',target='roster')['probe']
            except RuntimeError as error:
                if c.active_match or 'Expected one active service of kind 8' not in str(error):
                    raise
                early.reset()
                window.update(None,False,time.monotonic())
                status['phase']='waiting for lobby service'
                control.publish(token,status)
                time.sleep(1)
                continue
            if state['pageVtable']==0xe2b2cc:
                listing=getattr(c,'browser_listing',{})
                if isinstance(listing,dict) and listing.get('lobbyName') is not None:
                    status['browser']=c.command('publish-browser-name',**listing)['browser']
                try:
                    social.poll()
                    status.pop('social_notice',None)
                except (ValueError,RuntimeError) as error:
                    if status.get('social_notice') != str(error):
                        print(f'[CHAT] Read deferred: {error}',flush=True)
                    status['social_notice']=str(error)
                    c.record('lobby_social_not_ready',error=str(error))
            status.update(lobby_id=r['steamLobbyId'],map=r['map'],settings=r['settings'],
                roster=[{'name':m['displayName'],'member_id':m['memberIdRaw'],'kind':m['typeRaw'],
                         'team':m.get('teamRaw'),'nation':(r['settings'].get('teamArmies',{}).get(m.get('teamRaw'),'') if r['settings'].get('armySelectionMode')==1 else m['armyRaw']),'ready':m['typeRaw']==2 or bool(m['readyRaw']),'ready_raw':m['readyRaw']} for m in r['rows']])
            if c.active_match:
                early.reset(notify=False)
                match=c.active_match
                record=next(m for m in c.journal.inspect(c.process_key)['matches'] if m['match_id']==c.match_id)
                phase=record['state']
                status['phase']=phase
                if phase=='loading':
                    loading_since=loading_since or time.monotonic()
                    if state['stageVtable']==0xe2fe30 and state['pageVtable']==0xe2ae58 and state['ticks']>0:
                        epoch=r['gameStartTimeRaw']
                        if not epoch or epoch==match['starting_roster']['gameStartTimeRaw']:
                            # The gameplay page can appear before the session card
                            # publishes its new epoch. Keep the Start pending;
                            # never replay it or accept an unchanged generation.
                            status['phase']='loading (waiting for new match generation)'
                            control.publish(token,status)
                            if time.monotonic()-loading_since>loading_timeout:
                                raise TimeoutError('New match generation is unproven after loading timeout')
                            time.sleep(1)
                            continue
                        old=match['starting_roster']
                        identity=lambda roster: sorted((m['memberIdRaw'],m['typeRaw'],m['identityWordsRaw'],
                            sorted((s['slotIdRaw'],s['teamRaw']) for s in roster['slots'] if s['memberIdRaw']==m['memberIdRaw'])) for m in roster['rows'])
                        if r['steamLobbyId']!=old['steamLobbyId'] or identity(r)!=identity(old):
                            raise RuntimeError('Loaded roster/lobby differs from acknowledged Start')
                        match.update(native_game_start_time=epoch,loaded_at=time.time(),loaded_roster=r)
                        c.journal.transition(c.match_id,'loading','playing',match)
                        loading_since=None
                    elif time.monotonic()-loading_since>loading_timeout:
                        raise TimeoutError('Match loading exceeded budget; game preserved')
                elif phase in ('playing','completion_observed') and state['stageVtable']==0xe2fe30:
                    live=c.command('probe',target='live')['probe']
                    status['live']=live
                    from modules.live_game_data import observe_controller
                    observe_controller(c,r,live)
                    c.record('friends_live',match_id=c.match_id,live=live)
                    if live['managerStateRaw']==3:
                        terminal_since=terminal_since or time.monotonic()
                        try:
                            c.capture_completion(live,r)
                        except ValueError as error:
                            c.record('completion_not_ready',error=str(error))
                            status['phase']='waiting for complete results overlay'
                            if time.monotonic()-terminal_since>30:
                                raise TimeoutError('Completion overlay remained incomplete; game preserved') from error
                        else:
                            control.publish(token,{**status,'phase':'saving results / returning to lobby'})
                            c.finish_ai(timeout)
                            c.bind_session()
                            c.save_ai_results(timeout)
                            c.bind_session()
                            status['matches_saved']+=1
                            if restart:
                                restart_pending=match['match_id']
                            terminal_since=None
                            window.update(None,False,time.monotonic())
                elif phase in ('exit_requested','results_available','results_saved') and state['pageVtable']==0xe2b2cc:
                    if phase=='exit_requested':
                        c.journal.transition(c.match_id,'exit_requested','results_available',match)
                    c.bind_session()
                    c.save_ai_results(timeout)
                    c.bind_session()
                    status['matches_saved']+=1
                    if restart:
                        restart_pending=match['match_id']
                else:
                    raise RuntimeError('Unexpected active lifecycle state; game preserved for reconciliation')
            else:
                if state['pageVtable']!=0xe2b2cc:
                    raise RuntimeError('Expected lobby; refusing to host over an unassociated match')
                a=c.command('probe',target='approval')['probe']
                if desired=='run':
                    a=restore_bot_armies(c,a,ai_test,timeout)
                local=[m for m in a['roster']['rows'] if m['memberIdRaw']==a['roster']['localMemberIdRaw']]
                if len(local)==1 and local[0]['typeRaw']==4 and local[0]['readyRaw']==0:
                    # Native start also requires the spectator host to acknowledge Ready.
                    c.command('ready')
                    a=c.command('probe',target='approval')['probe']
                check=readiness(a['roster'],minimum,ai_test,getattr(c,'expected_map',None),requested_team_armies(c),army_selection=requested_army_selection(c))
                gate=c.command('gate')['startAllowed']
                check.update(engine_gate=gate)
                status.update(phase='held' if desired=='hold' else 'waiting for players / ready',readiness=check)
                early_check=readiness(a['roster'],minimum,False,getattr(c,'expected_map',None),requested_team_armies(c),early=True,army_selection=requested_army_selection(c))
                early_due=early.tick(social,a,enabled=desired=='run' and not ai_test,eligible=early_check['ready'],gate=gate)
                status['early_start']={'votes':len(early.votes),'required':len(early_voters(a['roster'])),'eligible':early_check['ready']}
                start_due=window.update(a['approval'],check['ready'] and gate and desired=='run',time.monotonic())
                try:
                    if desired=='run' and not ai_test:
                        social.greet_current()
                    social.game_master_tick(enabled=desired=='run' and not ai_test and window.since is None and early.scope is None)
                except (ValueError,RuntimeError) as error:
                    status['social_notice']=str(error)
                    c.record('lobby_announcement_not_ready',error=str(error))
                if start_due or early_due:
                    # Re-read local controls immediately before issuing the native guarded Start.
                    if control.desired(token)==(desired,sequence):
                        try:
                            start_match(c,a,minimum,ai_test,timeout,early_votes=sorted(early.votes) if early_due else None)
                            early.reset(notify=False)
                        except ReadinessChanged as error:
                            early.reset()
                            c.record('friends_start_precondition_changed',error=str(error))
                            status['phase']='roster changed; restarting readiness countdown'
                        window.update(None,False,time.monotonic())
                elif check['ready'] and gate and desired=='run':
                    status['phase']='ready countdown'
            control.publish(token,status)
            line=f"{status['phase']} | lobby {r['steamLobbyId']} | " + ', '.join(f"{m['displayName']}:{m.get('teamRaw')}:{'ready' if m['typeRaw']==2 or m['readyRaw'] else 'waiting'}" for m in r['rows'])
            if line!=last_print:
                print(line,flush=True)
                last_print=line
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    except Exception as error:
        status.update(phase='needs attention',error=str(error))
        raise
    finally:
        social.close()
        status.update(running=False,phase='stopped' if 'error' not in status else 'needs attention')
        control.publish(token,status)
    return status


def overview(status):
    label='Manual recorder' if status.get('mode')=='record_only' else 'Friends host'
    lines=[f"{label}: {status.get('phase')}" + (' (STALE - controller heartbeat missing)' if status.get('stale') and status.get('running') else '')]
    if status.get('lobby_id'):
        lines.append(f"Lobby: {status['lobby_id']} | Map: {status.get('map')} | Saved this run: {status.get('matches_saved',0)}")
    if status.get('desired'):
        lines.append(f"Control: {status['desired']} | requested {status.get('requested_sequence')} / applied {status.get('applied_sequence',0)}")
    hud=[re.sub(r'<[^>]*>','',n['rawText'] or '') for n in status.get('live',{}).get('hud',[])]
    if hud:
        lines.append('Observed HUD: '+' | '.join(hud))
    for m in status.get('roster',[]):
        ready='ready' if m['ready'] else 'not ready'
        if status.get('phase') in ('playing','loading','completion_observed','playing (record only)'):
            ready='in match'
        lines.append(f"  {m['name']} | {m['team']} | {m['nation'] or '-'} | {ready}")
    lines.extend(status.get('readiness',{}).get('reasons',[]))
    if status.get('error'):
        lines.append('ERROR: '+status['error'])
    if status.get('notice'):
        lines.append(status['notice'])
    if status.get('evidence'):
        lines.append('Evidence: '+status['evidence'])
    return '\n'.join(lines)
