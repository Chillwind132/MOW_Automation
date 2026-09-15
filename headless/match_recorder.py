"""Observe manually hosted matches. Never start, configure, select tabs, exit or dismiss."""
import time

from lobby_social import LobbySocial
from modules.live_game_data import associate_loaded


def save_lobby_results(c,roster=None,objects=None):
    from modules.end_game_results import wait_for_match
    result=wait_for_match(c.journal.path,c.active_match,timeout=0)
    record=next(m for m in c.journal.inspect(c.process_key)['matches'] if m['match_id']==c.match_id)
    if record['state']=='results_saved': return False
    c.active_match.update(final_results_source=result['source'],engine_outcome=result['engine_outcome'],replay=result['replay'])
    c.journal.transition(c.match_id,record['state'],'results_saved',c.active_match)
    c.record('manual_replay_results_saved',match_id=c.match_id)
    return True



def run(c,control,duration=None):
    if not c.record_only:
        raise RuntimeError('Recorder requires enforced record-only bridge')
    token=control.begin(held=True)
    status={'running':True,'mode':'record_only','phase':'watching manual lobby',
            'evidence':str(c.directory),'matches_saved':0}
    started=time.monotonic()
    prior=None
    last_line=None
    last_results_poll=0
    completed=set()
    social=LobbySocial(c)
    try:
        if c.active_match and c.recovery['status']=='needs_reconciliation':
            raise RuntimeError('Existing match identity needs reconciliation; observer cannot guess')
        while duration is None or time.monotonic()-started<duration:
            desired,sequence=control.desired(token)
            status.update(applied_sequence=sequence,match_id=c.match_id)
            if desired=='stop':
                break
            if c.active_match:
                try:
                    created=save_lobby_results(c)
                except TimeoutError:
                    pass
                else:
                    status['matches_saved']+=int(created)
                    status['last_saved_match']=c.match_id
                    c.journal.transition(c.match_id,'results_saved','lobby_returned',c.active_match)
                    c.active_match=None
                    c.match_id=None
            state=c.state()
            page=state['pageVtable']
            if page not in (0xe2b2cc,0xe2ae58):
                status['phase']='observing loading / menu (no game actions)'
                control.publish(token,status)
                time.sleep(1)
                continue
            r=c.command('probe',target='roster')['probe']
            if page==0xe2b2cc and not c.active_match:
                try:
                    social.poll()
                    status.pop('social_notice',None)
                except (ValueError,RuntimeError) as error:
                    status['social_notice']=str(error)
                    c.record('lobby_social_not_ready',error=str(error))
            if c.active_match and r['gameStartTimeRaw']!=c.active_match.get('native_game_start_time'):
                from modules.live_game_data import record_controller
                record_controller(c,'event','native_generation_changed',dict(roster=r))
                record=next(m for m in c.journal.inspect(c.process_key)['matches'] if m['match_id']==c.match_id)
                if record['state']=='results_saved':
                    c.journal.transition(c.match_id,'results_saved','lobby_returned',{'reason':'saved results followed by a new native generation'})
                    c.active_match=None
                    c.match_id=None
                else:
                    raise RuntimeError('New game observed before prior results were saved; evidence preserved')
            status.update(lobby_id=r['steamLobbyId'],map=r['map'],settings=r['settings'],
                roster=[{'name':m['displayName'],'member_id':m['memberIdRaw'],'kind':m['typeRaw'],
                         'team':m.get('teamRaw'),'nation':m['armyRaw'],'ready':bool(m['readyRaw'])} for m in r['rows']])
            if not c.active_match and (prior is None or r['steamLobbyId']!=prior['steamLobbyId']):
                c.bind_session()
            if page==0xe2ae58:
                if not c.active_match:
                    try:
                        associate_loaded(c,r,prior)
                    except ValueError as error:
                        status.update(phase='waiting for stable loaded identity',notice=str(error))
                        control.publish(token,status)
                        time.sleep(1)
                        continue
                status['phase']='playing (record only)'
                live=c.command('probe',target='live')['probe']
                status['live']=live
                from modules.live_game_data import observe_controller
                observe_controller(c,r,live)
                c.record('recorder_live',match_id=c.match_id,live=live)
                if c.active_match and live['managerStateRaw']==3 and c.match_id not in completed:
                    try:
                        c.capture_completion(live,r)
                        completed.add(c.match_id)
                        status['phase']='finish observed; waiting for saved replay'
                    except ValueError as error:
                        c.record('completion_not_ready',error=str(error))
            else:
                status.pop('live',None)
                prior=r
                status['phase']='watching manual lobby'
                if c.active_match:
                    status['phase']='waiting for completed replay (results screen not required)'
            control.publish(token,status)
            line=f"{status['phase']} | map {r['map']} | match {c.match_id or '-'} | saved {status['matches_saved']}"
            if line!=last_line:
                print(line,flush=True)
                last_line=line
            time.sleep(0.25 if page==0xe2b2cc and c.active_match else 1)
    except KeyboardInterrupt:
        pass
    except Exception as error:
        status.update(phase='needs attention',error=str(error))
        raise
    finally:
        status.update(running=False,phase='stopped' if 'error' not in status else 'needs attention')
        control.publish(token,status)
    return status
