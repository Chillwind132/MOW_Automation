import _test_paths  # Shared paths for direct runs and test discovery.
import copy
import json
from pathlib import Path
import subprocess
import unittest

from completion_guard import completion_signature

ROOT=_test_paths.ROOT


class CompletionGuardTests(unittest.TestCase):
    def test_rebuilt_rows_match_but_changed_results_do_not(self):
        raw=json.loads((ROOT/'tests/fixtures/ai_completion.json').read_text())
        root=next(n['address'] for n in raw['nodes'] if n['name']=='mp_result')
        original=completion_signature(raw['nodes'],root)
        changed=copy.deepcopy(raw['nodes'])
        addresses={n['address']:hex(int(n['address'],16)+0x1000) for n in changed}
        for n in changed:
            if (n.get('name') or '').lower()==n['address'].removeprefix('0x').lower():
                n['name']=addresses[n['address']].removeprefix('0x')
            n['address']=addresses[n['address']]
            n['parent']=addresses.get(n['parent'],n['parent'])
        self.assertEqual(original,completion_signature(changed,addresses[root]))
        source=(ROOT/'headless/headless_host.js').read_text()
        fn=source[source.index('function completionSignature('):source.index('function statisticsProbe(')]
        js=fn+'\nprocess.stdout.write(JSON.stringify(completionSignature('+json.dumps(changed)+','+json.dumps(addresses[root])+')));'
        result=subprocess.run(['node'],input=js,capture_output=True,encoding='utf-8',check=True)
        self.assertEqual(original,json.loads(result.stdout))
        title=next(n for n in changed if n.get('text')=='A Team wins!')
        title['text']='B Team wins!'
        self.assertNotEqual(original,completion_signature(changed,addresses[root]))


if __name__=='__main__': unittest.main()
