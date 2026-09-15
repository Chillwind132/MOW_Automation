"""Planned process replacement after durable replay save; never crash recovery."""
import ctypes
from ctypes import wintypes
import subprocess
from pathlib import Path


def launch_game(executable, minimize=False):
    options = {}
    if minimize:
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 7  # SW_SHOWMINNOACTIVE
        options['startupinfo'] = startup
    executable = Path(executable)
    return subprocess.Popen([str(executable), '-no_reload_caching'],
                            cwd=str(executable.parent), **options)


def stop_saved_game(identity):
    """Terminate only the verified, saved game's handle, then wait for its exit."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x101001, False, identity['pid'])
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        creation = str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        if creation != identity['creation_filetime']:
            raise RuntimeError('Process identity changed; refusing restart')
        if not kernel.TerminateProcess(handle, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        if kernel.WaitForSingleObject(handle, 10000) != 0:
            raise TimeoutError('Old game did not exit; replacement was not launched')
    finally:
        kernel.CloseHandle(handle)


def restart_after_match(c, match_id, timeout, poll):
    from headless_host import lobby_loaded, wait_boot, window_state, background_window, wait_for
    from modules.end_game_results import load_result

    record = c.journal.inspect(c.process_key)
    saved = next((m for m in record['matches'] if m['match_id'] == match_id), None)
    if (c.record_only or c.active_match or record['unresolved_commands'] or not saved
            or saved['state'] != 'lobby_returned'
            or saved['latest_match_observation'].get('hosting_mode') != 'friends'
            or not load_result(c.journal.path, match_id) or not lobby_loaded(c.state())):
        raise RuntimeError('Restart requires a saved friends replay and an idle lobby')
    executable = Path(c.identity['executable_path'])
    if not executable.is_file():
        raise RuntimeError('Game executable missing; existing lobby preserved')
    poll()
    old_identity = dict(c.identity)
    c.record('planned_restart', match_id=match_id, old_process=old_identity)
    print('[HOST] Replay saved; restarting MOW minimized. Players must rejoin the new lobby.', flush=True)
    # Stop first, retaining the old process lock until Windows confirms exit.
    stop_saved_game(old_identity)
    c.disconnect()
    c.active_match = c.match_id = None
    c.detachment = c.last_command = c.last_probe_step = c.last_engine_state = None
    c.selected_map = None
    c.next_heartbeat = 0
    poll()
    process = launch_game(executable, minimize=True)
    c.pid = process.pid
    c.record('replacement_launched', match_id=match_id, pid=c.pid)
    c.restart_poll = poll
    try:
        wait_boot(c.pid, timeout, poll=poll)
        window_state(c.pid, minimize=True)
        c.attach()
        window_state(c.pid, minimize=True)
        wait_for(lambda: window_state(c.pid, minimize=True), background_window, 5)
    finally:
        c.restart_poll = None
