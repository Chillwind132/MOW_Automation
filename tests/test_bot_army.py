"""Faction requests must target only validated bot lobbies and clean temporaries."""
import _test_paths  # Shared paths for direct runs and test discovery.
from pathlib import Path
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from friends_host import start_match, restore_bot_armies


class BotArmyTests(unittest.TestCase):
    def test_reload_restores_only_changed_bots_and_refreshes_approval(self):
        approval={'roster':{'rows':[
            {'typeRaw':2,'teamRaw':'a','armyRaw':'random','memberIdRaw':3},
            {'typeRaw':2,'teamRaw':'b','armyRaw':'rus','memberIdRaw':6},
            {'typeRaw':4,'teamRaw':'spectator','armyRaw':''}]}}
        refreshed={'approval':'new token'}
        controller=SimpleNamespace(expected_bot_armies={'a':'ger','b':'rus'},
            set_bot_army=Mock(),command=Mock(return_value={'probe':refreshed}))
        self.assertIs(restore_bot_armies(controller,approval,True,15),refreshed)
        controller.set_bot_army.assert_called_once_with(3,'ger',15)
        controller.command.assert_called_once_with('probe',target='approval')
        controller.set_bot_army.reset_mock();controller.command.reset_mock()
        with self.assertRaisesRegex(RuntimeError,'all-bot'):
            restore_bot_armies(controller,approval,'mixed',15)
        controller.set_bot_army.assert_not_called()
        controller.command.assert_not_called()

    def test_reverted_faction_blocks_next_start_before_journaling(self):
        controller=SimpleNamespace(expected_map=None,expected_bot_armies={'a':'ger'},
                                   journal=Mock(),command=Mock())
        approval={'roster':{'rows':[{'typeRaw':2,'teamRaw':'a','armyRaw':'random'}]}}
        with patch('friends_host.readiness',return_value={'ready':True}):
            with self.assertRaisesRegex(RuntimeError,'faction differs'):
                start_match(controller,approval,6,True,15)
        controller.command.assert_not_called()
        controller.journal.new_match.assert_not_called()

    def test_native_guards_and_temporary_lifetime(self):
        source=(_test_paths.ROOT/'headless/headless_host.js').read_text()
        start=source.index("} else if (action === 'set-bot-army') {")
        body=source[start:source.index("} else if (action === 'cleanup-resources')",start)]
        body=body[body.index('{')+1:]
        script=r'''
for(const scenario of ['valid','already','stage','stale','remote','world','service','member','army','signature','request_failure']) {
 const calls=[];let allocations=0;
 const options={approval:'ok',memberId:2,army:scenario==='army'?'unknown':'ger'};
 const signatures={0xb5e280:'558bec83ec2456578bf98d4d',0x643b20:'558bec538bd95657c6432400',0x643ba0:'8b4140568d712883f810720c'};
 const ptr=n=>({n,equals:p=>n===p.n});
 function lobbyPage(){if(scenario==='stage')throw Error('stage');return {add:()=>({readPointer:()=>ptr(scenario==='service'?8:7)})};}
 function lobbyProbe(){return {service:7,hostMemberIdRaw:scenario==='remote'?9:1,localMemberIdRaw:1,
  rows:[{memberIdRaw:1,typeRaw:4},{memberIdRaw:2,typeRaw:scenario==='member'?1:2,teamRaw:'a',armyRaw:scenario==='already'?'ger':'random'}]};}
 const rosterApproval=()=>scenario==='stale'?'stale':'ok';
 function va(n){return {readByteArray:()=>Buffer.from(scenario==='signature'?'000000000000000000000000':signatures[n],'hex')};}
 const read=()=>({isNull:()=>scenario!=='world'});
 const Memory={alloc:n=>{allocations++;return {writeUtf8String:()=>{},add:()=>({writeU32:()=>{}})};}};
 function call(address,type,args){return (...values)=>{
  calls.push(address);
  if(address===0xb5e280){
   if(type!=='void'||args.join(',')!=='pointer,uint,pointer'||values[0].n!==7||values[1]!==2)throw Error('bad request signature');
   if(scenario==='request_failure')throw Error('native request failed');
  }
 };}
 let error=false,result;try{result=(function(){BODY})();}catch(_){error=true;}
 if(['valid','request_failure'].includes(scenario)){
  if(calls.join(',')!==[0x643b20,0xb5e280,0x643ba0].join(',')||allocations!==2)throw Error('temporary lifetime '+scenario);
  if(error!==(scenario==='request_failure'))throw Error('unexpected request result');
 }else if(scenario==='already'){
  if(error||calls.length||allocations||!result.alreadySelected)throw Error('already selected');
 }else if(!error||calls.length||allocations)throw Error('unsafe native call '+scenario);
}
'''.replace('BODY',body)
        subprocess.run(['node'],input=script,text=True,capture_output=True,check=True)


if __name__=='__main__':
    unittest.main()
