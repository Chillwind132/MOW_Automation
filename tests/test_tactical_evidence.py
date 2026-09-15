import _test_paths
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tactical_controller import Evidence, main
from tactical_results import summarize


class EvidenceTests(unittest.TestCase):
    def test_physical_movement_requires_displacement_and_keeps_incarnations_separate(self):
        from tactical_results import MovementMetrics
        metrics=MovementMetrics(['1','2'])
        def raw(t,x,incarnation=1):
            return dict(generation='match',simulationTicks=t,units=[
                dict(id='1',incarnation=incarnation,eligible=True,position=[x,0,0]),
                dict(id='2',incarnation=1,eligible=True,position=[100,0,0])])
        metrics.observe(raw(1000,0));metrics.observe({'terminal':{},'status':'completed'})
        metrics.observe(raw(1200,.5))
        self.assertEqual(metrics.result()['movedIdentities'],0)
        metrics.observe(raw(1400,10))
        result=metrics.result()
        self.assertEqual(result['firstMovementSeconds'],{'1:1':.4})
        self.assertEqual(result['movingFractions'][-1]['fraction'],.5)
        metrics.observe(raw(1600,500,2))
        self.assertNotIn('1:2',metrics.result()['firstMovementSeconds'])
        self.assertEqual(metrics.result()['finalSpacing']['nearestNeighborMinWorld'],400.)
        with self.assertRaisesRegex(ValueError,'generations'):
            metrics.observe({**raw(1800,10),'generation':'other'})

    def test_army_report_separates_arrival_expiry_and_other_retirement(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            records = [dict(terminal={}, status=status) for status in
                       ('completed', 'failed', 'cancelled', 'uncertain')]
            records += [dict(retired={'expires': 10}, simulationTime=t) for t in (9, 10, 11, None)]
            (directory / 'observations.jsonl').write_text('\n'.join(json.dumps(r) for r in records))
            (directory / 'summary.json').write_text(json.dumps(dict(result='observed',
                scenario='serialized_bot_army_combat', elapsedSimulationSeconds=120,
                selectedUnits=['1', '2'], reachedUnits=['1'], nativeDeaths=0,
                runtimeStepMaxMs=150, withdrawalArrivals=1)))
            report = summarize([directory])
            run = report['runs'][0]
            self.assertEqual(run['simulationSeconds'], 120)
            self.assertEqual(run['army']['reachedUnits'], ['1'])
            self.assertEqual(run['army']['runtimeStepMaxMs'], 150)
            for field in ('completed', 'terminalFailed', 'terminalCancelled', 'terminalUncertain',
                          'retiredBeforeDeadline', 'retiredWithoutTiming'):
                self.assertEqual(run['metrics'][field], 1)
            self.assertEqual(run['metrics']['retired'], 4)
            self.assertEqual(run['metrics']['retiredAtDeadline'], 2)
            self.assertEqual(report['aggregates'][0]['passed'], 0)
            self.assertFalse(report['releaseReady'])

    def test_empty_or_declared_lost_evidence_never_counts_as_a_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            summary = dict(result='pass', scenario='fixture', simulationSeconds=10)
            for contents, loss in [('', None), ('{}\n', {'reason': 'record loss'})]:
                (directory / 'observations.jsonl').write_text(contents)
                (directory / 'summary.json').write_text(json.dumps({**summary, 'evidenceLoss': loss}))
                report = summarize([directory])
                self.assertFalse(report['runs'][0]['completeEvidence'])
                self.assertEqual(report['runs'][0]['evidenceLoss'], loss)
                self.assertEqual(report['aggregates'][0]['passed'], 0)
                self.assertIsNone(report['aggregates'][0]['simulationSeconds'])

    def test_rotation_bounds_disk_and_marks_partial_metrics(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'run'
            evidence = Evidence(directory, limit=64, retained_files=3)
            record = {'intent': {'action': 'move'}}
            for _ in range(15):
                evidence.write(record)
                files = list(directory.glob('observations*.jsonl'))
                self.assertLessEqual(len(files), 3)
                self.assertTrue(all(p.stat().st_size <= 64 for p in files))
            summary = dict(result='pass', scenario='fixture', simulationSeconds=10)
            evidence.close(summary)
            retained = sum(len(p.read_text().splitlines()) for p in directory.glob('observations*.jsonl'))
            metadata = json.loads((directory / 'retention.json').read_text())
            self.assertEqual(metadata['recordsWritten'], 15)
            self.assertEqual(metadata['retainedRecords'], retained)
            self.assertEqual(metadata['discardedRecords'], 15 - retained)
            report = summarize([directory])
            self.assertEqual(report['runs'][0]['metrics']['issued'], retained)
            self.assertFalse(report['runs'][0]['completeEvidence'])
            self.assertEqual(report['aggregates'][0]['passed'], 0)
            self.assertIsNone(report['aggregates'][0]['simulationSeconds'])

    def test_retained_archives_preserve_complete_short_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'run'
            evidence = Evidence(directory, limit=32, retained_files=4)
            for _ in range(3):
                evidence.write({'intent': {'action': 'move'}})
            evidence.close(dict(result='pass', scenario='fixture', simulationSeconds=3))
            report = summarize([directory])
            self.assertTrue(report['runs'][0]['completeEvidence'])
            self.assertEqual(report['runs'][0]['metrics']['issued'], 3)
            self.assertEqual(report['aggregates'][0]['passed'], 1)
            next(directory.glob('observations.*.jsonl')).unlink()
            self.assertFalse(summarize([directory])['runs'][0]['completeEvidence'])

    def test_strict_and_oversized_records_fail_without_discarding(self):
        with tempfile.TemporaryDirectory() as temporary:
            for retained in (1, 4):
                directory = Path(temporary) / str(retained)
                evidence = Evidence(directory, limit=16, retained_files=retained)
                evidence.write({'n': 1})
                before = (directory / 'observations.jsonl').read_bytes()
                with self.assertRaisesRegex(RuntimeError, 'size limit'):
                    evidence.write({'long': 'x' * 40})
                self.assertEqual((directory / 'observations.jsonl').read_bytes(), before)
                self.assertEqual(evidence.retention()['discardedRecords'], 0)
                if retained == 1:
                    evidence.write({'n': 2})
                    with self.assertRaisesRegex(RuntimeError, 'size limit'):
                        evidence.write({'n': 3})
                evidence.close({})

    def test_cli_run_is_unbounded_unless_duration_is_explicit(self):
        for mode, extra, duration in [('run', [], None), ('observe', [], 30),
                                      ('run', ['--duration', '5'], 5.)]:
            with patch('sys.argv', ['tactical_controller', mode, '--pid', '1', *extra]), \
                    patch('tactical_controller.observe', return_value={'result': 'observed', 'samples': 0}) as observe, \
                    patch('builtins.print'):
                self.assertEqual(main(), 0)
                self.assertEqual(observe.call_args.args[1], duration)


if __name__ == '__main__':
    unittest.main()
