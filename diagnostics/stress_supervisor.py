"""Continue the bot soak after confirmed fatal allocation failures.

No proactive memory recycling: preserve same-process repetitions until failure.
Other controller failures stop for inspection. friends-stop stops the campaign.
"""
import _bootstrap  # Set up imports for direct CLI execution.
import ctypes
import argparse
from ctypes import wintypes
from datetime import datetime
import json
import shutil
import subprocess
import sys
import time

from headless_host import ROOT, GAME_LOG, find_process, find_game_executable, process_identity
from friends_host import Control


def completed_restart(restart_after_match, exit_code, status):
    return bool(restart_after_match and exit_code==0 and status.get('desired')=='run'
                and not status.get('error') and status.get('matches_saved',0)>=1)


def fatal_allocation(log):
    block=log.rsplit('***************** Exception *****************',1)
    return (len(block)==2 and 'Failed to allocate memory.' in block[1]
            and 'ememory.cpp, 94' in block[1])


def new_fatal_allocation(log, baseline):
    """Require a fresh exception, not ordinary text appended after an old one."""
    marker='***************** Exception *****************'
    if not fatal_allocation(log):return False
    if log.startswith(baseline):
        return marker in log[len(baseline):]
    previous=baseline.rsplit(marker,1)
    current=log.rsplit(marker,1)[1]
    if len(previous)==2 and (current.startswith(previous[1]) or previous[1].startswith(current)):
        return False  # Rewritten/partial old exception remains ambiguous.
    return True


def terminate_failed_game(identity):
    """Hold and validate the process handle so a reused PID cannot be killed."""
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x101001,False,identity['pid'])
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    try:
        times=[wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*(ctypes.byref(t) for t in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        creation=str((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)
        if creation!=identity['creation_filetime']:
            raise RuntimeError('Process identity changed; refusing termination')
        if not kernel.TerminateProcess(handle,1):
            raise ctypes.WinError(ctypes.get_last_error())
        if kernel.WaitForSingleObject(handle,15000)!=0:
            raise RuntimeError('Terminated game did not finish exiting within 15 seconds')
    finally:
        kernel.CloseHandle(handle)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restart-after-match',action='store_true',help='Preserve results then launch a fresh process for every match')
    parser.add_argument('--trace-allocations',action='store_true')
    parser.add_argument('--audio-reset',action='store_true')
    parser.add_argument('--team-a-difficulty',choices=['easy','normal','hard','heroic'],default='normal')
    parser.add_argument('--team-b-difficulty',choices=['easy','normal','hard','heroic'],default='normal')
    for team in ('a','b'):
        parser.add_argument(f'--team-{team}-army',choices=['ger','rus','usa','eng','jap','axis_minor','ger_ss','rus_guard'])
    parser.add_argument('--no-reload-caching',action='store_true',help='Experimental native launch option; traced query verifies behavior')
    parser.add_argument('--matches-per-process',type=int,default=None)
    parser.add_argument('--cycles',type=int,default=None,help='Bound the diagnostic campaign, including failed processes')
    parser.add_argument('--hours',type=float,default=None,help='Stop launching processes after this duration; let an active runner finish')
    parser.add_argument('--continue-completed',action='store_true',help='Restart after a successfully completed bounded multi-match run')
    args=parser.parse_args()
    if any(x is not None and x<1 for x in (args.matches_per_process,args.cycles)):
        parser.error('Match and cycle limits must be positive')
    if args.hours is not None and args.hours<=0:parser.error('--hours must be positive')
    if args.continue_completed and not (args.matches_per_process or args.restart_after_match):
        parser.error('--continue-completed requires a match limit')
    deadline=time.monotonic()+args.hours*3600 if args.hours else float('inf')
    directory=ROOT/'validation'/datetime.now().strftime('campaign_%Y%m%d_%H%M%S')
    directory.mkdir()
    print(f'Campaign evidence: {directory}',flush=True)
    def record(event,**data):
        item=dict(time=time.time(),event=event,**data)
        with (directory/'events.jsonl').open('a',encoding='utf-8') as out:
            out.write(json.dumps(item)+'\n')
        (directory/'status.json').write_text(json.dumps(item,indent=2),encoding='utf-8')
        print(event,flush=True)
    cycle=0
    try:
        if find_process() is not None:
            raise RuntimeError('Campaign requires no existing game; preserve/reconcile it first')
        while (args.cycles is None or cycle<args.cycles) and time.monotonic()<deadline:
            cycle+=1
            executable=find_game_executable()
            if executable is None: raise RuntimeError('Game executable not found')
            startup=subprocess.STARTUPINFO()
            startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow=0
            launch=[str(executable)]+(['-no_reload_caching'] if args.no_reload_caching else [])
            game=subprocess.Popen(launch,cwd=executable.parent,startupinfo=startup)
            launched_at=time.time()
            identity=process_identity(game.pid)
            baseline=GAME_LOG.read_bytes() if GAME_LOG.exists() else b''
            record('game_launched',cycle=cycle,identity=identity,arguments=launch[1:])
            with (directory/f'runner_{cycle}.out').open('w') as out, (directory/f'runner_{cycle}.err').open('w') as err:
                command=[sys.executable,'-u',str(ROOT/'diagnostics/stability_loop.py'),'--no-dump']
                command+=['--team-a-difficulty',args.team_a_difficulty,'--team-b-difficulty',args.team_b_difficulty]
                for team in ('a','b'):
                    army=getattr(args,f'team_{team}_army')
                    if army:command += [f'--team-{team}-army',army]
                if args.restart_after_match: command+=['--matches-per-process','1']
                elif args.matches_per_process:command+=['--matches-per-process',str(args.matches_per_process)]
                if args.trace_allocations:command+=['--trace-allocations']
                if args.audio_reset:command+=['--audio-reset']
                runner=subprocess.Popen(command,
                    cwd=ROOT,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
                result=runner.wait()
            current=GAME_LOG.read_bytes() if GAME_LOG.exists() else b''
            (directory/f'game_{cycle}.log').write_bytes(current)
            # Preserve the game's own small crash dumps before any restart.
            dumps=GAME_LOG.parent/'minidumps'
            if dumps.exists():
                for dump in dumps.glob('*.mdmp'):
                    if dump.stat().st_mtime>=launched_at-2:
                        shutil.copy2(dump,directory/f'cycle_{cycle}_{dump.name}')
                        record('crash_dump_copied',cycle=cycle,name=dump.name,bytes=dump.stat().st_size,
                               empty=dump.stat().st_size==0)
            record('runner_exited',cycle=cycle,exit_code=result)
            if Control(ROOT/'data/friends_control.sqlite3').status().get('desired')!='run':
                record('stopped',reason='Control no longer requests running; game/evidence preserved')
                return
            if completed_restart(args.restart_after_match or args.continue_completed,result,Control(ROOT/'data/friends_control.sqlite3').status()):
                record('completed_match_restart',cycle=cycle,identity=identity)
                if game.poll() is None:
                    game.terminate()
                    game.wait(timeout=15)
                time.sleep(5)
                continue
            if result==0:
                record('stopped',reason='controller stopped normally; game left running')
                return
            if game.poll() is None:
                if not new_fatal_allocation(current.decode('utf-8',errors='replace'),baseline.decode('utf-8',errors='replace')):
                    raise RuntimeError('Controller failed without a new fatal allocation log; game preserved')
                record('fatal_allocation',cycle=cycle,identity=identity)
                if args.cycles is not None and cycle>=args.cycles:
                    record('diagnostic_failure_preserved',cycle=cycle,identity=identity)
                    return
                terminate_failed_game(identity)
                game.wait(timeout=15)
            else:
                record('game_exited',cycle=cycle,exit_code=game.returncode)
            # Backoff prevents rapid repeated failures from creating a restart storm.
            time.sleep(15)
        record('campaign_limit_reached',cycles=cycle)
    except BaseException as error:
        record('needs_attention',error=str(error))
        raise


if __name__=='__main__':
    main()
