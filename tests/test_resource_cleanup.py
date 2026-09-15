"""Native cleanup stays confined to a verified, unloaded local bot lobby."""
import _test_paths  # Shared paths for direct runs and test discovery.
import json
from pathlib import Path
import subprocess
import unittest


class ResourceCleanupTests(unittest.TestCase):
    def test_reload_option_probe_guards_and_releases_temporary_key(self):
        source=(_test_paths.ROOT/'headless/headless_host.js').read_text()
        start=source.index("if (options.target === 'reload-cache') {")
        end=source.index("if (options.target === 'social')",start)
        body=source[start:end]
        body=body[body.index('{')+1:body.rfind('}')]
        script=r'''
        for(const scenario of ['present','absent','world','signature','query_error']) {
          const signatures={0x713e40:'558bec8b5508568b',0x714260:'568bf1837e300075',0x444b30:'568bf18b462c578d'};
          let calls=[];
          function read(){return {isNull:()=>scenario!=='world'};}
          function va(a){return {readByteArray:()=>Uint8Array.from(Buffer.from(scenario==='signature'?'0000000000000000':signatures[a],'hex'))};}
          const Memory={alloc:()=>({}),allocUtf8String:s=>s};
          function call(address){return ()=>{
            calls.push(address);
            if(address===0x714260){if(scenario==='query_error')throw Error('query');return scenario==='present'?1:0;}
          };}
          let result,error=false;
          try{result=(function(){BODY})();}catch(_){error=true;}
          if(['world','signature'].includes(scenario)){
            if(!error || calls.length)throw Error('guard failed '+scenario);
          }else{
            if(calls.join()!==[0x713e40,0x714260,0x444b30].join())throw Error('key lifetime');
            if(scenario==='query_error'?!error:(error || result.probe.noReloadCachingPresent!==(scenario==='present')))
              throw Error('query result '+scenario);
          }
        }
        '''.replace('BODY',body)
        subprocess.run(['node'],input=script,capture_output=True,encoding='utf-8',check=True)

    def test_guards_precede_native_cleanup(self):
        source=(_test_paths.ROOT/'headless/headless_host.js').read_text()
        start=source.index("} else if (action === 'cleanup-resources') {")
        body=source[start:source.index("} else if (action === 'reset-audio-cache')",start)]
        body=body[body.index('{')+1:]
        script=r'''
        const valid='558bec83ec34833dd417fe00';
        for(const scenario of ['valid','world','remote','signature','stage']) {
          let invoked=0;
          function lobbyPage(){if(scenario==='stage') throw Error('wrong stage');}
          function lobbyProbe(){return {hostMemberIdRaw:1,localMemberIdRaw:1,
            rows:[{typeRaw:4,memberIdRaw:1},{typeRaw:scenario==='remote'?1:2,memberIdRaw:2}]};}
          function read(){return {isNull:()=>scenario!=='world'};}
          function va(){return {readU32:()=>100,readByteArray:()=>Uint8Array.from(Buffer.from(scenario==='signature'?'000000000000000000000000':valid,'hex'))};}
          function call(address,type,args,abi){
            if(address!==0x9ba180 || type!=='void' || args.length || abi!=='mscdecl') throw Error('wrong routine');
            return ()=>{invoked++;};
          }
          let rejected=false;
          try { (function(){ BODY })(); } catch(error) { rejected=true; }
          if(scenario==='valid' ? (rejected || invoked!==1) : (!rejected || invoked!==0))
            throw Error('guard failure: '+scenario);
        }
        '''.replace('BODY',body)
        subprocess.run(['node'],input=script,capture_output=True,encoding='utf-8',check=True)


if __name__=='__main__': unittest.main()
