"""Handoff after a known run; preserve evidence and monitor a bounded overnight soak."""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from friends_host import Control
from headless_host import ROOT, GAME_LOG, find_process, process_identity, prevent_idle_sleep
from stress_supervisor import fatal_allocation, terminate_failed_game
from heap_ownership import snapshot
from summarize_allocations import summarize


def safe_handoff(summary, status, log):
    if status.get('desired')=='stop':return False
    return bool((not summary.get('error') and status.get('matches_saved',0)>=2)
                or (summary.get('error') and fatal_allocation(log)))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--after',type=Path,required=True)
    p.add_argument('--music-patch',type=Path,required=True)
    p.add_argument('--music-already-applied',action='store_true')
    p.add_argument('--audio-reset',action='store_true')
    p.add_argument('--low-textures',action='store_true')
    p.add_argument('--hours',type=float,default=8)
    a=p.parse_args()
    if not 0<a.hours<=12:p.error('Duration must be between zero and twelve hours')
    directory=ROOT/'validation'/datetime.now().strftime('overnight_%Y%m%d_%H%M%S')
    directory.mkdir()
    deadline=time.monotonic()+a.hours*3600
    identity=process_identity(find_process())
    (directory/'configuration.json').write_text(json.dumps({'after':str(a.after),'identity':identity,
        'hours':a.hours,'music_patch':str(a.music_patch),'matches_per_process':3,
        'team_a':'heroic','team_b':'easy','vp':75,'mp':10000,'players':6,
        'music_already_applied':a.music_already_applied,'audio_reset':a.audio_reset,
        'low_textures':a.low_textures},indent=2))
    print(directory,flush=True)
    def record(event,**data):
        item={'time':time.time(),'event':event,**data}
        with (directory/'events.jsonl').open('a') as f:f.write(json.dumps(item)+'\n')
        (directory/'status.json').write_text(json.dumps(item,indent=2))
    control=Control(ROOT/'data/friends_control.sqlite3')
    runner=None;last_sample=last_report=0
    with prevent_idle_sleep():
        while time.monotonic()<deadline or (runner is not None and runner.poll() is None):
            status=control.status()
            if (directory/'STOP').exists():
                if status.get('running') and not status.get('stale'):control.request('stop')
                record('stop_requested')
                return
            now=time.monotonic()
            if now-last_sample>=30 and find_process() is not None:
                last_sample=now
                try:
                    result=snapshot(directory)
                    record('heap_sample',pid=result['identity']['pid'],phase=result['phase'],
                           totals_mib=result['totals_mib'],errors=result['traversal_errors'])
                except Exception as error:record('observation_error',error=str(error))
            if now-last_report>=60:
                last_report=now
                evidence=Path(status.get('evidence') or a.after)
                if (evidence/'allocations.jsonl').exists():
                    try:summarize(evidence)
                    except Exception as error:record('report_error',error=str(error))
            if runner is not None:
                if runner.poll() is not None:
                    record('campaign_finished',exit_code=runner.returncode)
                    return
            elif (a.after/'summary.json').exists():
                # The previous runner writes its summary before detaching its probes.
                if time.time()-(a.after/'summary.json').stat().st_mtime<20:
                    time.sleep(5);continue
                summary=json.loads((a.after/'summary.json').read_text())
                log=GAME_LOG.read_text(encoding='utf-8',errors='replace') if GAME_LOG.exists() else ''
                if summary.get('pid')!=identity['pid'] or not safe_handoff(summary,status,log):
                    record('handoff_preserved',reason='User stop or unclassified failure');return
                if GAME_LOG.exists():shutil.copy2(GAME_LOG,directory/'prior_game.log')
                dump_dir=GAME_LOG.parent/'minidumps'
                if dump_dir.exists():
                    for dump in dump_dir.glob('*.mdmp'):
                        if dump.stat().st_mtime>=summary['started']:
                            shutil.copy2(dump,directory/dump.name)
                            record('crash_dump_copied',name=dump.name,bytes=dump.stat().st_size,
                                   empty=dump.stat().st_size==0)
                if find_process() is not None:terminate_failed_game(identity)
                from headless_music_patch import install,digest
                if a.music_already_applied:
                    manifest=json.loads((a.music_patch/'manifest.json').read_text())
                    if digest(Path(manifest['source']))!=manifest['candidate_sha256']:
                        raise RuntimeError('Expected applied music patch changed; preserving files')
                    record('existing_music_patch_verified')
                else:
                    install(a.music_patch)
                    record('music_patch_applied')
                if a.low_textures:
                    from headless_texture_patch import prepare as prepare_textures,install as install_textures
                    texture_directory=directory/'texture_detail'
                    prepare_textures(texture_directory)
                    install_textures(texture_directory)
                    record('low_texture_detail_applied',evidence=str(texture_directory))
                remaining=max(.01,(deadline-time.monotonic())/3600)
                command=[sys.executable,'-u',str(ROOT/'diagnostics/stress_supervisor.py'),
                    '--trace-allocations','--no-reload-caching','--continue-completed',
                    '--matches-per-process','3','--cycles','20','--hours',str(remaining),
                    '--team-a-difficulty','heroic','--team-b-difficulty','easy']
                if a.audio_reset:command+=['--audio-reset']
                with (directory/'campaign.out').open('w') as out,(directory/'campaign.err').open('w') as err:
                    runner=subprocess.Popen(command,cwd=ROOT,stdout=out,stderr=err,
                                            creationflags=subprocess.CREATE_NO_WINDOW)
                record('campaign_started',pid=runner.pid,command=command)
            time.sleep(5)
        record('time_limit_reached')


if __name__=='__main__':main()
