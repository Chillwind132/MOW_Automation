"""Saved-result, process identity and restart failure boundaries."""
import _test_paths
import ctypes
from ctypes import wintypes
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from host_restart import launch_game, restart_after_match, stop_saved_game


class RestartTests(unittest.TestCase):
    def test_launch_is_direct_minimized_and_disables_reload_cache(self):
        with patch('host_restart.subprocess.Popen') as launch:
            launch_game(Path('game/mowas_2.exe'), minimize=True)
        args, options = launch.call_args
        self.assertEqual(args[0], [str(Path('game/mowas_2.exe')), '-no_reload_caching'])
        self.assertEqual(options['startupinfo'].wShowWindow, 7)
        self.assertTrue(options['startupinfo'].dwFlags & 1)

    def test_identity_mismatch_and_exit_timeout_never_succeed(self):
        for creation, wait in ((2, 0), (1, 0x102), (1, 0)):
            kernel = Mock()
            kernel.OpenProcess.return_value = 42
            def times(handle, created, *rest):
                ctypes.cast(created, ctypes.POINTER(wintypes.FILETIME)).contents.dwLowDateTime = creation
                return 1
            kernel.GetProcessTimes.side_effect = times
            kernel.WaitForSingleObject.return_value = wait
            with patch('host_restart.ctypes.WinDLL', return_value=kernel):
                if creation != 1 or wait:
                    with self.assertRaises((RuntimeError, TimeoutError)):
                        stop_saved_game({'pid':123,'creation_filetime':'1'})
                else:
                    stop_saved_game({'pid':123,'creation_filetime':'1'})
            if creation != 1:
                kernel.TerminateProcess.assert_not_called()
            else:
                kernel.TerminateProcess.assert_called_once_with(42, 0)
            kernel.CloseHandle.assert_called_once_with(42)

    def test_restart_guards_and_order_preserve_policy_and_evidence(self):
        for variation in ('ok','record_only','active','pending_command','unsaved','missing_replay','gameplay','stop_failure','launch_failure','stop'):
            with self.subTest(variation=variation), tempfile.TemporaryDirectory() as tmp:
                exe=Path(tmp)/'mowas_2.exe';exe.touch()
                record={'matches':[{'match_id':'m','state':'lobby_returned',
                    'latest_match_observation':{'hosting_mode':'friends'}}], 'unresolved_commands':[]}
                c=Mock(record_only=False,active_match=None,identity={'pid':1,'executable_path':str(exe)},
                       expected_army_selection='players',expected_map='map',directory=Path(tmp))
                c.journal.inspect.return_value=record
                if variation=='record_only':c.record_only=True
                if variation=='active':c.active_match={'match_id':'new'}
                if variation=='pending_command':record['unresolved_commands']=[{}]
                if variation=='unsaved':record['matches'][0]['state']='results_available'
                order=Mock()
                poll=Mock(side_effect=KeyboardInterrupt if variation=='stop' else None)
                with patch('modules.end_game_results.load_result',return_value=None if variation=='missing_replay' else {'source':'persisted_replay_battleInfoTotal'}), \
                     patch('headless_host.lobby_loaded',return_value=variation!='gameplay'), \
                     patch('host_restart.stop_saved_game') as stop, \
                     patch('host_restart.launch_game',return_value=Mock(pid=2)) as launch, \
                     patch('headless_host.wait_boot') as boot, \
                     patch('headless_host.window_state'),patch('headless_host.wait_for'):
                    order.attach_mock(stop,'stop');order.attach_mock(c.disconnect,'disconnect')
                    order.attach_mock(launch,'launch');order.attach_mock(boot,'boot');order.attach_mock(c.attach,'attach')
                    if variation=='stop_failure':stop.side_effect=TimeoutError('exit')
                    if variation=='launch_failure':launch.side_effect=OSError('launch')
                    if variation=='ok':
                        restart_after_match(c,'m',10,poll)
                        self.assertEqual([call[0] for call in order.mock_calls],['stop','disconnect','launch','boot','attach'])
                        self.assertEqual(c.pid,2)
                        self.assertEqual(c.expected_army_selection,'players')
                        self.assertEqual(c.expected_map,'map')
                        self.assertEqual(c.directory,Path(tmp))
                        self.assertIsNone(c.restart_poll)
                    else:
                        with self.assertRaises((RuntimeError,OSError,KeyboardInterrupt)):
                            restart_after_match(c,'m',10,poll)
                        c.attach.assert_not_called()
                        if variation not in ('stop_failure','launch_failure'):stop.assert_not_called()
                        if variation!='launch_failure':launch.assert_not_called()


if __name__=='__main__':
    unittest.main()
