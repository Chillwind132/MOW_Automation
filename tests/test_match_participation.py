import _test_paths  # Shared paths for direct runs and test discovery.
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from modules.live_game_data import Participation,history,native_reason,observe_controller


def fixture():
    roster={'steamLobbyId':'lobby','gameStartTimeRaw':'epoch',
            'rows':[{'typeRaw':1,'memberIdRaw':1,'identityWordsRaw':[101,17825793]},
                    {'typeRaw':1,'memberIdRaw':2,'identityWordsRaw':[102,17825793]},
                    {'typeRaw':4,'memberIdRaw':3,'identityWordsRaw':[103,17825793]}],
            'slots':[{'memberIdRaw':1,'teamRaw':'a'},{'memberIdRaw':2,'teamRaw':'b'}]}
    people=[dict(steam_id=str((17825793<<32)|101+i),native_member_id=1+i,
                 role='participant' if i<2 else 'spectator',controller_kind='remote_human',
                 starting_team='a' if i==0 else 'b') for i in range(3)]
    return dict(match_id='match',native_game_start_time='epoch',starting_roster=copy.deepcopy(roster),participants=people),roster


class ParticipationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'test.sqlite3'
        self.monitor=Participation(self.path)
        self.match,self.roster=fixture()
        self.live={'managerStateRaw':2}

    def poll(self,now,roster=None,live=None):
        return self.monitor.observe(self.match,self.roster if roster is None else roster,self.live if live is None else live,now)

    def test_departure_return_are_durable_once_with_unknown_intent(self):
        self.poll(0)
        lost=copy.deepcopy(self.roster);lost['rows'].pop(0)
        events=self.poll(1,lost)
        self.assertEqual([e['kind'] for e in events],['roster_missing'])
        self.assertEqual(events[0]['steam_id'],self.match['participants'][0]['steam_id'])
        self.assertEqual(self.poll(2,lost),[])
        self.assertEqual([e['kind'] for e in self.poll(3)],['roster_restored'])
        self.assertEqual(len(history(self.path,'match')),3)
        self.assertTrue(all(not e['evidence']['penalty_applied'] for e in history(self.path)))

    def test_finished_roster_removal_never_becomes_early_departure(self):
        self.poll(0)
        r=copy.deepcopy(self.roster);r['rows']=[]
        self.assertEqual([e['kind'] for e in self.poll(1,r,{'managerStateRaw':3})],['finish_observed'])
        self.assertEqual(self.poll(2,r),[])

    def test_first_observation_does_not_invent_departure(self):
        self.roster['rows'].pop(0)
        kinds=[e['kind'] for e in self.poll(0)]
        self.assertIn('state_observed_without_continuous_coverage',kinds)
        self.assertNotIn('roster_missing',kinds)

    def test_restart_and_poll_gap_are_explicit(self):
        self.poll(0)
        self.monitor=Participation(self.path)
        self.roster['rows'].pop(0)
        kinds=[e['kind'] for e in self.poll(1)]
        self.assertIn('observation_gap',kinds)
        self.assertNotIn('roster_missing',kinds)
        self.assertEqual([e['kind'] for e in self.poll(12)],['observation_gap'])

    def test_unknown_probe_and_other_generation_never_count_as_missing(self):
        self.poll(0)
        self.assertEqual(self.poll(1,live={'managerStateRaw':None}),[])
        self.roster['gameStartTimeRaw']='other'
        self.assertEqual(self.poll(2),[])
        self.roster['gameStartTimeRaw']='epoch';self.roster['steamLobbyId']='other'
        self.assertEqual(self.poll(3),[])

    def test_spectators_excluded_team_switch_recorded(self):
        self.poll(0);self.roster['rows'].pop()
        self.assertEqual(self.poll(1),[])
        self.roster['slots'][0]['teamRaw']='b'
        self.assertEqual([e['kind'] for e in self.poll(2)],['role_or_team_changed'])

    def test_same_steam_new_member_binding_is_not_new_player(self):
        self.poll(0)
        self.roster['rows'][0]['memberIdRaw']=8;self.roster['slots'][0]['memberIdRaw']=8
        self.assertEqual([e['kind'] for e in self.poll(1)],['member_binding_changed'])

    def test_multiple_departures_preserve_shared_outage_evidence(self):
        self.poll(0);self.roster['rows']=[]
        events=self.poll(1)
        self.assertEqual(len(events),2)
        self.assertTrue(all(e['evidence']['absent_players']==2 and e['evidence']['intent']=='unknown' for e in events))

    def test_native_flags_are_facts_not_intent(self):
        for flags,reason in ((1,'entered'),(2,'left'),(4,'disconnected'),(8,'kicked'),(16,'banned'),(6,'left+disconnected'),(32,'unknown_flags')):
            self.assertEqual(native_reason(flags),reason)
            event=self.monitor.native(dict(lobby_id='lobby',steam_id='123',flags=flags,page_vtable=0xe2ae58,manager_state=2),self.match)
            self.assertEqual(event['match_id'],'match')
            self.assertEqual(event['evidence']['intent'],'unknown')
            self.assertFalse(event['evidence']['penalty_applied'])

    def test_native_outside_match_and_finished_events_stay_unassociated(self):
        p=dict(lobby_id='lobby',steam_id='123',flags=2,page_vtable=0xe2ae58,manager_state=3)
        self.assertIsNone(self.monitor.native(p,self.match)['match_id'])
        p.update(manager_state=2,lobby_id='other')
        self.assertIsNone(self.monitor.native(p,self.match)['match_id'])

    def test_read_only_history_and_integration(self):
        missing=self.path.parent/'missing.sqlite3'
        self.assertEqual(history(missing),[]);self.assertFalse(missing.exists())
        c=Mock(journal=Mock(path=self.path),active_match=self.match)
        observe_controller(c,self.roster,self.live)
        before=self.path.read_bytes()
        self.assertEqual(len(history(self.path)),1)
        self.assertEqual(before,self.path.read_bytes())

    def test_controller_message_captures_raw_native_evidence(self):
        from headless_host import HostController
        c=HostController.__new__(HostController);c.record=Mock();c.participation=self.monitor;c.active_match=self.match
        c.instrumentation_message({'type':'send','payload':dict(event='native_lobby_membership',lobby_id='lobby',steam_id='123',flags=4,page_vtable=0xe2ae58,manager_state=2)},None)
        self.assertEqual(history(self.path)[0]['evidence']['reason'],'disconnected')


if __name__=='__main__':unittest.main()
