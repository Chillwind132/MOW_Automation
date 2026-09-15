"""Launch/resume AS2 into multiplayer gameplay without foreground input.

Run: py headless_host.py run --minimize
Inspect: py headless_host.py status
Validate existing gameplay: py headless_host.py check --stable-seconds 15
Requires the Steam client, the supported retail executable, frida 17.5.0, pymem.
Uses the game's remembered map and lobby settings. Does not restart matches.
"""
import argparse
from contextlib import contextmanager, closing, ExitStack
import ctypes
from ctypes import wintypes
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import winreg
import sys
import threading
import time
import traceback
import uuid

sys.path.append(str(Path(__file__).resolve().parents[1]))

import frida
import pymem
import pymem.pattern
from match_journal import Journal, ProcessLock, fingerprint, reconcile
from modules.live_game_data import participants, controlled_ai
from completion_guard import completion_signature

ROOT = Path(__file__).resolve().parent.parent
GAME_LOG = Path.home() / 'Documents/my games/men of war - assault squad 2/log/game.log'
SUPPORTED_SHA256 = '3bc956732844aab0f4028cafecc74a9c0fc73abd6afc618bad5c4e9de537e64f'
MAIN_MENU, INTERNET, SETUP, LOBBY, GAME = 0xe212f8, 0xe2fcc4, 0xe2fd60, 0xe2fee8, 0xe2fe30
LOBBY_PAGE, GAME_HUD = 0xe2b2cc, 0xe2ae58


def scan_with_partial_copy_retry(handle, pattern, attempts=3):
    """Retry a whole read-only scan when pages change during ReadProcessMemory."""
    for attempt in range(attempts):
        try:
            return pymem.pattern.pattern_scan_all(handle,pattern,return_multiple=True)
        except pymem.exception.WinAPIError as error:
            if error.error_code!=299 or attempt==attempts-1:
                raise
            time.sleep(0.15)


@contextmanager
def prevent_idle_sleep():
    """Hold a system-only power request on this thread for the command lifetime."""
    continuous, system_required = 0x80000000, 0x00000001
    set_state = ctypes.windll.kernel32.SetThreadExecutionState
    set_state.argtypes = [wintypes.DWORD]
    set_state.restype = wintypes.DWORD
    previous = set_state(continuous | system_required)
    if not previous:
        raise RuntimeError('Windows refused the request to prevent idle sleep')
    try:
        print('Idle sleep blocked while this command runs; screen may turn off.', flush=True)
        yield
    finally:
        if not set_state(previous | continuous):
            print('WARNING could not restore thread power state; it clears on process exit.',
                  file=sys.stderr, flush=True)


@contextmanager
def bounded(seconds):
    """Cancel a blocked Frida RPC/attach/detach instead of waiting forever."""
    cancellation = frida.Cancellable()
    timer = threading.Timer(seconds, cancellation.cancel)
    timer.daemon = True
    timer.start()
    try:
        with cancellation:
            yield
    except frida.OperationCancelledError as error:
        raise TimeoutError(f'Frida operation exceeded {seconds}s; inspect state before retrying') from error
    finally:
        timer.cancel()


def valid_engine(state):
    return (state.get('coreVtable') in (0xe25660, 0xe2568c)
            and state.get('sessionVtable') == 0xd9f744)


def gameplay_loaded(state):
    # eGameStage exists before the map has finished loading: require the HUD too.
    return (valid_engine(state) and state.get('stageVtable') == GAME
            and state.get('pageVtable') == GAME_HUD)


def lobby_loaded(state):
    return (valid_engine(state) and state.get('stageVtable') == LOBBY
            and state.get('pageVtable') == LOBBY_PAGE
            and state.get('serviceVtable') == 0xde0fd0
            and state.get('card') not in (None, '0x0') and bool(state.get('map')))


def wait_for(sample, predicate, timeout, *, stable_seconds=0, clock=time.monotonic, sleep=time.sleep):
    """Require the condition continuously, plus a live main-loop heartbeat."""
    deadline = clock() + timeout
    stable_since = None
    first_ticks = None
    previous_ticks = None
    last_progress = None
    last = None
    while clock() < deadline:
        last = sample()
        if predicate(last):
            if stable_since is None:
                stable_since, first_ticks = clock(), last.get('ticks', 0)
                previous_ticks, last_progress = first_ticks, clock()
            current_ticks = last.get('ticks', 0)
            if current_ticks > previous_ticks:
                previous_ticks, last_progress = current_ticks, clock()
            if stable_seconds and clock() - last_progress > 2:
                raise TimeoutError('Main-loop heartbeat stalled despite apparently valid engine state')
            if clock() - stable_since >= stable_seconds:
                if stable_seconds == 0 or last.get('ticks', 0) > first_ticks:
                    return last
        else:
            stable_since = first_ticks = None
        sleep(.5)
    raise TimeoutError(f'Engine state did not satisfy validation in {timeout}s; last={last}')


def find_process():
    matches = [p.pid for p in frida.get_local_device().enumerate_processes()
               if p.name.lower() == 'mowas_2.exe']
    if len(matches) > 1:
        raise RuntimeError('Multiple game processes found; specify --pid')
    return matches[0] if matches else None


def find_game_executable():
    """Locate the retail install in Steam's default or additional libraries."""
    roots = [Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Steam']
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
            roots.insert(0, Path(winreg.QueryValueEx(key, 'SteamPath')[0]))
    except OSError:
        pass
    libraries = list(roots)
    for root in roots:
        try:
            config = (root / 'steamapps/libraryfolders.vdf').read_text(encoding='utf-8')
            libraries.extend(Path(value.replace('\\\\', '\\'))
                             for value in re.findall(r'"path"\s*"([^"\r\n]+)"', config))
        except OSError:
            continue
    for library in dict.fromkeys(libraries):
        try:
            manifest = (library / 'steamapps/appmanifest_244450.acf').read_text(encoding='utf-8')
        except OSError:
            continue
        match = re.search(r'"installdir"\s*"([^"\r\n]+)"', manifest)
        if match:
            executable = library / 'steamapps/common' / match[1] / 'mowas_2.exe'
            if executable.is_file():
                return executable
    return None


def ensure_process(action, pid=None, timeout=120):
    pid=pid or find_process()
    if pid is not None:
        return pid
    if action not in ('run','lobby','solo','friends-prepare','friends-host'):
        raise RuntimeError('Game is not running')
    executable = find_game_executable()
    if executable is not None:
        print(f'Launching AS2 directly: {executable}', flush=True)
        try:
            # Verified during the overnight fixed-faction batches. Persist this
            # launch policy in the host, rather than relying on a one-off shell.
            from host_restart import launch_game
            launch_game(executable)
        except OSError as error:
            print(f'Direct launch failed ({error}); falling back to Steam...', flush=True)
            os.startfile('steam://rungameid/244450')
            print('Steam fallback: -no_reload_caching is not guaranteed; set it in Steam launch options.', flush=True)
    else:
        print('Game executable not found; launching AS2 through Steam...', flush=True)
        os.startfile('steam://rungameid/244450')
        print('Steam fallback: -no_reload_caching is not guaranteed; set it in Steam launch options.', flush=True)
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        time.sleep(.5)
        pid=find_process()
        if pid is not None:
            return pid
    raise TimeoutError('Game process did not appear after launch')


def wait_boot(pid, timeout, poll=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if poll:
            poll()
        pm = None
        try:
            pm = pymem.Pymem(pid)
            if pm.read_bytes(0xb0dbc0, 4) == bytes.fromhex('558bec68') and pm.read_uint(0xfeaac0):
                return
        except (pymem.exception.PymemError, OSError):
            pass
        finally:
            if pm is not None:
                pm.close_process()
        time.sleep(.5)
    raise TimeoutError('Game did not finish unpacking/loading its main menu')


def process_path(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD(32768)
        path = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return Path(path.value)
    finally:
        kernel.CloseHandle(handle)


def window_state(pid, minimize=False):
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsIconic.argtypes = [wintypes.HWND]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    foreground = user.GetForegroundWindow()
    foreground_pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid))
    windows = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    @callback_type
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user.IsWindowVisible(hwnd):
            if minimize:
                user.ShowWindowAsync(hwnd, 6)
            windows.append({'handle':int(hwnd), 'minimized':bool(user.IsIconic(hwnd))})
        return True
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows(visit, 0)
    return {'foregroundPid':foreground_pid.value,'gameForeground':foreground_pid.value == pid,'windows':windows}


def process_identity(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)]*4
    handle = kernel.OpenProcess(0x1000,False,pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*(ctypes.byref(t) for t in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        path = process_path(pid)
        return {'pid':pid,'creation_filetime':str((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime),
                'executable_path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'version':'3.262.1' if hashlib.sha256(path.read_bytes()).hexdigest() == SUPPORTED_SHA256 else None}
    finally:
        kernel.CloseHandle(handle)


def background_window(state):
    return (state.get('gameForeground') is False and bool(state.get('windows'))
            and all(window.get('minimized') is True for window in state['windows']))


def background_result(violations, strict=False):
    """Window visibility is an observation, never an engine failure."""
    return {'status':'interrupted' if violations else 'passed',
            'scope':'sampled_window_state', 'strict':strict,
            'validation_passed':not violations,
            'exit_code':2 if strict and violations else 0,
            'cause':'unknown' if violations else None}


class HostController:
    def __init__(self, pid, directory):
        self.pid, self.directory = pid, directory
        directory.mkdir(parents=True, exist_ok=True)
        self.log = (directory / 'events.jsonl').open('w', encoding='utf-8')
        self.lock = threading.Lock()
        self.session = self.script = None
        self.selected_map = None
        self.monitor_background = False
        self.background_violations = []
        self.process_lock = self.journal = None
        self.match_id = None
        self.record_only = False
        self.diagnostics = None
        self.last_command = self.last_probe_step = self.last_engine_state = None
        self.detachment = None
        self.next_heartbeat = 0

    def observe_window(self):
        observed = window_state(self.pid)
        self.record('window_observation', **observed)
        if not background_window(observed):
            self.background_violations.append(observed)
        return observed

    def record(self, event, **data):
        with self.lock:
            if not self.log.closed:
                self.log.write(json.dumps({'time':time.time(),'event':event,**data}) + '\n')
                self.log.flush()

    def attach(self):
        self.identity = process_identity(self.pid)
        digest = self.identity['sha256']
        self.record('binary', **self.identity)
        if digest != SUPPORTED_SHA256:
            raise RuntimeError('Unsupported game executable; refusing fixed-address calls')
        from host_diagnostics import ProcessDiagnostics
        try:
            self.diagnostics = ProcessDiagnostics(self.pid)
        except OSError as error:
            self.record('process_diagnostics_unavailable', error=str(error))
            print(f'[HOST] Exit-code diagnostics unavailable: {error}', flush=True)
        self.process_lock = ProcessLock(ROOT/'data/controller_locks', self.identity)
        self.journal = Journal(ROOT/'data/rankbot.sqlite3')
        from modules.end_game_results import ensure_watcher
        ensure_watcher(self.journal.path)
        from modules.live_game_data import Participation
        self.participation=Participation(self.journal.path)
        from modules.live_game_data import MatchTelemetry
        self.match_telemetry=MatchTelemetry(self.journal.path,getattr(self,'snapshot_seconds',30))
        self.process_key = fingerprint(self.identity)
        with bounded(10):
            self.session = frida.attach(self.pid)
            self.session.on('detached', self.on_detached)
            from modules.live_game_data import compose_bridge
            source = compose_bridge(Path(__file__).with_suffix('.js'))
            self.record('host_sources', python_path=str(Path(__file__).resolve()),
                        python_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        script_sha256=hashlib.sha256(source.encode('utf-8')).hexdigest())
            self.script = self.session.create_script(source)
            self.script.on('message', self.instrumentation_message)
            self.script.load()
            if self.record_only:
                self.script.exports_sync.readonly()
        self.bind_session()

    def on_detached(self, reason, crash):
        self.detachment = {'reason': reason, 'crash': str(crash) if crash else None}
        self.record('detached', **self.detachment)
        from modules.live_game_data import record_controller
        record_controller(self,'event','game_process_exited' if reason=='process-terminated' else 'instrumentation_detached',
                          dict(detachment=self.detachment))

    def failure_diagnostics(self):
        evidence = {'process': self.diagnostics.snapshot() if self.diagnostics else None,
                    'detachment': self.detachment, 'last_command': self.last_command,
                    'last_probe_step': self.last_probe_step, 'last_state': self.last_engine_state}
        self.record('failure_diagnostics', **evidence)
        from modules.live_game_data import record_controller
        record_controller(self,'event','observation_failed',evidence)
        return evidence

    def instrumentation_message(self,message,data):
        self.record('instrumentation',message=message)
        payload=message.get('payload',{}) if message.get('type')=='send' else {}
        if payload.get('event') == 'social_probe_step':
            self.last_probe_step = payload
        if payload.get('event')=='native_lobby_membership':
            try:
                event=self.participation.native(payload,getattr(self,'active_match',None))
                match=getattr(self,'active_match',None)
                if event['match_id'] or (isinstance(match,dict) and payload.get('lobby_id')==match.get('starting_roster',{}).get('steamLobbyId')):
                    from modules.live_game_data import record_controller
                    record_controller(self,'event','steam_lobby_membership',dict(participation_event=event,
                        association='same_observed_match_lobby; outside-play events do not prove gameplay departure'),deduplicate=False)
            except Exception as error:
                self.record('participation_capture_error',error=str(error))

    def bind_session(self):
        state = self.state()
        roster=None
        native = {'session':state['session'],'steam_lobby_id':None,
                  'steam_lobby_status':'unavailable','source':'guarded_engine_session_pointer_with_process_creation'}
        if lobby_loaded(state) or gameplay_loaded(state):
            roster=self.command('probe',target='roster')['probe']
            native.update(steam_lobby_id=roster['steamLobbyId'],steam_lobby_status='observed',card=roster['card'])
        if self.record_only and roster is None:
            self.match_id=None
            self.active_match=None
            self.recovery={'status':'waiting_for_lobby','match_id':None,'may_mutate':False}
            self.record('recovery_decision',**self.recovery)
            return
        self.process_key,self.host_session_id = self.journal.register(self.identity,native)
        self.record('journal_attachment',process_key=self.process_key,host_session_id=self.host_session_id,
                    journal=self.journal.inspect(self.process_key))
        record=self.journal.inspect(self.process_key)
        if self.record_only and native['steam_lobby_id']:
            # A different Steam lobby is an independent observation scope.
            # Keep earlier matches durable even if their lobby export was missed.
            record=dict(record)
            record['matches']=[m for m in record['matches']
                if not m['latest_match_observation'].get('starting_roster',{}).get('steamLobbyId')
                or m['latest_match_observation']['starting_roster']['steamLobbyId']==native['steam_lobby_id']]
        if self.record_only:
            # A complete, identity-checked persisted replay closes an observation
            # even when the recorder was stopped before the user left the game.
            from modules.end_game_results import load_result
            for item in record['matches']:
                final=load_result(self.journal.path,item['match_id']) or {}
                if (item['state'] not in ('failed','lobby_returned')
                        and item['latest_match_observation'].get('hosting_mode')=='record_only'
                        and final.get('source')=='persisted_replay_battleInfoTotal'):
                    self.journal.transition(item['match_id'],item['state'],'lobby_returned',
                        dict(item['latest_match_observation'],final_results_source=final['source'],replay=final['replay'],
                             engine_outcome=final['engine_outcome']))
                    item['state']='lobby_returned'
        active=[m for m in record['matches'] if m['state'] not in ('failed','lobby_returned')]
        replay_saved=False
        if len(active)==1 and lobby_loaded(state) and roster is not None and not record['unresolved_commands']:
            item=active[0]
            from modules.end_game_results import load_result
            replay_saved=load_result(self.journal.path,item['match_id']) is not None
            if (replay_saved and item['session_id']==self.host_session_id
                    and item['latest_match_observation'].get('native_game_start_time')==roster['gameStartTimeRaw']
                    and item['state'] in ('playing','completion_observed','exit_requested')):
                self.journal.transition(item['match_id'],item['state'],'results_available',item['latest_match_observation'])
                item['state']='results_available'
        if (len(active)==1 and active[0]['state']=='exit_requested' and gameplay_loaded(state)
                and not record['unresolved_commands'] and roster is not None
                and active[0]['session_id']==self.host_session_id
                and active[0]['latest_match_observation'].get('starting_roster',{}).get('steamLobbyId')==roster['steamLobbyId']
                and active[0]['latest_match_observation'].get('native_game_start_time')==roster['gameStartTimeRaw']):
            # A native precondition rejection proves Exit never ran. Recover the
            # saved completion without treating unknown/time-out commands as safe.
            with closing(self.journal.connect()) as db:
                rejected=db.execute("SELECT status,evidence_json FROM command_journal WHERE match_id=? AND action='exit-completed' ORDER BY updated_at DESC LIMIT 1",(active[0]['match_id'],)).fetchone()
            if rejected and rejected[0]=='failed' and json.loads(rejected[1]).get('mutationStarted') is False:
                self.journal.transition(active[0]['match_id'],'exit_requested','completion_observed',active[0]['latest_match_observation'])
                self.record('recovered_rejected_exit',match_id=active[0]['match_id'])
                record=self.journal.inspect(self.process_key)
                active=[m for m in record['matches'] if m['state'] not in ('failed','lobby_returned')]
        self.recovery=reconcile(record,self.process_key,self.host_session_id,
            {'process_key':self.process_key,'session_id':self.host_session_id,'loaded':gameplay_loaded(state),
             'lobby_loaded':lobby_loaded(state),'replay_saved':replay_saved,
             'results_visible':bool(active and lobby_loaded(state) and any(o['kind']=='mp_statistics' and o['flags']&6==6 for o in self.ui_objects())),
             'native_game_start_time':roster['gameStartTimeRaw'] if roster is not None else None})
        if len(active)==1:
            self.match_id=active[0]['match_id']
            self.active_match=active[0]['latest_match_observation']
        else:
            self.active_match=None
            self.match_id=None
        self.record('recovery_decision',**self.recovery)

    def state(self):
        if getattr(self, 'restart_poll', None):
            self.restart_poll()
        if self.monitor_background:
            self.observe_window()
        with bounded(5):
            state = self.script.exports_sync.state()
        self.record('state', state=state)
        self.last_engine_state = state
        from modules.live_game_data import record_controller
        record_controller(self,'observe_state',state)
        if self.monitor_background and time.monotonic() >= getattr(self, 'next_heartbeat', 0):
            self.next_heartbeat = time.monotonic() + 60
            print(f"[HOST] {datetime.now():%H:%M:%S} pid={self.pid} ticks={state.get('ticks')} page={state.get('pageName')}", flush=True)
        return state

    def command(self, action, **options):
        if getattr(self,'record_only',False) and action!='probe':
            raise RuntimeError('Record-only mode forbids native mutations')
        if self.monitor_background:
            self.observe_window()
        self.record('command', action=action, options=options)
        self.last_command = {'action': action, 'target': options.get('target'), 'time': time.time()}
        self.last_probe_step = None
        request_id = None
        if getattr(self,'journal',None) and action not in ('probe','gate'):
            if action in ('start','internet','setup','create') and getattr(self,'active_match',None):
                raise RuntimeError('Existing durable match must be reconciled before starting another')
            request_id = self.journal.request(self.process_key,self.match_id,action,options)
            self.journal.command_state(request_id,'executing')
        try:
            with bounded(20):
                result = self.script.exports_sync.command(action, options, 15000)
        except BaseException as error:
            if request_id:
                self.journal.command_state(request_id,'unknown',{'error':str(error)})
            raise
        if request_id and (not result.get('ok') or action not in ('assign-ai','set-bot-army','configure-ai','configure-friends','configure-capacity','spectate-host')):
            self.journal.command_state(request_id,'observed-complete' if result.get('ok') else (
                'failed' if result.get('mutationStarted') is False else 'unknown'),result)
        self.last_request_id = request_id
        self.record('command_result', action=action, result=result)
        if not result.get('ok'):
            error = RuntimeError(f'{action}: {result.get("error", result)}')
            error.command_result = result
            raise error
        return result

    def assign_ai(self, slot, difficulty, timeout):
        approved = self.command('probe',target='approval')['probe']
        result = self.command('assign-ai',slot=slot,difficulty=difficulty,approval=approved['approval'])
        request_id = self.last_request_id
        def assigned(observation):
            slots = [s for s in observation['slots'] if s['slotIdRaw'] == slot]
            return len(slots) == 1 and any(r['memberIdRaw'] == slots[0]['memberIdRaw'] and
                r['typeRaw'] == 2 and r['aiDifficultyRaw'] == difficulty for r in observation['rows'])
        try:
            after = wait_for(lambda:self.command('probe',target='roster')['probe'],assigned,min(timeout,15))
            self.journal.command_state(request_id,'observed-complete',after)
        except BaseException as error:
            self.journal.command_state(request_id,'unknown',{'error':str(error)})
            raise
        self.record('ai_assignment_verified',before=approved['roster'],after=after,slot=slot,difficulty=difficulty)
        (self.directory/'ai_assignment.json').write_text(json.dumps({'before':approved,'after':after},indent=2),encoding='utf-8')
        print(f'PASS AI {difficulty} assigned to native slot {slot}',flush=True)
        return after

    def set_bot_army(self, member_id, army, timeout):
        approved = self.command('probe',target='approval')['probe']
        self.command('set-bot-army',memberId=member_id,army=army,approval=approved['approval'])
        request_id = self.last_request_id
        def selected(roster):
            members=[r for r in roster['rows'] if r['memberIdRaw']==member_id and r['typeRaw']==2]
            return len(members)==1 and members[0]['armyRaw']==army
        try:
            after=wait_for(lambda:self.command('probe',target='roster')['probe'],selected,min(timeout,15))
            self.journal.command_state(request_id,'observed-complete',after)
        except BaseException as error:
            self.journal.command_state(request_id,'unknown',{'error':str(error)})
            raise
        self.record('bot_army_verified',member_id=member_id,army=army,before=approved['roster'],after=after)
        with (self.directory/'bot_armies.jsonl').open('a',encoding='utf-8') as output:
            output.write(json.dumps({'time':time.time(),'member_id':member_id,'army':army,'roster':after})+'\n')
        print(f'PASS AI member {member_id} faction verified: {army}',flush=True)
        return after

    def configure_ai(self, timeout, victory_points=75):
        if type(victory_points) is not int or victory_points not in (75, 200):
            raise ValueError('Unsupported AI victory points')
        approved = self.command('probe',target='approval')['probe']
        self.command('configure-ai',approval=approved['approval'],victoryPoints=victory_points,totalManpower=10000)
        request_id = self.last_request_id
        try:
            after = wait_for(lambda:self.command('probe',target='roster')['probe'],
                lambda r:r['settings']['victoryPoints']==victory_points and r['settings']['totalManpower']==10000,min(timeout,15))
            self.journal.command_state(request_id,'observed-complete',after)
        except BaseException as error:
            self.journal.command_state(request_id,'unknown',{'error':str(error)})
            raise
        (self.directory/'effective_profile.json').write_text(json.dumps({'before':approved,'after':after},indent=2),encoding='utf-8')
        print(f'PASS effective session settings: {victory_points} VP / 10000 Total Manpower',flush=True)
        return after

    def start_ai(self, timeout, stable_seconds, victory_points=75):
        if type(victory_points) is not int or victory_points not in (75, 200):
            raise ValueError('Unsupported AI victory points')
        self.host_lobby(timeout)
        if any(o['kind']=='mp_statistics' and o['flags']&6==6 for o in self.ui_objects()):
            raise RuntimeError('Preserve previous results before Start')
        self.command('ready')
        wait_for(lambda:self.command('probe',target='roster')['probe'],
                 lambda r:any(m['memberIdRaw']==r['localMemberIdRaw'] and m['readyRaw']==1 for m in r['rows']),10)
        approved=self.command('probe',target='approval')['probe']
        if not controlled_ai(approved['roster']):
            raise RuntimeError('Local host with bots on both teams or exactly three opposing Heroic bots required')
        if approved['roster']['settings']['victoryPoints'] != victory_points:
            raise RuntimeError('Requested AI victory points do not match the lobby')
        match={'match_id':str(uuid.uuid4()),'process_identity':self.identity,
               'host_session_id':self.host_session_id,'starting_roster':approved['roster'],
               'requested_settings':{'victoryPoints':victory_points,'totalManpower':10000},
               'effective_settings':approved['roster']['settings'],'created_at':time.time(),
               'mods':None,'mods_status':'not_yet_captured','engine_outcome':None}
        match['participants']=participants(approved['roster'],match['match_id'])
        self.match_id=self.journal.new_match(self.host_session_id,match,match['match_id'])
        self.journal.transition(self.match_id,'lobby','start_requested',approved)
        (self.directory/'match_observation.json').write_text(json.dumps(match,indent=2),encoding='utf-8')
        try:
            started=self.command('start',ai=True,approval=approved['approval'],victoryPoints=victory_points)
        except Exception:
            record=self.journal.inspect(self.process_key)
            if not record['unresolved_commands']:
                self.journal.transition(self.match_id,'start_requested','failed',{'reason':'native_precondition_rejected'})
            raise
        self.journal.transition(self.match_id,'start_requested','loading',started)
        state=self.checkpoint('AI loaded gameplay',gameplay_loaded,timeout,stable_seconds)
        current=self.command('probe',target='roster')['probe']
        match.update(native_game_start_time=current['gameStartTimeRaw'],loaded_at=time.time(),loaded_roster=current)
        if not match['native_game_start_time'] or match['native_game_start_time']==approved['roster']['gameStartTimeRaw']:
            raise RuntimeError('New native game generation was not observed')
        self.journal.transition(self.match_id,'loading','playing',match)
        self.active_match=match
        self.recovery={'status':'playing','match_id':self.match_id,'may_mutate':False}
        (self.directory/'match_observation.json').write_text(json.dumps(match,indent=2),encoding='utf-8')
        return state,match

    def watch(self, duration, interval):
        deadline=time.monotonic()+duration
        previous=None
        count=0
        last_report=0
        while time.monotonic()<deadline:
            started=time.monotonic()
            state=self.state()
            roster=self.command('probe',target='roster')['probe'] if valid_engine(state) else None
            sample={'observed_at':time.time(),'state':state,'roster':roster,
                    'match_id':self.match_id,
                    'read_duration_seconds':time.monotonic()-started,
                    'live_counters':None,'live_counters_status':'unavailable'}
            sample['live']=self.command('probe',target='live')['probe']
            if roster and gameplay_loaded(state) and not self.active_match:
                from modules.live_game_data import associate_loaded
                associate_loaded(self,roster,hosting_mode='observe')
            if self.active_match and roster:
                from modules.live_game_data import observe_controller
                observe_controller(self,roster,sample['live'])
            if sample['live']['managerStateRaw']==3 and self.active_match:
                capture=self.capture_completion(sample['live'],roster)
                print(f'PASS finish observed; waiting for replay for {self.match_id}',flush=True)
                return {'samples':count+1,'state':state,'completion':capture,'finish_captured':True}
            sample['read_duration_seconds']=time.monotonic()-started
            signature=(state.get('stageVtable'),state.get('pageVtable'),roster.get('gameStartTimeRaw') if roster else None)
            sample['lifecycle_changed']=previous is not None and previous!=signature
            previous=signature
            self.record('live_sample',**sample)
            count+=1
            if time.monotonic()-last_report>=30:
                print(f'WATCH sample={count} loaded={gameplay_loaded(state)} ticks={state["ticks"]} counters={[x["rawText"] for x in sample["live"]["hud"]]}',flush=True)
                last_report=time.monotonic()
            time.sleep(max(0,min(interval-(time.monotonic()-started),deadline-time.monotonic())))
        return {'samples':count,'duration':duration,'interval':interval,'state':state}

    def capture_completion(self, live=None, roster=None):
        if not self.active_match:
            raise RuntimeError('No durable active match to associate with completion')
        live=live or self.command('probe',target='live')['probe']
        roster=roster or self.command('probe',target='roster')['probe']
        match=self.active_match
        if live['managerStateRaw']!=3 or roster['gameStartTimeRaw']!=match['native_game_start_time'] or roster['steamLobbyId']!=match['starting_roster']['steamLobbyId']:
            raise RuntimeError('Terminal state or native match generation mismatch')
        raw=self.command('probe',target='controls',summaryOnly=True)['probe']
        raw.update(observed_at=time.time(),match_id=self.match_id,native_game_start_time=roster['gameStartTimeRaw'])
        (self.directory/'completion_raw.json').write_text(json.dumps(raw,indent=2),encoding='utf-8')
        # The overlay is lifecycle evidence for a safe native exit, never a
        # final-results source. Final counters and outcome come only from replay.
        if len([n for n in raw.get('nodes',[]) if n.get('name')=='mp_result' and n.get('vtable')==0xe2f8a4])!=1:
            raise ValueError('Completion exit overlay is not available yet')
        match.update(trigger='normal_completion_observed',engine_outcome=None,
                     completion_observed_at=raw['observed_at'],final_results_status='waiting_for_replay')
        record=next(m for m in self.journal.inspect(self.process_key)['matches'] if m['match_id']==self.match_id)
        if record['state']=='playing':
            self.journal.transition(self.match_id,'playing','completion_observed',match)
        self.record('completion_observed_waiting_for_replay',match_id=self.match_id)
        return {'source':'lifecycle_observation','final_results_status':'waiting_for_replay'}

    def abort_ai(self, timeout):
        match=self.active_match
        if not match or not match.get('native_game_start_time') or self.recovery['status']!='playing':
            raise RuntimeError('A reconciled controller-created AI match is required')
        original=match['starting_roster']
        if not controlled_ai(original):
            raise RuntimeError('Original scenario was not a controlled AI match')
        controlled={'epoch':match['native_game_start_time'],'card':original['card'],'lobby':original['steamLobbyId'],
            'identities':sorted([[r['memberIdRaw'],r['typeRaw'],r['identityWordsRaw'],
                [[s['slotIdRaw'],s['teamRaw']] for s in original['slots'] if s['memberIdRaw']==r['memberIdRaw']],
                r['aiDifficultyRaw']] for r in original['rows']])}
        match.update(trigger='controlled_ai_test_abort',engine_outcome=None,abort_requested_at=time.time())
        self.journal.transition(self.match_id,'playing','exit_requested',match)
        if gameplay_loaded(self.state()):
            self.command('menu',controlled=controlled)
        state=self.checkpoint('controlled AI game menu',lambda s:s.get('pageVtable')==0xe216cc,timeout,1)
        roster=self.command('probe',target='roster')['probe']
        match['pre_quit_roster']=roster
        (self.directory/'match_observation.json').write_text(json.dumps(match,indent=2),encoding='utf-8')
        self.command('request-quit',controlled=controlled)
        dialogs=[o for o in self.ui_objects() if o['kind']=='POPUP' and any(
            r[0]==7 and r[1]==0x118 and r[3]==int(state['page'],16) for r in o.get('bindings',[]))]
        if len(dialogs)!=1:
            raise RuntimeError('Expected one controlled AI Close confirmation')
        self.command('confirm-quit',controlled=controlled,dialog=dialogs[0]['address'],menu=state['page'],
                     card=roster['card'],identity=':'.join(str(w) for w in roster['rows'][0]['identityWordsRaw']))
        state=self.checkpoint('controlled AI exit',lambda s:valid_engine(s) and s.get('stageVtable')!=GAME,timeout,3)
        raw={}
        self.journal.transition(self.match_id,'exit_requested','results_available',match)
        print('PASS controlled AI abort preserved raw statistics; normal finish is not claimed',flush=True)
        return state,match,raw

    def finish_ai(self, timeout):
        self.capture_completion()
        match=self.active_match
        original=match['starting_roster']
        controlled={'epoch':match['native_game_start_time'],'card':original['card'],'lobby':original['steamLobbyId'],
            'identities':sorted([[r['memberIdRaw'],r['typeRaw'],r['identityWordsRaw'],
                [[s['slotIdRaw'],s['teamRaw']] for s in original['slots'] if s['memberIdRaw']==r['memberIdRaw']],
                r['aiDifficultyRaw']] for r in original['rows']])}
        raw=json.loads((self.directory/'completion_raw.json').read_text())
        root=next(n for n in raw['nodes'] if n['name']=='mp_result')
        signature=completion_signature(raw['nodes'],root['address'])
        self.journal.transition(self.match_id,'completion_observed','exit_requested',match)
        self.command('exit-completed',controlled=controlled,address=root['address'],signature=signature,
                     friendsCompleted=match.get('hosting_mode')=='friends')
        state=self.checkpoint('normal completion returned to lobby',lobby_loaded,timeout,3)
        match['pre_quit_roster']=self.command('probe',target='roster')['probe']
        (self.directory/'match_observation.json').write_text(json.dumps(match,indent=2),encoding='utf-8')
        raw={}
        self.journal.transition(self.match_id,'exit_requested','results_available',match)
        return state,match,raw

    def archived_ai_results(self):
        state = self.state()
        if not lobby_loaded(state):
            raise RuntimeError('Archived results recovery requires the native lobby')
        roster = self.command('probe', target='roster')['probe']
        original = self.active_match['starting_roster']
        if roster['steamLobbyId'] != original['steamLobbyId'] or roster['card'] != original['card']:
            raise RuntimeError('Archived results lobby identity changed')
        return self.journal.archived_completion_results(self.process_key, self.host_session_id, self.match_id,
            dict(process_key=self.process_key, session_id=self.host_session_id,
                 native_game_start_time=roster['gameStartTimeRaw'], lobby_loaded=True, loaded=False,
                 results_visible=any(o['kind']=='mp_statistics' and o['flags']&6==6 for o in self.ui_objects()),
                 session=state['session'], card=state['card']))

    def save_ai_results(self, timeout):
        if not self.active_match or self.recovery['status'] not in ('results_available', 'needs_reconciliation'):
            raise RuntimeError('Reconciled match required before replay save/cleanup')
        from modules.end_game_results import wait_for_match
        match=self.active_match
        normalized=wait_for_match(self.journal.path,match,timeout)
        match.update(final_results_source=normalized['source'],engine_outcome=normalized['engine_outcome'],
                     replay=normalized['replay'])
        (self.directory/'normalized_results.json').write_text(json.dumps(normalized,indent=2),encoding='utf-8')
        record=next(m for m in self.journal.inspect(self.process_key)['matches'] if m['match_id']==self.match_id)
        if record['state']!='results_saved':
            self.journal.transition(self.match_id,record['state'],'results_saved',match)
        objects=[o for o in self.ui_objects() if o['kind']=='mp_statistics' and o['flags']&6==6]
        if len(objects)>1: raise RuntimeError('Ambiguous statistics dialog during cleanup')
        if objects:
            self.command('dismiss-results',address=objects[0]['address'],epoch=match['native_game_start_time'],
                         lobby=match['starting_roster']['steamLobbyId'])
        self.journal.transition(self.match_id,'results_saved','lobby_returned',match)
        return self.checkpoint('Replay results saved and lobby usable',lobby_loaded,timeout,3),match

    def ai_cycle(self, timeout, stable_seconds, completion_timeout):
        self.start_ai(timeout,stable_seconds)
        report=self.watch(completion_timeout,1)
        if not report.get('finish_captured'):
            raise TimeoutError('AI normal completion budget exceeded; observations preserved, match left running')
        self.finish_ai(timeout)
        self.bind_session()
        return self.save_ai_results(timeout)

    def create_widget(self):
        pm = pymem.Pymem(self.pid)
        try:
            page = pm.read_uint(0xfeaac0)
            # Scan on the controller thread, never stall the game loop with a heap scan.
            hits = scan_with_partial_copy_retry(pm.process_handle,
                re.escape(struct.pack('<I',0xe2bea8)))
            candidates = []
            for address in hits:
                try:
                    if address > 0x1000000 and pm.read_uint(address+0x9c) == page:
                        candidates.append(address)
                except pymem.exception.MemoryReadError:
                    continue
            if len(candidates) != 1:
                raise RuntimeError(f'Expected exactly one Create widget owned by page; found {candidates}')
            self.record('create_widget', address=hex(candidates[0]), owner=hex(page))
            return hex(candidates[0])
        finally:
            pm.close_process()

    def ui_objects(self, kinds=None):
        """Bounded-size results for named menu/statistics objects; no UI activation."""
        pm = pymem.Pymem(self.pid)
        found = []
        try:
            for kind, vtable in [('game_menu', 0xe216cc), ('mp_statistics', 0xe1f69c), ('POPUP', 0xd9f9f4)]:
                if kinds is not None and kind not in kinds:
                    continue
                hits = scan_with_partial_copy_retry(pm.process_handle,
                    re.escape(struct.pack('<I',vtable)))
                for address in hits:
                    if address < 0x1000000:
                        continue
                    try:
                        size, capacity = pm.read_uint(address+0x3c), pm.read_uint(address+0x40)
                        if size != len(kind) or size > capacity:
                            continue
                        at = pm.read_uint(address+0x2c) if capacity > 15 else address+0x2c
                        if pm.read_bytes(at,size).decode('utf-8') == kind:
                            entry = {'kind':kind,'address':hex(address),'vtable':hex(vtable),
                                     'flags':pm.read_uint(address+0x20)}
                            if kind == 'POPUP':
                                begin, end = pm.read_uint(address+0x84), pm.read_uint(address+0x88)
                                if 0 <= end-begin <= 128*20 and (end-begin) % 20 == 0:
                                    entry['bindings'] = [list(struct.unpack('<5I', pm.read_bytes(at,20)))
                                                         for at in range(begin,end,20)]
                            found.append(entry)
                    except (pymem.exception.MemoryReadError, UnicodeError):
                        continue
            self.record('ui_objects', objects=found)
            return found
        finally:
            pm.close_process()

    def checkpoint(self, name, predicate, timeout, stable=1):
        state = wait_for(self.state, predicate, timeout, stable_seconds=stable)
        self.record('checkpoint_pass', name=name, state=state)
        if state.get('map'):
            self.selected_map = state['map']
        print(f'PASS {name}', flush=True)
        return state

    def host_lobby(self, timeout):
        state = self.state()
        # The unpacking/global-pointer check can finish before the UI exists.
        # Wait for a live page before deciding which hosting transition is legal.
        if (state.get('core') == '0x0' and state.get('stageVtable') == 0
                and state.get('pageVtable') == 0):
            print('Waiting for game startup / main menu...', flush=True)
            state = self.checkpoint('startup page with live updates',
                lambda s: s.get('pageVtable') == MAIN_MENU or (
                    valid_engine(s) and bool(s.get('stageVtable'))
                    and bool(s.get('pageVtable'))), timeout)
        if state['core'] == '0x0' and state['pageVtable'] == MAIN_MENU:
            self.command('internet')
            state = self.checkpoint('online engine initialized', lambda s: valid_engine(s) and s['stageVtable'] == INTERNET, timeout)
        browser=(state['stageVtable']==0xe2fd94 and state['pageVtable']==0xe2a3d0 and state.get('pageName')=='mp_lobbyinet')
        if state['stageVtable'] == INTERNET or browser:
            self.command('setup')
            state = self.checkpoint('Host Game setup', lambda s: valid_engine(s) and s['stageVtable'] == SETUP and s['pageVtable'] == 0xe2a540, timeout)
        if state['stageVtable'] == SETUP:
            self.command('create', widget=self.create_widget())
            state = self.checkpoint('multiplayer lobby with session card and map',
                lobby_loaded, timeout, stable=3)
        if not lobby_loaded(state):
            raise RuntimeError(f'Cannot host to lobby from this engine state: {state}')
        return self.checkpoint('stopped in multiplayer lobby', lobby_loaded, timeout, stable=3)

    def run(self, timeout, stable_seconds):
        state = self.state()
        if state['stageVtable'] not in (GAME, 0xe2ff84):
            state = self.host_lobby(timeout)
        if state['stageVtable'] == LOBBY:
            self.command('ready')
            wait_for(lambda: self.command('gate'), lambda s: s.get('startAllowed') is True, 10)
            print('PASS engine Ready/Start gate', flush=True)
            self.record('checkpoint_pass', name='engine Ready/Start gate')
            self.command('start')
        elif state['stageVtable'] not in (GAME, 0xe2ff84):
            raise RuntimeError(f'Cannot resume from this engine state: {state}')
        state = self.checkpoint('loaded multiplayer gameplay with live updates', gameplay_loaded, timeout, stable=stable_seconds)
        self.observe_loaded_match('run')
        return state

    def observe_loaded_match(self, mode):
        """Use the shared observer for modes that attach after native Start."""
        from modules.live_game_data import associate_loaded, observe_controller
        roster = self.command('probe',target='roster')['probe']
        if not self.active_match:
            associate_loaded(self,roster,hosting_mode=mode)
        if self.active_match:
            observe_controller(self,roster,self.command('probe',target='live')['probe'])
        return self.active_match

    def quit_solo(self, timeout, stable_seconds, match=None):
        state = self.state()
        if gameplay_loaded(state):
            self.observe_loaded_match('solo')
            self.checkpoint('loaded gameplay before solo quit', gameplay_loaded, timeout, stable_seconds)
            self.command('menu')
        elif state.get('stageVtable') != GAME or state.get('pageVtable') != 0xe216cc:
            raise RuntimeError('Solo quit requires gameplay or its active game menu')
        self.checkpoint('active game menu with live updates',
                        lambda s: valid_engine(s) and s.get('stageVtable') == GAME
                        and s.get('pageVtable') == 0xe216cc, timeout, stable_seconds)
        roster = self.command('probe',target='roster')['probe']
        match = self.observe_loaded_match('solo')
        if match is None:
            raise RuntimeError('No active native match to associate with solo results')
        match.update(trigger='host_requested_quit',engine_outcome=None,
                     pre_quit_roster=roster,observed_at=time.time())
        (self.directory/'match_observation.json').write_text(json.dumps(match,indent=2),encoding='utf-8')
        menu = self.state()['page']
        def confirmations():
            return [obj for obj in self.ui_objects() if obj['kind'] == 'POPUP'
                    and any(row[0] == 7 and row[1] == 0x118 and row[3] == int(menu,16)
                            for row in obj.get('bindings', []))]
        dialogs = confirmations()
        if not dialogs:
            self.command('request-quit')
            dialogs = confirmations()
        if len(dialogs) != 1:
            raise RuntimeError('Expected exactly one native Close confirmation; inspect before retrying')
        self.record('quit_confirmation_observed', dialog=dialogs[0])
        self.command('confirm-quit',dialog=dialogs[0]['address'],menu=menu,card=roster['card'],
                     identity=':'.join(str(word) for word in roster['rows'][0]['identityWordsRaw']))
        state = self.checkpoint('native quit transition with surviving game loop',
                               lambda s: valid_engine(s) and s.get('stageVtable') != GAME,
                               timeout, stable=3)
        match['post_quit_state'] = state
        match['ui_objects'] = self.ui_objects()
        (self.directory/'match_observation.json').write_text(json.dumps(match,indent=2),encoding='utf-8')
        from modules.end_game_results import wait_for_match
        normalized=wait_for_match(self.journal.path,match,timeout)
        match.update(final_results_source=normalized['source'],engine_outcome=normalized['engine_outcome'],replay=normalized['replay'])
        current=next(m for m in self.journal.inspect(self.process_key)['matches'] if m['match_id']==self.match_id)
        if current['state']!='results_saved':
            self.journal.transition(self.match_id,current['state'],'results_saved',match)
        (self.directory/'normalized_results.json').write_text(json.dumps(normalized,indent=2),encoding='utf-8')
        self.record('results_saved',match_id=match['match_id'])
        return state, match

    def dismiss_saved_results(self, match):
        from modules.end_game_results import wait_for_match
        wait_for_match(ROOT/'data/rankbot.sqlite3',match,timeout=0)
        objects=[o for o in self.ui_objects() if o['kind']=='mp_statistics' and o['flags']&6==6]
        if len(objects)!=1: raise RuntimeError('Expected one saved-results dialog')
        self.command('dismiss-results',address=objects[0]['address'])
        current=next((m for m in self.journal.inspect(self.process_key)['matches'] if m['match_id']==match['match_id']),None)
        if current and current['state']=='results_saved':
            self.journal.transition(match['match_id'],'results_saved','lobby_returned',match)
        self.record('results_dismissed',match_id=match['match_id'])

    def solo_cycle(self, timeout, stable_seconds):
        self.host_lobby(timeout)
        if any(obj['kind'] == 'mp_statistics' and obj['flags'] & 6 == 6 for obj in self.ui_objects()):
            raise RuntimeError('Preserve and dismiss the previous statistics before a new solo cycle')
        match = {'match_id':str(uuid.uuid4()),'created_at':time.time(),'starting_roster':None}
        self.command('ready')
        wait_for(lambda:self.command('gate'), lambda s:s.get('startAllowed') is True,10)
        # Save the ID before Start; never replay a timed-out Start.
        (self.directory/'match_observation.json').write_text(json.dumps(match,indent=2),encoding='utf-8')
        started = self.command('start',solo=True)
        match.update(starting_roster=started['startingRoster'],started_at=time.time())
        (self.directory/'match_observation.json').write_text(json.dumps(match,indent=2),encoding='utf-8')
        self.checkpoint('solo loaded gameplay',gameplay_loaded,timeout,stable_seconds)
        match = self.observe_loaded_match('solo')
        state, match = self.quit_solo(timeout,stable_seconds,match)
        self.dismiss_saved_results(match)
        self.checkpoint('solo cycle returned to lobby',lobby_loaded,timeout,stable=3)
        return state,match

    def capture_results(self, objects=None):
        if objects is None:
            objects = self.ui_objects(kinds=('mp_statistics',))
        objects = [obj for obj in objects if obj['kind'] == 'mp_statistics' and obj['flags'] & 6 == 6]
        if len(objects) != 1:
            raise RuntimeError('Expected exactly one visible statistics object')
        result = self.command('probe',target='statistics',address=objects[0]['address']) if self.record_only else self.command('results',address=objects[0]['address'])
        raw = dict(result['probe'], observed_at=time.time(), state=result['state'])
        (self.directory/'raw_statistics.json').write_text(json.dumps(raw,indent=2),encoding='utf-8')
        return raw

    def disconnect(self):
        """Release one process attachment while keeping this run's log open."""
        if self.session:
            try:
                with bounded(5):
                    self.session.detach()
            except Exception as error:
                self.record('detach_error', error=str(error))
        self.session = self.script = None
        if self.process_lock:
            self.process_lock.close()
            self.process_lock = None
        if getattr(self, 'diagnostics', None):
            self.diagnostics.close()
            self.diagnostics = None

    def close(self):
        from modules.live_game_data import record_controller
        record_controller(self,'event','observer_stopped',dict(description='Controller is closing; game exit is not implied'))
        self.disconnect()
        with self.lock:
            self.log.close()


def configure_console_output():
    """Keep player text from stopping the host on legacy Windows output pipes."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='backslashreplace')


def main():
    configure_console_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run','lobby','probe','menu','quit','results','export','dismiss-results','solo','status','check','assign-ai','ai-joinability','configure-ai','start-ai','watch','abort-ai','recover','finish-ai','save-ai-results','ai-cycle','friends-prepare','friends-host','friends-status','friends-hold','friends-resume','friends-stop','review','matches','lobby-history'])
    parser.add_argument('--no-open',action='store_true',help='Generate review HTML without opening a browser')
    parser.add_argument('--serve',action='store_true',help='With review: serve the page on localhost with manual winner recording until Ctrl+C')
    parser.add_argument('--min-players',type=int,default=2,help='Automatic hosting: exact playing-slot capacity and required humans (even 2..32); spectators excluded')
    parser.add_argument('--ready-seconds',type=float,default=5,help='Unchanged all-ready countdown before auto-start')
    parser.add_argument('--held',action='store_true',help='Start friends controller with automatic starts held')
    parser.add_argument('--ai-test',action='store_true',help='Local spectator validation: require AI-only playing roster instead of humans')
    parser.add_argument('--run-seconds',type=float,help='Bound friends controller runtime; default runs until stop/Ctrl+C')
    parser.add_argument('--json',action='store_true',help='Machine-readable friends overview')
    parser.add_argument('--follow',action='store_true',help='Refresh friends-status until Ctrl+C')
    parser.add_argument('--record-only',action='store_true',help='With friends-host: observe manual games and save results; no game/window mutations')
    parser.add_argument('--snapshot-seconds',type=float,default=30,help='Seconds between durable progress snapshots (default 30); lifecycle events save immediately')
    parser.add_argument('--game-master',action='store_true',help='Reply to lobby chat using the existing Codex ChatGPT login')
    parser.add_argument('--gm-model',default='gpt-6-astra',help='Codex model name')
    parser.add_argument('--gm-reasoning',choices=['minimal','low','medium','high','xhigh'],default='low')
    parser.add_argument('--gm-mode',choices=['addressed','ambient'],default='ambient',help='Consider all new player chat; the prompt decides whether to reply. Addressed is a legacy alias for ambient.')
    parser.add_argument('--gm-cooldown',type=float,default=20,help='Minimum seconds between generation requests')
    parser.add_argument('--gm-timeout',type=float,default=45,help='Maximum seconds allowed per model request')
    parser.add_argument('--gm-context',type=int,default=12,help='Recent chat messages supplied to Codex')
    parser.add_argument('--gm-max-chars',type=int,default=120,help='Maximum chat reply length, up to 128')
    parser.add_argument('--gm-quiet',action='store_true',help='Hide game-master flow from CLI; evidence logs remain')
    parser.add_argument('--gm-dry-run',action='store_true',help='Generate and log replies without sending them')
    parser.add_argument('--rating-profile',choices=['robz-battle-zones'],help='Declare the loaded mod is Robz for this run; unknown mods remain unrated')
    parser.add_argument('--army-selection',choices=['players','teams','alliances'],help='Automatic host army selection; default: Teams with both team armies, otherwise Alliances')
    parser.add_argument('--team-a-army',choices=['ger','rus','usa','eng','jap','axis_minor','ger_ss','rus_guard'],help='Host Teams mode: nation for Team A; requires --team-b-army')
    parser.add_argument('--team-b-army',choices=['ger','rus','usa','eng','jap','axis_minor','ger_ss','rus_guard'],help='Host Teams mode: nation for Team B; requires --team-a-army')
    parser.add_argument('--lobby-name',help='Override the advertised lobby name; Steam profile name stays unchanged')
    parser.add_argument('--lobby-color',help='Six-digit RGB color for --lobby-name, e.g. ff0000')
    parser.add_argument('--expected-map',help='Refuse automatic starts if the remembered lobby map differs from this native map ID')
    parser.add_argument('--completion-timeout',type=float,default=900)
    parser.add_argument('--duration',type=float,default=60)
    parser.add_argument('--interval',type=float,default=1)
    parser.add_argument('--slot',type=int,help='Native slot ID, as observed by the roster probe')
    parser.add_argument('--joinability', choices=['open','closed'], default='closed', help='AI test lobby admission; ai-joinability only')
    parser.add_argument('--ai-victory-points', type=int, choices=[75,200], default=75,
                        help='Exact VP profile for configure-ai/start-ai; 200 allows longer tactical trials')
    parser.add_argument('--difficulty',choices=['easy','normal','hard','heroic'],default='normal')
    parser.add_argument('--pid', type=int)
    parser.add_argument('--minimize', action='store_true', help='Minimize the game without moving the cursor or foregrounding it')
    parser.add_argument('--strict-background', action='store_true',
                        help='Report interrupted background validation with exit 2 after completing the operation; never quits the match')
    parser.add_argument('--target', choices=['lobby', 'services', 'roster', 'ui', 'statistics', 'controls','settings','live','social'], default='lobby', help='Read-only probe target')
    parser.add_argument('--match-observation', type=Path, help='Explicit saved match observation for offline export')
    parser.add_argument('--raw-statistics', type=Path, help='Explicit saved native statistics for offline export')
    parser.add_argument('--database', type=Path, default=ROOT/'data/rankbot.sqlite3', help='Offline export database')
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--evidence-root', type=Path, default=ROOT / 'validation',
                        help='Directory for new run evidence; defaults to the project validation directory')
    parser.add_argument('--loading-timeout', type=float, default=600,
                        help='Seconds to await the gameplay page and new match generation in automatic hosting')
    parser.add_argument('--stable-seconds', type=float, default=15)
    args = parser.parse_args()
    if args.serve and args.action!='review':parser.error('--serve requires review')
    if not math.isfinite(args.snapshot_seconds) or args.snapshot_seconds<=0:
        parser.error('--snapshot-seconds must be positive and finite')
    if args.game_master and (args.action!='friends-host' or args.record_only or args.ai_test):
        parser.error('--game-master requires automatic human friends-host')
    if args.gm_dry_run and not args.game_master:
        parser.error('--gm-dry-run requires --game-master')
    if not (5<=args.gm_cooldown<=3600 and 5<=args.gm_timeout<=120 and 1<=args.gm_context<=30 and 20<=args.gm_max_chars<=128):
        parser.error('Require gm-cooldown 5..3600, gm-timeout 5..120, gm-context 1..30, gm-max-chars 20..128')
    if (args.team_a_army or args.team_b_army) and (not (args.team_a_army and args.team_b_army) or args.action not in ('friends-host','friends-prepare') or args.record_only):
        parser.error('Team nation options require both armies and automatic friends-host or friends-prepare')
    if args.army_selection and (args.action not in ('friends-host','friends-prepare') or args.record_only):
        parser.error('--army-selection requires automatic friends-host or friends-prepare')
    if args.army_selection and ((args.army_selection=='teams') != bool(args.team_a_army)):
        parser.error('--army-selection teams requires both team armies; players/alliances cannot use team armies')
    if args.record_only and (args.action!='friends-host' or args.minimize or args.ai_test):
        parser.error('--record-only requires friends-host and cannot combine with --minimize or --ai-test')
    if not 2<=args.min_players<=32 or args.min_players%2 or not 1<=args.ready_seconds<=60 or (args.run_seconds is not None and args.run_seconds<=0):
        parser.error('Require even min-players 2..32, ready-seconds 1..60, run-seconds > 0')
    if args.action=='lobby-history':
        from lobby_social import read_history
        history=read_history(args.database)
        if args.json:
            print(json.dumps(history,indent=2))
        else:
            print(f"{len(history['players'])} observed players")
            for p in history['players']:
                rating=p.get('rating')
                skill='unrated' if rating is None else f"{round(rating['value'])}"+(' (provisional)' if rating['provisional'] else '')
                print(f"{p['display_name']} | {p['steam_id']} | games: {p['games_played']} | badge: {p['badge_tier']} | ranked games: {p['ranked_games_played']} | Robz skill: {skill}")
            print('Recent lobby chat (newest first):')
            for m in history['chat']:
                print(f"{m['sender_name'] or 'System'}: {m['text']}")
        return 0
    if args.action in ('review','matches'):
        from match_review import load_matches,write_review,print_matches
        import webbrowser
        try:
            records=load_matches(args.database)
            if args.action=='matches':
                print(json.dumps(records,indent=2) if args.json else print_matches(records))
            else:
                if args.serve:
                    from match_review_service import serve
                    serve(args.database,ROOT/'data/match_review.html',open_browser=not args.no_open)
                    return 0
                path=write_review(records,ROOT/'data/match_review.html',args.database)
                print(f'{len(records)} saved matches. Review: {path}',flush=True)
                if not args.no_open:
                    webbrowser.open(path.as_uri())
            return 0
        except (OSError,ValueError) as error:
            print(str(error),file=sys.stderr)
            return 1
    if args.action in ('friends-status','friends-hold','friends-resume','friends-stop'):
        from friends_host import Control,overview
        control=Control(ROOT/'data/friends_control.sqlite3')
        try:
            while True:
                status=control.status() if args.action=='friends-status' else control.request({'friends-hold':'hold','friends-resume':'run','friends-stop':'stop'}[args.action])
                if args.follow and sys.stdout.isatty() and not args.json:
                    print('\x1b[2J\x1b[H',end='')
                print(json.dumps(status,indent=2) if args.json else overview(status),flush=True)
                if not args.follow or args.action!='friends-status':
                    break
                time.sleep(2)
            return 0
        except KeyboardInterrupt:
            return 0
        except RuntimeError as error:
            print(str(error),file=sys.stderr)
            return 1
    if not 0.25<=args.interval<=60 or not 0<args.duration<=3600:
        parser.error('Require interval 0.25..60 seconds and duration 0..3600 seconds')
    if args.action == 'assign-ai' and args.slot is None:
        parser.error('assign-ai requires --slot')
    if args.loading_timeout <= 0:
        parser.error('--loading-timeout must be positive')
    if args.timeout <= 0 or args.stable_seconds <= 0 or args.timeout <= args.stable_seconds:
        parser.error('Require timeout > stable-seconds > 0')
    if args.action == 'export' and (not args.match_observation or not args.raw_statistics):
        parser.error('export requires --match-observation and --raw-statistics')
    if args.action == 'dismiss-results' and not args.match_observation:
        parser.error('dismiss-results requires --match-observation; current results are saved before dismissal')
    if args.lobby_name is not None or args.lobby_color is not None:
        import re
        if args.action!='friends-host' or args.record_only:
            parser.error('Lobby name options require automatic friends-host')
        if not args.lobby_name or not args.lobby_name.strip() or len(args.lobby_name)>64 or re.search(r'[<>\x00-\x1f\x7f]',args.lobby_name):
            parser.error('Lobby name requires 1..64 characters without markup or control characters')
        if args.lobby_color is not None and not re.fullmatch(r'[0-9a-fA-F]{6}',args.lobby_color):
            parser.error('Lobby color requires six hexadecimal digits')
    if args.game_master:
        from game_master import check_login
        try:
            check_login()
        except (RuntimeError,OSError,subprocess.TimeoutExpired) as error:
            print(f'Game master startup failed: {error}',file=sys.stderr)
            return 1
    directory = args.evidence_root / datetime.now().strftime('run_%Y%m%d_%H%M%S_%f')
    controller = None
    summary = {'action':args.action,'success':False}
    directory.mkdir(parents=True)
    with ExitStack() as power:
        try:
            if args.action in ('run', 'lobby', 'solo', 'friends-prepare', 'friends-host', 'start-ai', 'ai-cycle', 'watch', 'check'):
                power.enter_context(prevent_idle_sleep())
            if args.action == 'export':
                raise ValueError('UI exports are no longer final results. Use py -m modules.end_game_results to import completed replays.')
            pid = ensure_process(args.action,args.pid,args.timeout)
            summary['pid'] = pid
            if args.action in ('run', 'lobby', 'solo','friends-prepare','friends-host'):
                wait_boot(pid,args.timeout)
            controller = HostController(pid,directory)
            controller.record_only=args.record_only
            controller.snapshot_seconds=args.snapshot_seconds
            controller.rating_profile=args.rating_profile
            controller.game_master_settings=None
            if args.game_master:
                from game_master import Settings
                controller.game_master_settings=Settings(args.gm_model,args.gm_reasoning,args.gm_mode,args.gm_cooldown,args.gm_timeout,args.gm_context,args.gm_max_chars,args.gm_dry_run,not args.gm_quiet)
                controller.record('game_master_config',**vars(controller.game_master_settings))
            controller.expected_map=args.expected_map
            controller.expected_army_selection=args.army_selection
            controller.expected_team_armies={'a':args.team_a_army,'b':args.team_b_army} if args.team_a_army else {}
            controller.browser_listing={'lobbyName':args.lobby_name,'lobbyColor':args.lobby_color}
            controller.attach()
            controller.record('window_before', **window_state(pid,minimize=args.minimize))
            if args.minimize:
                # ShowWindowAsync only queues the request. Observe its completion
                # before issuing engine commands; never treat its return as proof.
                try:
                    wait_for(lambda: window_state(pid), background_window, 5)
                except TimeoutError:
                    controller.record('minimize_not_observed', cause='unknown')
            controller.monitor_background = True
            controller.observe_window()
            if args.action in ('friends-prepare','friends-host'):
                from friends_host import Control,prepare,run as run_friends
                if args.action=='friends-prepare':
                    summary['roster']=prepare(controller,args.timeout,args.min_players)
                else:
                    if args.record_only:
                        from match_recorder import run as run_recorder
                        summary['friends']=run_recorder(controller,Control(ROOT/'data/friends_control.sqlite3'),duration=args.run_seconds)
                    else:
                        summary['friends']=run_friends(controller,Control(ROOT/'data/friends_control.sqlite3'),
                            minimum=args.min_players,ready_seconds=args.ready_seconds,timeout=args.timeout,loading_timeout=args.loading_timeout,
                            held=args.held,ai_test=args.ai_test,duration=args.run_seconds,restart=not args.ai_test)
                state=controller.state() if controller.script is not None else None
            elif args.action == 'run':
                state = controller.run(args.timeout,args.stable_seconds)
            elif args.action == 'lobby':
                state = controller.host_lobby(args.timeout)
            elif args.action == 'assign-ai':
                summary['roster'] = controller.assign_ai(args.slot,args.difficulty,args.timeout)
                state = controller.state()
            elif args.action == 'configure-ai':
                summary['roster'] = controller.configure_ai(args.timeout,args.ai_victory_points)
                state = controller.state()
            elif args.action == 'start-ai':
                state,summary['match']=controller.start_ai(args.timeout,args.stable_seconds,args.ai_victory_points)
            elif args.action == 'ai-cycle':
                state,summary['match']=controller.ai_cycle(args.timeout,args.stable_seconds,args.completion_timeout)
            elif args.action == 'abort-ai':
                state,summary['match'],summary['raw_statistics']=controller.abort_ai(args.timeout)
            elif args.action == 'finish-ai':
                state,summary['match'],summary['raw_statistics']=controller.finish_ai(args.timeout)
            elif args.action == 'save-ai-results':
                state,summary['match']=controller.save_ai_results(args.timeout)
            elif args.action == 'watch':
                summary['watch']=controller.watch(args.duration,args.interval)
                state=summary['watch']['state']
            elif args.action == 'recover':
                summary['recovery']=controller.recovery
                state=controller.state()
                print(json.dumps(controller.recovery,indent=2),flush=True)
            elif args.action == 'check':
                state = controller.checkpoint('loaded multiplayer gameplay with live updates',gameplay_loaded,args.timeout,args.stable_seconds)
            elif args.action == 'ai-joinability':
                summary['joinability'] = controller.command('ai-joinability', joinability=args.joinability)
                print(f'PASS Steam accepted lobby joining {args.joinability}', flush=True)
                state = controller.state()
            elif args.action == 'menu':
                controller.checkpoint('loaded gameplay before solo menu',gameplay_loaded,args.timeout,args.stable_seconds)
                result = controller.command('menu')
                summary['roster'] = result['roster']
                summary['ui_objects'] = controller.ui_objects()
                state = controller.state()
            elif args.action == 'quit':
                state, summary['match'] = controller.quit_solo(args.timeout,args.stable_seconds)
            elif args.action == 'solo':
                state, summary['match'] = controller.solo_cycle(args.timeout,args.stable_seconds)
            elif args.action == 'dismiss-results':
                match = json.loads(args.match_observation.read_text(encoding='utf-8'))
                controller.dismiss_saved_results(match)
                state = controller.checkpoint('lobby after statistics dismissal',lobby_loaded,args.timeout,3)
            elif args.action == 'results':
                summary['probe'] = controller.capture_results()
                state = summary['probe']['state']
            elif args.action == 'probe':
                if args.target == 'ui':
                    summary['probe'] = controller.ui_objects()
                    state = controller.state()
                else:
                    options = {}
                    if args.target == 'statistics':
                        objects = [obj for obj in controller.ui_objects() if obj['kind'] == 'mp_statistics']
                        if len(objects) != 1:
                            raise RuntimeError('Expected exactly one statistics object')
                        options['address'] = objects[0]['address']
                    result = controller.command('probe', target=args.target, **options)
                    summary['probe'] = result['probe']
                    state = result['state']
                print(json.dumps(summary['probe'],indent=2))
            else:
                state = controller.state()
                print(json.dumps(state,indent=2))
            summary.update(success=True,pid=controller.pid,state=state,selected_map=controller.selected_map,window=window_state(controller.pid))
            controller.observe_window()
            summary['background_violations'] = controller.background_violations
            summary['background'] = background_result(controller.background_violations, args.strict_background)
            if summary['background']['status'] == 'interrupted':
                print('INFO window observed outside minimized background state; operation completed. Background validation interrupted (cause unknown).', flush=True)
            else:
                print('PASS sampled game window remained minimized and out of focus', flush=True)
            controller.record('success', summary=summary)
        except Exception as error:
            summary.update(success=False,error=str(error))
            if controller:
                summary['pid'] = controller.pid
                summary['background_violations'] = controller.background_violations
                summary['diagnostics'] = controller.failure_diagnostics()
                controller.record('failure',error=str(error),traceback=traceback.format_exc())
                diagnostic = summary['diagnostics']
                print('[HOST] Failure diagnostics: '+json.dumps({k: diagnostic[k] for k in
                    ('process','detachment','last_command','last_probe_step')}), file=sys.stderr, flush=True)
            print(f'FAIL {error}', file=sys.stderr, flush=True)
        finally:
            if controller:
                controller.close()
            (directory/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
            if GAME_LOG.exists():
                lines = GAME_LOG.read_text(encoding='utf-8',errors='replace').splitlines()
                (directory/'game_log_tail.txt').write_text('\n'.join(lines[-120:]),encoding='utf-8')
            print(f'Evidence: {directory}',flush=True)
    return summary.get('background', {}).get('exit_code', 0) if summary['success'] else 1


if __name__ == '__main__':
    sys.exit(main())
