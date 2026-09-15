"""Unbounded same-process 3v3 AI test; never launches or restarts the game."""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime
from functools import wraps
import json
import threading
import time
import traceback

from headless_host import (ROOT, GAME_LOG, HostController, find_process,
                           prevent_idle_sleep, wait_boot, window_state)
from friends_host import Control, prepare, run


class MemoryCounters(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
        'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
        'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]


class SystemCounters(ctypes.Structure):
    _fields_=[('cb',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
        ('CommitTotal','CommitLimit','CommitPeak','PhysicalTotal','PhysicalAvailable',
         'SystemCache','KernelTotal','KernelPaged','KernelNonpaged','PageSize')]+[
        (name,wintypes.DWORD) for name in ('HandleCount','ProcessCount','ThreadCount')]


def serialized(lock, operation):
    """Wait outside RPC deadlines while diagnostics may suspend the game."""
    @wraps(operation)
    def invoke(*args, **kwargs):
        with lock:
            return operation(*args, **kwargs)
    return invoke


def memory_monitor(pid, directory, stop, operation_lock, no_dump=False, trace_holder=None):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    sample = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
    sample.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
    sample.restype = wintypes.BOOL
    system_sample=ctypes.WinDLL('psapi',use_last_error=True).GetPerformanceInfo
    system_sample.argtypes=[ctypes.POINTER(SystemCounters),wintypes.DWORD]
    system_sample.restype=wintypes.BOOL
    handle = kernel.OpenProcess(0x410, False, pid)
    from memory_diagnostics import Diagnostics
    diagnostics=Diagnostics(handle,pid,directory)
    diagnostics.dump_attempted=no_dump
    control=Control(ROOT/'data/friends_control.sqlite3')
    try:
        with (directory/'memory.jsonl').open('a', encoding='utf-8') as output:
            while not stop.is_set():
                counters = MemoryCounters()
                counters.cb = ctypes.sizeof(counters)
                item = {'time': time.time(), 'pid': pid}
                if handle and sample(handle, ctypes.byref(counters), counters.cb):
                    item.update({name: getattr(counters, name) for name, _ in counters._fields_})
                else:
                    item['error'] = ctypes.get_last_error()
                system=SystemCounters();system.cb=ctypes.sizeof(system)
                if system_sample(ctypes.byref(system),system.cb):
                    item['system']={name:getattr(system,name)*system.PageSize for name in
                        ('CommitTotal','CommitLimit','PhysicalTotal','PhysicalAvailable')}
                try:
                    context=control.status()
                    if context.get('evidence')!=str(directory):context={}
                    item.update(match_id=context.get('match_id'),phase=context.get('phase'))
                    with operation_lock:
                        diagnostics.observe(item,context)
                        if trace_holder:
                            largest=getattr(diagnostics,'latest_report',{}).get('largest_free_region')
                            if largest is not None and largest<16*1024**2:
                                item['trace_snapshot_skipped']='Contiguous free VA below 16 MiB; native fixed-size tracking and failure hook remain active'
                                trace_holder[0].snapshot({k:context.get(k) for k in
                                    ('match_id','phase','matches_saved','roster')},light=True)
                            else:
                                trace_holder[0].snapshot({k:context.get(k) for k in
                                    ('match_id','phase','matches_saved','roster')})
                except Exception as error:
                    item['diagnostic_error']=str(error)
                output.write(json.dumps(item)+'\n')
                output.flush()
                stop.wait(5)
    finally:
        if handle:
            kernel.CloseHandle(handle)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mixed',action='store_true',help='Use the existing approved human/bot lobby')
    parser.add_argument('--no-dump',action='store_true',help='Keep memory monitoring but skip additional full dumps')
    parser.add_argument('--resource-cleanup',action='store_true',help='Experimental native cache cleanup; does not cure fragmentation')
    parser.add_argument('--audio-reset',action='store_true',help='Experimental native audio reconfiguration after saved matches')
    parser.add_argument('--matches-per-process',type=int,default=None,help='Stop normally after this many saved matches')
    parser.add_argument('--trace-allocations',action='store_true',help='Sample active allocator lifetimes and observe reload cleanup')
    parser.add_argument('--team-a-difficulty',choices=['easy','normal','hard','heroic'],default='normal')
    parser.add_argument('--team-b-difficulty',choices=['easy','normal','hard','heroic'],default='normal')
    for team in ('a','b'):
        parser.add_argument(f'--team-{team}-army',choices=['ger','rus','usa','eng','jap','axis_minor','ger_ss','rus_guard'])
    args=parser.parse_args()
    if args.mixed and (args.team_a_army or args.team_b_army):
        parser.error('Fixed faction configuration requires the all-bot test mode')
    if args.matches_per_process is not None and args.matches_per_process<1:
        parser.error('--matches-per-process must be positive')
    pid = find_process()
    if pid is None:
        raise RuntimeError('No existing game. This test never launches or restarts it.')
    directory = ROOT/'validation'/datetime.now().strftime('stability_%Y%m%d_%H%M%S')
    directory.mkdir(parents=True)
    print(f'STABILITY PID {pid}; evidence: {directory}', flush=True)
    stop = threading.Event()
    operation_lock = threading.RLock()
    trace_holder=[]
    monitor = threading.Thread(target=memory_monitor, args=(pid,directory,stop,operation_lock,args.no_dump,trace_holder), daemon=True)
    controller = None
    summary = {'pid':pid, 'map':'multi/3v3_big_desert_town:battle_zones',
               'players':6, 'victory_points':75, 'manpower':10000, 'started':time.time(),
               'resource_cleanup':args.resource_cleanup}
    summary['bot_difficulties']={'a':args.team_a_difficulty,'b':args.team_b_difficulty}
    summary['bot_armies']={'a':args.team_a_army,'b':args.team_b_army}
    summary['audio_reset']=args.audio_reset
    with prevent_idle_sleep(), (directory/'activity.jsonl').open('a',encoding='utf-8') as activity:
        monitor.start()
        try:
            wait_boot(pid,120)
            controller = HostController(pid,directory)
            controller.state = serialized(operation_lock, controller.state)
            controller.command = serialized(operation_lock, controller.command)
            controller.expected_map = summary['map']
            controller.expected_bot_armies = summary['bot_armies']
            controller.rating_profile = 'robz-battle-zones'
            with operation_lock:
                controller.attach()
                if args.trace_allocations:
                    summary['reload_cache_option']=controller.command('probe',target='reload-cache')['probe']
                    controller.record('reload_cache_option',**summary['reload_cache_option'])
                    print('Native reload cache option:',summary['reload_cache_option'],flush=True)
                    from allocation_trace import AllocationTrace
                    trace_holder.append(AllocationTrace(pid,directory))
                    trace_holder[0].snapshot({'phase':'before_host'})
            window_state(pid,minimize=True)
            controller.monitor_background = True
            if args.resource_cleanup:
                save_results=controller.save_ai_results
                def save_and_cleanup(timeout):
                    result=save_results(timeout)
                    resources=controller.command('cleanup-resources')['resourceCleanup']
                    heap=controller.command('optimize-heap')['heapOptimization']
                    controller.record('post_match_resource_cleanup',resources=resources,heap=heap)
                    print(f"PASS native resource cleanup: {resources['beforeResources']} -> {resources['afterResources']} entries",flush=True)
                    return result
                controller.save_ai_results=save_and_cleanup
            if args.audio_reset:
                save_before_audio_reset=controller.save_ai_results
                def save_and_reset_audio(timeout):
                    result=save_before_audio_reset(timeout)
                    audio=controller.command('reset-audio-cache')['audioReset']
                    controller.record('post_match_audio_reset',**audio)
                    print(f"PASS native audio reset: {audio['before']['sampleEntries']} -> {audio['after']['sampleEntries']} samples",flush=True)
                    return result
                controller.save_ai_results=save_and_reset_audio
            original_record = controller.record
            previous = {}
            def record(event, **data):
                original_record(event, **data)
                if event == 'friends_live':
                    live = data['live']
                    cells = {cell['name']:cell['rawText'] for cell in live.get('hud',[])}
                    key = data.get('match_id')
                    changes = {name:value for name,value in cells.items()
                               if previous.get(key,{}).get(name) != value}
                    activity.write(json.dumps({'time':time.time(), 'match_id':key,
                        'manager_state':live.get('managerStateRaw'), 'hud':cells,
                        'changed_cells':changes, 'scope':'raw HUD; team/counter meanings unverified'})+'\n')
                    activity.flush()
                    previous.clear()
                    previous[key] = cells
            controller.record = record
            if controller.active_match and (args.team_a_army or args.team_b_army):
                raise RuntimeError('Fixed factions must be configured from an unloaded lobby, not an active-match resume')
            if not controller.active_match and not args.mixed:
                controller.host_lobby(120)
                controller.bind_session()
                controller.configure_ai(120)
                roster = prepare(controller,120,6)
                if roster['map'] != summary['map']:
                    raise RuntimeError('Expected desert map; refusing to start on a different map')
                for slot in roster['slots']:
                    if slot['teamRaw'] in ('a','b') and slot['memberIdRaw'] == 0:
                        controller.assign_ai(slot['slotIdRaw'],summary['bot_difficulties'][slot['teamRaw']],120)
                roster=controller.command('probe',target='roster')['probe']
                for member in roster['rows']:
                    army=summary['bot_armies'].get(member['teamRaw'])
                    if member['typeRaw']==2 and army:
                        controller.set_bot_army(member['memberIdRaw'],army,120)
            summary['result'] = run(controller,Control(ROOT/'data/friends_control.sqlite3'),
                minimum=6, ready_seconds=5, timeout=120, ai_test='mixed' if args.mixed else True,
                max_matches=args.matches_per_process)
        except BaseException:
            summary['error'] = traceback.format_exc()
            (directory/'error.txt').write_text(summary['error'],encoding='utf-8')
            raise
        finally:
            stop.set()
            monitor.join(10)
            summary['ended'] = time.time()
            (directory/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
            if GAME_LOG.exists():
                (directory/'game_log.txt').write_bytes(GAME_LOG.read_bytes())
            if controller:
                controller.close()
            if trace_holder:
                try:
                    trace_holder[0].snapshot({'phase':'runner_exit'})
                finally:
                    try:trace_holder[0].close()
                    finally:
                        from summarize_allocations import summarize
                        summarize(directory)


if __name__ == '__main__':
    main()
