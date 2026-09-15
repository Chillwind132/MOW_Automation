"""Real JS capture preserves required scores despite oversized optional lists."""
import _test_paths  # Shared paths for direct runs and test discovery.
import json
from pathlib import Path
import subprocess
import unittest
import tempfile

from modules.end_game_results.legacy import normalize_statistics, normalize_completion

ROOT=_test_paths.ROOT


class SummaryCaptureTests(unittest.TestCase):
    def test_live_hud_rebuild_discards_partial_sample_and_recovers(self):
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('headless/headless_host.js','utf8').replace('// @include modules/live_game_data/bridge.js',fs.readFileSync('modules/live_game_data/bridge.js','utf8'));
const code=source.slice(source.indexOf('let hudCache='),source.indexOf('function requireSoloGame'));
let changed=false,scans=0;
const ptr=a=>({a:Number(a),add(n){return ptr(this.a+n)},toString(){return '0x'+this.a.toString(16)},
    isNull(){return !this.a},equals(p){return this.a===p.a},readU32(){return 3}});
const nodes=[{address:'0x1000',parent:null,vtable:1,name:'page'},
    {address:'0x2000',parent:'0x1000',vtable:2,name:'timer',text:'1:00'},
    {address:'0x3000',parent:'0x1000',vtable:2,name:'counter',text:'1 / 160'}];
const ctx={ptr,va:ptr,state:()=>({page:'0x1000',pageVtable:0xe2ae58}),
    read:p=>ptr(p.a===0xfed0c4?0x4000:p.a===0x4000?99:
        p.a===0x1000?1:[0x2000,0x3000].includes(p.a)?2:
        p.a===0x309c&&changed?0x9999:0x1000),rva:p=>p.a,
    statisticsProbe:()=>{scans++;return {nodes}},stringAt:()=> '1 / 160'};
vm.createContext(ctx);vm.runInContext(code,ctx);
assert.equal(ctx.liveProbe().hud.length,2);
changed=true;
const failed=ctx.liveProbe();
assert.equal(failed.hud.length,0);assert.equal(failed.hudStatus,'unavailable');
assert.match(failed.hudError,/ownership changed/);assert.equal(failed.managerStateRaw,3);
changed=false;
assert.equal(ctx.liveProbe().hudStatus,'observed');assert.equal(scans,2);
'''
        subprocess.run(['node','-e',script],cwd=ROOT,check=True,capture_output=True,text=True)

    def test_fixed_team_slot_list_is_traversed_with_native_ownership_guard(self):
        nodes = [dict(address='0x1000', parent=None, vtable=0xe2b2cc, name='mp_sessionclient', text=''),
            dict(address='0x2000', parent='0x1000', vtable=0xd8e478, name='slots', text=''),
            dict(address='0x3000', parent='0x2000', vtable=0xd82e0c, name='2:a', text='empty'),
            dict(address='0x4000', parent='0x1000', vtable=0xd8e30c, name='optional', text='')]
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / 'lobby.json'
            for native_parent in ('0x2000', '0x0', '0x9999'):
                malformed = native_parent == '0x9999'
                nodes[2]['nativeParent'] = native_parent
                fixture.write_text(json.dumps(dict(nodes=nodes)))
                result = subprocess.run(['node', 'tests/statistics_probe_harness.js', str(fixture),
                    '{"includeRaw":false}'], cwd=ROOT, capture_output=True, text=True)
                if malformed:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Invalid owned lobby slot row', result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('2:a', [n['name'] for n in json.loads(result.stdout)['nodes']])

    def capture(self,name,options=None):
        path=ROOT/'tests/fixtures'/name
        result=subprocess.run(['node','tests/statistics_probe_harness.js',str(path),json.dumps(options or {})],
            cwd=ROOT,check=True,capture_output=True,text=True)
        return json.loads(path.read_text()),json.loads(result.stdout)

    def test_lightweight_capture_preserves_fields_without_raw_memory_reads(self):
        _,full=self.capture('ai_completion.json')
        _,light=self.capture('ai_completion.json',{'includeRaw':False})
        for node in full['nodes']:node.pop('rawHeaderHex',None)
        self.assertEqual(light,full)

    def test_search_prunes_panel_descendants(self):
        fixture=json.loads((ROOT/'tests/fixtures/ai_completion.json').read_text())
        root=fixture['nodes'][0]['name']
        _,result=self.capture('ai_completion.json',{'includeRaw':False,'pruneName':root})
        self.assertEqual(len(result['nodes']),1)
        self.assertEqual(result['nodes'][0]['name'],root)

    def test_expired_ui_budget_rejects_partial_capture(self):
        result=subprocess.run(['node','tests/statistics_probe_harness.js',
            str(ROOT/'tests/fixtures/ai_completion.json'),'{"deadline":0}'],
            cwd=ROOT,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('UI probe time budget exceeded',result.stderr)
        self.assertEqual(result.stdout,'')

    def test_postmatch_scores_survive_million_entry_detail_lists(self):
        original,summary=self.capture('solo_statistics.json')
        self.assertEqual(normalize_statistics(original),normalize_statistics(summary))
        self.assertEqual(summary['captureScope'],'player_team_summary')
        self.assertLess(len(summary['nodes']),len(original['nodes']))

    def test_completion_outcome_and_participants_survive_large_details(self):
        original,summary=self.capture('ai_completion.json')
        match=json.loads((ROOT/'tests/fixtures/ai_match.json').read_text())
        normalize=lambda raw:normalize_completion(raw,match['loaded_roster'],match['participants'])
        self.assertEqual(normalize(original),normalize(summary))


if __name__=='__main__':unittest.main()
