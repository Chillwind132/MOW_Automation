"""Native audio reset must reject unsafe state before performing any engine call."""
import _test_paths  # Shared paths for direct runs and test discovery.
from pathlib import Path
import subprocess
import unittest

class AudioResetTests(unittest.TestCase):
    def test_preconditions_and_device_failure(self):
        source=(_test_paths.ROOT/'headless/headless_host.js').read_text()
        start=source.index("} else if (action === 'reset-audio-cache') {")
        body=source[start:source.index("} else if (action === 'optimize-heap')",start)]
        body=body[body.index('{')+1:]
        script=r'''
        for(const scenario of ['valid','world','remote','stage','signature','disabled','vector','reset_failure']) {
          let calls=0;
          const signatures={0x5c3b70:'b99c1ef300e836ebffffb908',0x5c26b0:'8b41083b410c744356578b79',
            0x5c6590:'558bec81ec30010000833d88',0x5c2700:'8b41083b410c741b56578b79',0x5c7b70:'538bd956578b43243b432874'};
          function pointer(n){return {isNull:()=>n===0,sub:p=>({toUInt32:()=>(n-p.n)>>>0}),compare:p=>n-p.n,n};}
          function lobbyPage(){if(scenario==='stage')throw Error('stage');}
          function lobbyProbe(){return {hostMemberIdRaw:1,localMemberIdRaw:1,
            rows:[{typeRaw:4,memberIdRaw:1},{typeRaw:scenario==='remote'?1:2,memberIdRaw:2}]};}
          function va(address){return {
            readPointer:()=>pointer(address===0xfe17d4?(scenario==='world'?1:0):
              address===0xfb142c?100:scenario==='vector'?99:100+(calls?0:80)),
            readU32:()=>address===0xf31f88?+(scenario==='disabled'||(calls&&scenario==='reset_failure')):10,
            readByteArray:()=>Uint8Array.from(Buffer.from(scenario==='signature'?'000000000000000000000000':signatures[address],'hex'))};}
          function call(address,type,args,abi){
            if(address!==0x5c3b70||type!=='void'||args.length||abi!=='mscdecl')throw Error('wrong native call');
            return ()=>calls++;
          }
          let error=false,result;
          try{result=(function(){BODY})();}catch(_){error=true;}
          if(scenario==='valid'){
            if(error||calls!==1||result.audioReset.before.sampleEntries!==10||result.audioReset.after.sampleEntries!==0)
              throw Error('valid reset failed');
          }else if(scenario==='reset_failure'){
            if(!error||calls!==1)throw Error('device failure not surfaced');
          }else if(!error||calls!==0)throw Error('unsafe native call '+scenario);
        }
        '''.replace('BODY',body)
        subprocess.run(['node'],input=script,capture_output=True,encoding='utf-8',check=True)

if __name__=='__main__':unittest.main()
