"""A failed runner must not restart the game after Hold or Stop."""
import _test_paths  # Shared paths for direct runs and test discovery.
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import stress_supervisor


class SupervisorControlTests(unittest.TestCase):
    def test_control_change_preserves_game_even_with_a_new_fatal_log(self):
        for desired in ['hold','stop']:
            with self.subTest(desired=desired),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);(root/'validation').mkdir();log=root/'game.log';log.write_text('startup')
                game=Mock(pid=111);runner=Mock()
                def finish():
                    log.write_text('***************** Exception *****************\nFailed to allocate memory.\nememory.cpp, 94')
                    return 1
                runner.wait.side_effect=finish
                control=Mock();control.status.return_value={'desired':desired,'error':'allocation failure'}
                with patch.object(stress_supervisor,'ROOT',root),patch.object(stress_supervisor,'GAME_LOG',log),\
                     patch.object(stress_supervisor,'find_process',return_value=None),\
                     patch.object(stress_supervisor,'find_game_executable',return_value=root/'mowas_2.exe'),\
                     patch.object(stress_supervisor,'process_identity',return_value={'pid':111}),\
                     patch.object(stress_supervisor,'Control',return_value=control),\
                     patch.object(stress_supervisor.subprocess,'Popen',side_effect=[game,runner]) as launch,\
                     patch.object(stress_supervisor,'terminate_failed_game') as terminate,\
                     patch.object(stress_supervisor.sys,'argv',['stress_supervisor.py','--cycles','2']):
                    stress_supervisor.main()
                self.assertEqual(launch.call_count,2)
                terminate.assert_not_called();game.terminate.assert_not_called()
                self.assertEqual(len(list((root/'validation').glob('campaign_*/game_1.log'))),1)


if __name__=='__main__':unittest.main()
