import _test_paths
import copy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock,patch
from friends_host import readiness
from early_start import EarlyStart,early_voters
from test_friends_host import roster


def lobby():
    r=roster();r.update(steamLobbyId='lobby',gameStartTimeRaw='epoch',map='map')
    r['settings']['maxPlayers']=4
    r['slots'] += [{'memberIdRaw':0,'teamRaw':t,'slotIdRaw':i} for i,t in [(2,'a'),(5,'b')]]
    for i,m in enumerate(r['rows']):m['displayName']=str(i)
    return r


class EarlyTests(unittest.TestCase):
    def setUp(self):
        self.r=lobby();self.e=EarlyStart();self.messages=[];self.now=0
        self.c=Mock(record_only=False);self.c.game_master_can_send=lambda:True
        self.social=Mock(c=self.c,last_send=-100)
        self.obs={'lobby_id':'lobby','messages':self.messages,'players':[
            {'display_name':m['displayName'],'native_member_id':m['memberIdRaw'],
             'steam_id':str((m['identityWordsRaw'][1]<<32)|m['identityWordsRaw'][0])} for m in self.r['rows']]}

    def tick(self,enabled=True,gate=True):
        self.now+=6;self.social.latest={'roster':copy.deepcopy(self.r),'input_busy':False}
        with patch('early_start.normalize_social',return_value=self.obs),patch('early_start.time.monotonic',return_value=self.now):
            return self.e.tick(self.social,{'roster':self.r,'approval':'token'},enabled,
                               readiness(self.r,4,early=True)['ready'],gate)

    def vote(self,name,key):
        self.messages.append({'message_key':key,'kind':'player','sender_name':name,'text':' /START '})

    def test_unanimous_new_votes_only(self):
        self.vote('1','old');self.assertFalse(self.tick())
        self.vote('1','new');self.assertFalse(self.tick())
        self.vote('1','duplicate');self.vote('0','spectator');self.assertFalse(self.tick())
        self.assertEqual(len(self.e.votes),1)
        self.vote('2','last');self.assertTrue(self.tick())
        self.assertEqual(self.e.votes,set(early_voters(self.r)))

    def test_successful_start_does_not_cancel_on_return_to_lobby(self):
        self.tick();self.vote('1','one');self.vote('2','two')
        self.assertTrue(self.tick())
        self.e.reset(notify=False)  # Start accepted; then active-match observation.
        self.e.reset(notify=False)
        self.c.command.reset_mock()
        self.r['gameStartTimeRaw']='finished-match'
        self.r['rows'][1]['readyRaw']=0;self.r['rows'][2]['readyRaw']=0
        self.assertFalse(self.tick());self.c.command.assert_not_called()
        self.assertFalse(self.e.votes);self.assertFalse(self.e.cancelled)
        self.r['rows'][1]['readyRaw']=1;self.r['rows'][2]['readyRaw']=1
        self.tick()
        self.assertTrue(self.c.command.call_args.kwargs['text'].startswith('All players ready'))
        self.assertNotIn('Votes reset',self.c.command.call_args.kwargs['text'])

    def test_real_lobby_cancellation_still_announced(self):
        self.tick();self.vote('1','one');self.tick()
        self.r['rows'][2]['readyRaw']=0
        self.tick()
        self.assertIn('Early start cancelled',self.c.command.call_args.kwargs['text'])
        count=self.c.command.call_count;self.tick()
        self.assertEqual(self.c.command.call_count,count)

    def test_unready_cancels_and_old_votes_do_not_return(self):
        self.tick();self.vote('1','one');self.tick()
        self.r['rows'][2]['readyRaw']=0;self.tick();self.assertFalse(self.e.votes)
        self.r['rows'][2]['readyRaw']=1;self.tick()
        self.vote('2','two');self.assertFalse(self.tick());self.assertEqual(len(self.e.votes),1)

    def test_hold_settings_and_team_changes_reset(self):
        for change in ('hold','settings','team','epoch'):
            with self.subTest(change=change):
                self.setUp();self.tick();self.vote('1','one');self.tick()
                if change=='settings':self.r['settings']['test']=1
                if change=='team':self.r['slots'][0]['teamRaw']='b'
                if change=='epoch':self.r['gameStartTimeRaw']='next'
                self.tick(enabled=change!='hold');self.assertFalse(self.e.votes)

    def test_closed_engine_gate_waits_without_spam(self):
        self.tick();self.vote('1','one');self.vote('2','two')
        self.assertFalse(self.tick(gate=False));n=self.c.command.call_count
        self.assertFalse(self.tick(gate=False));self.assertEqual(self.c.command.call_count,n)
        self.assertTrue(self.tick())

    def test_ambiguous_name_cannot_vote(self):
        self.obs['players'][2]['display_name']='1'
        self.tick();self.vote('1','one');self.tick();self.assertFalse(self.e.votes)

    def test_read_only_never_sends(self):
        self.c.record_only=True;self.tick();self.c.command.assert_not_called()

    def test_partial_and_uneven_require_opponents(self):
        self.assertFalse(readiness(self.r,4)['ready'])
        self.assertTrue(readiness(self.r,4,early=True)['ready'])
        extra=copy.deepcopy(self.r['rows'][1]);extra.update(memberIdRaw=4,identityWordsRaw=[104,17825793])
        self.r['rows'].append(extra);self.r['slots'][2]['memberIdRaw']=4
        self.assertTrue(readiness(self.r,4,early=True)['ready'])
        self.r['rows'].pop(2);self.r['slots'][1]['memberIdRaw']=0
        self.assertFalse(readiness(self.r,4,early=True)['ready'])

    def test_departure_clears_existing_consents(self):
        self.tick();self.vote('1','one');self.tick()
        self.r['rows'].pop();self.r['slots'][1]['memberIdRaw']=0
        self.assertFalse(self.tick());self.assertFalse(self.e.votes)

    def test_busy_input_defers_offer_and_ignores_premature_votes(self):
        self.social.latest={'roster':self.r,'input_busy':True}
        with patch('early_start.normalize_social',return_value=self.obs):
            self.e.tick(self.social,{'roster':self.r,'approval':'token'},True,True,True)
        self.c.command.assert_not_called()
        self.vote('1','too-soon');self.tick();self.assertFalse(self.e.votes)

    def test_send_failure_cannot_start(self):
        self.tick();self.vote('1','one');self.vote('2','two')
        self.c.command.side_effect=RuntimeError('stale approval')
        self.assertFalse(self.tick());self.assertFalse(self.e.votes)

    def test_native_early_guard(self):
        source=Path('headless/headless_host.js').read_text()
        fn=source[source.index('function friendsReady('):source.index('function settingsProbe(')]
        cases=[]
        r=lobby();cases.append([r,early_voters(r),True]);cases.append([r,early_voters(r)[:1],False])
        uneven=copy.deepcopy(r);extra=copy.deepcopy(r['rows'][1]);extra.update(memberIdRaw=4,identityWordsRaw=[104,17825793]);uneven['rows'].append(extra);uneven['slots'][2]['memberIdRaw']=4
        cases.append([uneven,early_voters(uneven),True])
        r=copy.deepcopy(r);r['rows'][1]['readyRaw']=0;cases.append([r,early_voters(r),False])
        r=lobby();r['slots'][1]['teamRaw']='a';cases.append([r,early_voters(r),False])
        js=fn+'\nconst cases='+json.dumps(cases)+'; for(const [r,v,want] of cases) {if(friendsReady(r,4,false,null,v)!==want)throw Error("bad early guard");}'
        subprocess.run(['node','-e',js],check=True,capture_output=True)
