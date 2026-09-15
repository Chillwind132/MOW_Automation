"""Verify lobby naming leaves native player-count publication unchanged."""
import _test_paths  # Shared paths for direct runs and test discovery.
import json
from pathlib import Path
import subprocess
import unittest


class BrowserCountTests(unittest.TestCase):
    def test_publication_hook_only_changes_owned_lobby(self):
        source=(_test_paths.ROOT/'headless/headless_host.js').read_text(encoding='utf-8')
        hook=source[source.index('const hook=Interceptor.attach(setter,'):source.index('browserMetadata={mm,get,set,hook,hostName}')]
        script=r'''
const assert=require('node:assert/strict');
let callbacks,readOnly=false;
const setter={},Interceptor={attach(address,value){callbacks=value;return {};}};
const Memory={allocUtf8String(text){return {text};}};
const browserMetadata={hostName:'<c(ff0000)>\u2605 ROBZ 2v2 \u2605'};
const browserContext=()=>({roster:{steamLobbyId:String((1n<<32n)|23n)}});
const send=()=>{throw Error('Unexpected hook error');};
function args(low,key){return [{toUInt32:()=>low},{toUInt32:()=>1},{readUtf8String:()=>key},{text:'original'}];}
''' + hook + r'''
let a=args(23,'hostname');callbacks.onEnter.call({},a);assert.equal(a[3].text,browserMetadata.hostName);
a=args(24,'hostname');callbacks.onEnter.call({},a);assert.equal(a[3].text,'original');
a=args(23,'numplayers');callbacks.onEnter.call({},a);assert.equal(a[3].text,'original');
a=args(24,'numplayers');callbacks.onEnter.call({},a);assert.equal(a[3].text,'original');
a=args(23,'mapname');callbacks.onEnter.call({},a);assert.equal(a[3].text,'original');
readOnly=true;a=args(23,'hostname');callbacks.onEnter.call({},a);assert.equal(a[3].text,'original');
readOnly=false;browserMetadata.hostName=null;a=args(23,'hostname');callbacks.onEnter.call({},a);assert.equal(a[3].text,'original');
'''
        result=subprocess.run(['node'],input=script,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_lobby_name_format_and_invalid_input(self):
        source = (_test_paths.ROOT/'headless/headless_host.js').read_text(encoding='utf-8')
        policy = source[source.index('function browserLobbyName('):source.index('function browserContext(')]
        script = policy + r'''
const assert=require('node:assert/strict');
assert.equal(browserLobbyName({}),null);
assert.equal(browserLobbyName({lobbyName:'\u2605 ROBZ 2v2 \u2605',lobbyColor:'FF0000'}),'<c(ff0000)>\u2605 ROBZ 2v2 \u2605');
assert.equal(browserLobbyName({lobbyName:'ROBZ'}),'ROBZ');
for(const options of [{lobbyColor:'ff0000'},{lobbyName:''},{lobbyName:'   '},
    {lobbyName:'a\nb'},{lobbyName:'<c(red)>name'},{lobbyName:'a'.repeat(65)},
    {lobbyName:'ROBZ',lobbyColor:'red'},{lobbyName:'ROBZ',lobbyColor:'ff0000>'}])
    assert.throws(()=>browserLobbyName(options));
'''
        result = subprocess.run(['node'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

if __name__ == '__main__':
    unittest.main()
