"""Host Teams mode uses team settings, including when member armies are empty."""
import _test_paths  # Shared paths for direct runs and test discovery.
import copy
import json
from pathlib import Path
import subprocess
import struct
import sys
import unittest
from friends_host import readiness, team_settings_ready, army_selection_mode
from match_metadata import participants
from test_friends_host import roster


class TeamNationTests(unittest.TestCase):
    def test_modes_match_executable_enum_table(self):
        # Independent evidence, rather than a roster fixture repeating our enum.
        binary=Path('C:/Program Files (x86)/Steam/steamapps/common/Men of War Assault Squad 2/mowas_2.exe')
        if not binary.exists():binary=_test_paths.ROOT/'diagnostics/reference/mowas_2_dumped.exe'
        if not binary.exists():self.skipTest('AS2 executable unavailable')
        data=binary.read_bytes()
        pe=struct.unpack_from('<I',data,0x3c)[0]
        count=struct.unpack_from('<H',data,pe+6)[0]
        optional_size=struct.unpack_from('<H',data,pe+20)[0]
        base=struct.unpack_from('<I',data,pe+52)[0]
        sections=[struct.unpack_from('<IIII',data,pe+24+optional_size+i*40+8) for i in range(count)]
        def read(address,size):
            for virtual_size,rva,raw_size,offset in sections:
                if rva<=address-base<rva+max(virtual_size,raw_size):
                    start=offset+address-base-rva
                    return data[start:start+size]
            self.fail('Enum address outside executable sections')
        modes={}
        for i in range(5):
            pointer,value=struct.unpack('<II',read(0xe27b18+i*8,8))
            if not pointer:break
            modes[read(pointer,32).split(b'\0')[0].decode('ascii')]=value
        self.assertEqual(modes,{'player':2,'team':1,'alliance':3,'default':4})
        self.assertEqual(army_selection_mode({},'players'),modes['player'])
        self.assertEqual(army_selection_mode({},'alliances'),modes['alliance'])
        self.assertEqual(army_selection_mode({'a':'ger','b':'rus'},'teams'),modes['team'])

    def test_native_configuration_rejects_incorrect_enum_before_setter(self):
        source=(_test_paths.ROOT/'headless/headless_host.js').read_text()
        start=source.index('        const mode=options.armySelection')
        guard=source[start:source.index('        // Native mode setter:',start)]
        script='''
        let table=[];
        function va(address){
            if(address!==0xe27b18)throw Error('Unexpected enum address');
            const entry=offset=>({
                add:n=>entry(offset+n),
                readU32:()=>table[Math.floor(offset/8)]?.[1],
                readPointer:()=>({isNull:()=>!table[Math.floor(offset/8)],
                    readUtf8String:()=>table[Math.floor(offset/8)][0]})
            });
            return entry(0);
        }
        function configure(options){
        '''+guard+'''
            return mode;
        }
        table=[['alliance',3],['team',1],['player',2],['default',4]];
        if(configure({armySelection:'players'})!==2)throw Error('Wrong Players enum');
        for(const invalid of [[['player',0]],[['wrong-label',2]],[]]){
            table=invalid;let rejected=false;
            try{configure({armySelection:'players'});}catch(e){rejected=true;}
            if(!rejected)throw Error('Invalid enum reached setter');
        }
        '''
        subprocess.run(['node'],input=script,text=True,capture_output=True,check=True)

    def test_native_and_python_reject_changed_team_settings(self):
        armies={'a':'ger_ss','b':'rus'}
        r=roster()
        r['settings'].update(armySelectionMode=1,teamArmies=armies.copy())
        for row in r['rows']:row['armyRaw']=''
        cases=[(r,True)]
        for mode,team in [(3,'rus'),(1,'usa'),(1,'random'),(1,'')]:
            changed=copy.deepcopy(r)
            changed['settings']['armySelectionMode']=mode
            changed['settings']['teamArmies']['b']=team
            cases.append((changed,False))
        missing=copy.deepcopy(r);del missing['settings']['teamArmies']
        cases.append((missing,False))
        for case,want in cases:
            self.assertEqual(readiness(case,team_armies=armies)['ready'],want)
            self.assertEqual(team_settings_ready(case,armies),want)
        self.assertFalse(readiness(r)['ready'])
        records=participants(r,'test')
        self.assertEqual([x['army'] for x in records if x['role']=='participant'],['ger_ss','rus'])
        source=(_test_paths.ROOT/'headless/headless_host.js').read_text()
        source=source[source.index('function friendsReady('):source.index('function settingsProbe(')]
        script=source+'\nconst cases='+json.dumps(cases)+';const armies='+json.dumps(armies)+''';
        for(const [r,want] of cases){
            if(friendsReady(r,2,false,armies)!==want)throw Error('Team policy mismatch');
        }
        if(friendsReady(cases[0][0],2))throw Error('Unexpected Teams mode without explicit configuration');
        '''
        subprocess.run(['node'],input=script,text=True,capture_output=True,check=True)

    def test_players_mode_python_and_native_guards(self):
        r=roster()
        r['settings']['armySelectionMode']=2
        r['rows'][1]['armyRaw']='ger_ss'
        r['rows'][2]['armyRaw']='rus_guard'
        cases=[(r,True)]
        for mode in (0,1,3):
            changed=copy.deepcopy(r);changed['settings']['armySelectionMode']=mode
            cases.append((changed,False))
        for field,value in [('armyRaw',''),('readyRaw',0)]:
            changed=copy.deepcopy(r);changed['rows'][1][field]=value
            cases.append((changed,False))
        self.assertTrue(team_settings_ready(r,{},'players'))
        self.assertFalse(readiness(r)['ready'])
        for case,want in cases:
            self.assertEqual(readiness(case,army_selection='players')['ready'],want)
            self.assertEqual(readiness(case,army_selection='players',early=True)['ready'],want)
        source=(_test_paths.ROOT/'headless/headless_host.js').read_text()
        source=source[source.index('function friendsReady('):source.index('function settingsProbe(')]
        script=source+'\nconst cases='+json.dumps(cases)+""";
        for(const [r,want] of cases){
            if(friendsReady(r,2,false,null,null,'players')!==want)throw Error('Players policy mismatch');
            const ids=r.rows.filter(x=>x.typeRaw!==4).map(x=>String((BigInt(x.identityWordsRaw[1])<<32n)|BigInt(x.identityWordsRaw[0])));
            if(friendsReady(r,2,false,null,ids,'players')!==want)throw Error('Players early policy mismatch');
        }
        if(friendsReady(cases[0][0],2))throw Error('Players mode needs explicit selection');
        if(friendsReady(cases[0][0],2,false,null,null,'invalid'))throw Error('Unknown selection accepted');
        """
        subprocess.run(['node'],input=script,text=True,capture_output=True,check=True)

    def test_invalid_players_cli_fails_before_attach(self):
        for args in [ ['friends-host','--army-selection','players','--team-a-army','ger','--team-b-army','rus'],
                      ['friends-host','--army-selection','teams'],
                      ['friends-host','--record-only','--army-selection','players'],
                      ['probe','--army-selection','players'] ]:
            result=subprocess.run([sys.executable,str(_test_paths.ROOT/'headless_host.py'),*args],capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertIn('--army-selection',result.stderr)

    def test_incomplete_or_record_only_cli_configuration_fails_before_attach(self):
        root=_test_paths.ROOT
        for args in [ ['friends-host','--team-a-army','ger_ss'],
                      ['probe','--team-a-army','ger_ss','--team-b-army','rus'],
                      ['friends-host','--record-only','--team-a-army','ger_ss','--team-b-army','rus'] ]:
            result=subprocess.run([sys.executable,str(root/'headless_host.py'),*args],capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertIn('Team nation options require',result.stderr)


if __name__=='__main__':unittest.main()
