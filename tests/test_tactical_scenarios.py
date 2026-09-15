import _test_paths
import unittest
from unittest.mock import patch

from tactical_scenarios import (objective_trial, weapon_trial, pause_trial, friendly_reload_watch,
    manual_move_trial, army_mode_setup, army_objectives_trial, army_combat_trial)


class ArmyTrialTests(unittest.TestCase):
    def test_stranded_survivor_adoption_preserves_manual_and_group_scope(self):
        from types import SimpleNamespace
        from test_tactical_adapter import native
        from tactical_scenarios import BotSupply
        for scope,revision,expected in ((True,0,True),(False,0,False),(True,1,False)):
            calls=[]
            def request(intent):
                calls.append(intent)
                return dict(status='serialized') if intent['action']=='mode' else dict(status='queried',available=False)
            supply=BotSupply(SimpleNamespace(trialstance=request),SimpleNamespace(sequence=0,_submission_events=lambda r:None),SimpleNamespace(write=lambda r:None))
            raw=native();raw['units'][0].update(squadLeader=True,individualOrder=scope,enrolled=False,movementBits=4096,revision=revision)
            supply.step(raw)
            self.assertEqual(any(c['action']=='mode' for c in calls),expected)

    def test_supply_queries_and_purchases_the_same_verified_infantry_type(self):
        from types import SimpleNamespace
        from test_tactical_adapter import native
        from tactical_scenarios import BotSupply
        for completed,kind in ((0,'rifle'),(1,'rifle'),(2,'rifle'),(64,'rifle'),(256,None)):
            calls=[]
            def request(intent):
                calls.append(intent)
                return dict(status='queried',available=True) if intent['action']=='purchase_query' else dict(status='submitted_unconfirmed')
            supply=BotSupply(SimpleNamespace(trialstance=request),
                SimpleNamespace(sequence=0,_submission_events=lambda r:None),SimpleNamespace(write=lambda r:None))
            supply.purchases=completed;raw=native();raw['units']=[];supply.step(raw)
            if kind is None:
                self.assertEqual(calls,[])
                continue
            self.assertEqual([r['action'] for r in calls],['purchase_query','purchase'])
            self.assertEqual([r['purchaseTemplate'] for r in calls],[kind,kind])

    def test_supply_waits_for_purchase_and_observed_mode_without_replay(self):
        import copy
        from types import SimpleNamespace
        from test_tactical_adapter import native
        from tactical_scenarios import BotSupply
        calls=[]
        def request(intent):
            calls.append(intent)
            return {'purchase_query':dict(status='queried',available=True),
                    'purchase':dict(status='submitted_unconfirmed'),
                    'mode':dict(status='serialized')}[intent['action']]
        api=SimpleNamespace(trialstance=request)
        evidence=SimpleNamespace(write=lambda r:None)
        adapter=SimpleNamespace(sequence=0,_submission_events=lambda r:None)
        supply=BotSupply(api,adapter,evidence)
        raw=native();unit=raw['units'].pop()
        supply.step(raw)
        self.assertEqual([r['action'] for r in calls],['purchase_query','purchase'])
        raw['simulationTicks']=1200;supply.step(raw)
        self.assertEqual(len(calls),2)
        unit.update(enrolled=False,movementBits=4096,revision=0)
        raw.update(simulationTicks=1500,units=[unit]);supply.step(raw)
        self.assertEqual(calls[-1]['action'],'mode')
        self.assertTrue(calls[-1]['adoptAfterMode'])
        raw['simulationTicks']=1700;supply.step(raw)
        self.assertEqual(len(calls),3)
        unit.update(enrolled=True,movementBits=0,revision=1)
        raw['simulationTicks']=2000;supply.step(raw)
        self.assertEqual(supply.adopted,1)
        self.assertFalse(supply.recruits)
        self.assertEqual(len(calls),3)

    def test_unobserved_purchase_stops_without_purchasing_again(self):
        from types import SimpleNamespace
        from test_tactical_adapter import native
        from tactical_scenarios import BotSupply
        calls=[]
        def request(intent):
            calls.append(intent['action'])
            return dict(status='queried',available=True) if intent['action']=='purchase_query' else dict(status='submitted_unconfirmed')
        supply=BotSupply(SimpleNamespace(trialstance=request),
            SimpleNamespace(sequence=0,_submission_events=lambda r:None),SimpleNamespace(write=lambda r:None))
        raw=native();raw['units']=[];supply.step(raw)
        raw['simulationTicks']=47000
        with self.assertRaisesRegex(RuntimeError,'unobserved'):supply.step(raw)
        self.assertEqual(calls,['purchase_query','purchase'])

    def test_timing_metrics_distinguish_simulation_and_sampler_gaps(self):
        from tactical_scenarios import timing_metrics
        samples=[(0.,1000,0,123),(.01,1000,0,123),(.02,1020,0,123),(.03,1020,0,123),(.04,1040,0,123)]
        metrics=timing_metrics(samples)
        self.assertAlmostEqual(metrics['simulationToWallRatio'],1.)
        self.assertEqual(metrics['simulationProgressGapMs']['count'],2)
        self.assertAlmostEqual(metrics['simulationProgressGapMs']['median'],20.)
        self.assertAlmostEqual(metrics['samplerGapMs']['median'],10.)
        for last in ((.04,1040,1,123),(.04,900,0,123),(.04,1040,0,456),(.01,1040,0,123)):
            with self.assertRaises(ValueError): timing_metrics(samples[:-1]+[last])
        with self.assertRaises(ValueError): timing_metrics([(0.,1000,0,123),(.1,1000,0,123)])

    def test_bot_runtime_counts_death_and_stops_on_terminal_match(self):
        import copy
        from test_tactical_adapter import native
        baseline = native()
        baseline.update(botTrialRoster='["card","123",[]]', playerTeams={'2': 'a', '3': 'b'})
        baseline['capabilities'].update(move=False, stance=False, attack=False, contacts=False, death=False)
        template = baseline['units'][0]
        baseline['units'] = [dict(template, id=str(i), squadMembers=[str(j) for j in range(4)],
            position=[float(i) * 100, 0., 0.]) for i in range(4)]
        class Api:
            def __init__(self): self.raw, self.samples, self.orders = copy.deepcopy(baseline), 0, []
            def snapshot(self):
                self.samples += 1
                self.raw['simulationTicks'] += 200
                self.raw['events'] = []
                if self.samples == 3:
                    self.raw['units'][0].update(eligible=False, enrolled=False, nativeDeadPredicate=True)
                    self.raw['events'] = [dict(key=1, kind='owned_death', id='0', incarnation=1,
                        position=[0., 0., 0.], simulationTicks=self.raw['simulationTicks'])]
                if self.samples == 8:
                    self.raw['playing'] = False
                    self.raw['managerStateRaw'] = 3
                return copy.deepcopy(self.raw)
            def trialstance(self, options):
                self.orders.append((self.samples, options))
                if options['action'] == 'move':
                    next(u for u in self.raw['units'] if u['id'] == options['id'])['position'] = options['destination']
                return dict(status='serialized')
        class Evidence:
            def write(self, record): pass
        api, summary = Api(), {}
        with patch('tactical_scenarios.time.sleep'):
            army_combat_trial(api, baseline, Evidence(), summary)
        self.assertEqual(summary['nativeDeaths'], 1)
        self.assertTrue(summary['matchCompleted'])
        self.assertEqual(summary['result'], 'observed')
        self.assertGreater(summary['orders']['move'], 0)
        self.assertFalse(any(n >= 3 and o['id'] == '0' for n, o in api.orders))
        self.assertFalse(api.raw['capabilities']['move'])

        # Purchase/mode RPCs drain shots produced after the captured snapshot.
        # They must be consumed by the following snapshot, never the old one.
        class Supply:
            purchases=0
            adopted=0
            def __init__(self, api, adapter, evidence): self.adapter=adapter
            def step(self, raw, snapshot, policy):
                self.adapter.events.append(dict(key=10000+raw['simulationTicks'],
                    kind='bullet_created', id='1', incarnation=1,
                    simulationTicks=raw['simulationTicks']+1))
        baseline['capabilities']['shotEvents']=True
        baseline['paused']=True
        class ResumingApi(Api):
            def trialstance(self, options):
                if options['action'] == 'cover_scored_query':
                    self.orders.append((self.samples, options))
                    return dict(status='rejected', rejected=True)
                return super().trialstance(options)
            def snapshot(self):
                raw=super().snapshot()
                raw['paused']=self.samples==1
                return raw
        api, summary=ResumingApi(), {}
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            evidence=Evidence();evidence.path=Path(folder)
            with patch('tactical_scenarios.time.sleep'), patch('tactical_scenarios.BotSupply', Supply):
                army_combat_trial(api, baseline, evidence, summary, battle=True)
            (evidence.path/'STOP').touch()
            stopped={};idle=Api()
            army_combat_trial(idle,baseline,evidence,stopped,battle=True)
            self.assertTrue(stopped['controllerStoppedByFile'])
            self.assertEqual(idle.samples,0)
            self.assertFalse(idle.orders)
        self.assertTrue(summary['matchCompleted'])
        self.assertEqual(summary['nativeDeaths'],1)
        self.assertFalse(any(n==1 for n,_ in api.orders))

    def test_bot_runtime_refuses_missing_roster_proof(self):
        with self.assertRaisesRegex(RuntimeError, 'guarded'):
            army_combat_trial(None, dict(playing=True, paused=False), None, {})

    def test_gameplay_disappearance_is_not_completion(self):
        from types import SimpleNamespace
        from test_tactical_adapter import native
        baseline = native()
        baseline.update(botTrialRoster='verified')
        baseline['units'] = [dict(baseline['units'][0], id=str(i)) for i in range(4)]
        for state in (None, 0, 2, True, '3'):
            summary = {}
            raw = dict(baseline, playing=False, managerStateRaw=state)
            army_combat_trial(SimpleNamespace(snapshot=lambda: raw), baseline,
                SimpleNamespace(write=lambda record: None), summary)
            self.assertTrue(summary['gameplayStopped'])
            self.assertFalse(summary['matchCompleted'])

    def test_new_desync_stops_before_orders_and_never_claims_completion(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from unittest.mock import Mock
        from test_tactical_adapter import native
        baseline = native()
        baseline.update(botTrialRoster=json.dumps(['card', 'epoch', []]))
        failure = dict(source='new_native_game_log_entry', nativeQuant=1000)
        for playing in (True, False):
            with TemporaryDirectory() as folder:
                api = SimpleNamespace(snapshot=Mock(return_value=dict(baseline, playing=playing,
                    paused=True, managerStateRaw=3)), trialstance=Mock())
                evidence = SimpleNamespace(path=Path(folder), write=Mock())
                summary = {}
                monitor = SimpleNamespace(poll=Mock(return_value=failure), status='native_desync_observed')
                with patch('tactical_scenarios.SyncLogMonitor', return_value=monitor):
                    army_combat_trial(api, baseline, evidence, summary, battle=True)
                api.trialstance.assert_not_called()
                self.assertEqual(summary['failureKind'], 'out_of_sync')
                self.assertEqual(summary['outcome'], 'interrupted')
                self.assertFalse(summary['matchCompleted'])
                self.assertEqual(json.loads((Path(folder)/'synchronization_failure.json').read_text()), failure)

    def test_result_collection_requires_terminal_and_clean_detach(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from tactical_scenarios import collect_battle_result
        clean = dict(matchCompleted=True, stop={'stopped': True},
            postDetachCode={str(i): True for i in range(12)})
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            with patch('tactical_scenarios.subprocess.run', return_value=SimpleNamespace(
                    returncode=0, stdout='saved', stderr='')) as run:
                for change in ({'matchCompleted': False}, {'detachError': 'lost process'},
                        {'stop': {'stopped': False}}, {'postDetachCode': {}},
                        {'postDetachCode': dict(clean['postDetachCode'], **{'0': False})}):
                    collect_battle_result(123, output, dict(clean, **change))
                run.assert_not_called()
                summary = dict(clean)
                collect_battle_result(123, output, summary)
                run.assert_called_once()
                self.assertIn('finish-ai', run.call_args.args[0])
                self.assertEqual(summary['resultCollection']['status'], 'captured')
                self.assertEqual((output / 'result_collection.log').read_text(), 'saved')
            with patch('tactical_scenarios.subprocess.run', return_value=SimpleNamespace(
                    returncode=1, stdout='', stderr='generation mismatch')) as run:
                summary = dict(clean)
                collect_battle_result(123, output, summary)
                self.assertEqual(summary['resultCollection']['status'], 'failed')
                run.assert_called_once()

    def test_setup_preserves_scope_and_does_not_claim_same_session_enrollment(self):
        import copy
        baseline = dict(generation='match', commandRevision=0, playing=True, paused=False,
            owner='2', playerTeams={'2': 'a'}, units=[dict(id=str(i), incarnation=1, eligible=True,
                squadLeader=i == 0, controlLockRaw=0, movementBits=4096, enrolled=False) for i in range(4)])
        class Api:
            def __init__(self): self.raw, self.requests = copy.deepcopy(baseline), []
            def trialstance(self, request):
                self.requests.append(request)
                next(u for u in self.raw['units'] if u['id'] == request['id'])['movementBits'] = 0
                return dict(status='serialized')
            def snapshot(self): return self.raw
        class Evidence:
            def write(self, record): pass
        api, summary = Api(), {}
        army_mode_setup(api, baseline, Evidence(), summary)
        self.assertEqual(summary['setupModeOrders'], 3)
        self.assertEqual(summary['preparedUnits'], ['1', '2', '3'])
        self.assertFalse(any(u['enrolled'] for u in api.raw['units']))
        self.assertEqual(api.raw['units'][0]['movementBits'], 4096)
        baseline['playerTeams']['3'] = 'b'
        with self.assertRaisesRegex(RuntimeError, 'only the local'):
            army_mode_setup(api, baseline, Evidence(), {})

    def test_army_runtime_observes_arrival_without_promoting_production_gates(self):
        import copy
        from test_tactical_adapter import native
        baseline = native()
        baseline.update(playerTeams={'2': 'a'}, selectedOwnedIds=[],
            capabilities=dict(move=False, stance=False, objectives=False, death=False, ammoLoading=True))
        template = baseline['units'][0]
        baseline['units'] = [dict(template, id=str(i), squadMembers=[str(j) for j in range(4)],
            position=[float(i) * 100, 0., 0.]) for i in range(4)]
        baseline['objectives'][0]['captureRadius'] = 600
        class Api:
            def __init__(self): self.raw, self.orders = copy.deepcopy(baseline), []
            def snapshot(self):
                self.raw['simulationTicks'] += 1000
                if all(u['position'][0] > 1500 for u in self.raw['units']):
                    self.raw['objectives'][0]['occupant'] = 'a'
                return copy.deepcopy(self.raw)
            def trialstance(self, options):
                self.orders.append(options)
                next(u for u in self.raw['units'] if u['id'] == options['id'])['position'] = options['destination']
                return dict(status='serialized')
        class Evidence:
            def write(self, record): pass
        api, summary = Api(), {}
        with patch('tactical_scenarios.time.sleep'):
            army_objectives_trial(api, baseline, Evidence(), summary)
        self.assertEqual(summary['result'], 'pass')
        self.assertEqual(len(summary['arrivedUnits']), 4)
        self.assertEqual(summary['proximateCapturedObjectives'], ['flag'])
        self.assertFalse(api.raw['capabilities']['move'])
        self.assertTrue(all(o['requireEnrolled'] for o in api.orders))


class ManualMoveTests(unittest.TestCase):
    def test_only_addressed_player_order_and_specific_stale_rejection_pass(self):
        import copy
        unit = dict(id='18', incarnation=1, squadLeader=False, eligible=True, enrolled=True,
            controlLockRaw=0, movementBits=0, revision=2, stance=0)
        baseline = dict(generation='match', commandRevision=0, selectedOwnedIds=['18'], units=[unit], events=[])
        for variation in ('valid', 'wrong_rejection', 'still_enrolled', 'foreign_command'):
            raw = copy.deepcopy(baseline)
            raw['units'][0].update(enrolled=variation == 'still_enrolled', revision=3)
            raw.update(commandRevision=1, events=[dict(kind='player_command', type=1,
                ids=['other' if variation == 'foreign_command' else '18'])])
            class Api:
                def __init__(self): self.requests = []
                def snapshot(self): return raw
                def trialstance(self, request):
                    self.requests.append(request)
                    return dict(rejected=True, error='Game paused' if variation == 'wrong_rejection'
                                else 'Unit reclaimed or revision cancelled')
            class Evidence:
                def write(self, row): pass
            api, summary = Api(), {'pid': 1}
            with patch('tactical_scenarios.GameKeys') as keys, patch('tactical_scenarios.time.sleep'), \
                    patch('tactical_scenarios.time.monotonic', side_effect=[0, 0, 5]):
                if variation == 'valid':
                    manual_move_trial(api, baseline, Evidence(), summary, [20, 30])
                    self.assertEqual(summary['result'], 'pass')
                    self.assertEqual(api.requests[0]['unitRevision'], 2)
                    self.assertEqual(api.requests[0]['revision'], 1)
                else:
                    with self.assertRaises(RuntimeError):
                        manual_move_trial(api, baseline, Evidence(), summary, [20, 30])
                keys.return_value.close.assert_called_once()


class FriendlyReloadTests(unittest.TestCase):
    def test_pass_requires_two_observed_loading_cycles_for_eight_round_clips(self):
        baseline = dict(generation='match', playing=True, paused=False)
        class Evidence:
            def write(self, record): pass
        for observed_loading, second_clip in ((True, 8), (False, 8), (True, 15)):
            events = []
            for cycle, clip in ((1, 8), (2, second_clip)):
                if observed_loading:
                    events.append(dict(key=cycle * 2, kind='friendly_reload_progress', cycle=cycle, nativeLoading=True))
                events.append(dict(key=cycle * 2 + 1, kind='friendly_reload_end', cycle=cycle,
                    generation='match', nativeLoading=False, pendingRounds=0, ammoCount=clip,
                    ammoBefore=0, simulationTicks=7000, startedAtTicks=1000, clipSize=clip))
            class Api:
                def snapshot(self): return {**baseline, 'events': events}
            summary = {}
            with patch('tactical_scenarios.time.monotonic', side_effect=[0, 0, 61]), patch('tactical_scenarios.time.sleep'):
                friendly_reload_watch(Api(), baseline, Evidence(), summary)
            expected = 'pass' if observed_loading and second_clip == 8 else 'observed'
            self.assertEqual(summary['result'], expected)
            self.assertEqual(summary['ordersIssued'], 0)


class FriendlyCoverTests(unittest.TestCase):
    def test_idle_or_unknown_inputs_do_not_end_combat_sampling(self):
        baseline = dict(generation='match', playing=True, paused=False)
        class Evidence:
            def write(self, record): pass
        for inputs in (0, None, True, 14):
            events = [dict(key=i, kind='friendly_cover_assessment', weightsRaw=[0, 0, 10],
                candidateCount=1, inputRecordCountRaw=inputs, hasTargetRecordRaw=inputs == 14)
                for i in range(10)]
            class Api:
                def snapshot(self): return {**baseline, 'events': events}
            summary = {}
            with patch('tactical_scenarios.time.monotonic', side_effect=[0, 0, 1, 61]), patch('tactical_scenarios.time.sleep'):
                friendly_reload_watch(Api(), baseline, Evidence(), summary, cover=True)
            active = type(inputs) is int and inputs > 0
            self.assertEqual(summary['samples'], 1 if active else 2)
            self.assertEqual(summary['weightedCoverSamples'], 10)  # Repeated event keys are deduplicated.
            self.assertEqual(summary['weightedCoverWithInputs'], 10 if active else 0)
            self.assertEqual(summary['weightedCoverWithTarget'], 10 if active else 0)
            self.assertEqual(summary['result'], 'observed')
            self.assertEqual(summary['ordersIssued'], 0)


class PauseTrialTests(unittest.TestCase):
    def test_frozen_observations_rejection_and_resume(self):
        self.check_trial(False)

    def test_failed_clock_check_still_resumes(self):
        self.check_trial(True)

    def check_trial(self, moving_clock):
        baseline = dict(generation='match', playing=True, paused=False, simulationTicks=1000, commandRevision=0)
        class Api:
            def __init__(self): self.paused, self.calls, self.tick = False, [], 1000
            def pauserequest(self, resume):
                self.calls.append(resume); self.paused = not resume
                return dict(status='requested')
            def snapshot(self):
                if moving_clock or not self.paused: self.tick += 20
                return {**baseline, 'paused': self.paused, 'simulationTicks': self.tick}
            def trialstance(self, options):
                return dict(rejected=True, error='Error: Game paused')
        class Evidence:
            def write(self, record): pass
        api, summary = Api(), {}
        with patch('tactical_scenarios.time.sleep'):
            if moving_clock:
                with self.assertRaisesRegex(RuntimeError, 'frozen-clock'):
                    pause_trial(api, baseline, Evidence(), summary)
            else:
                pause_trial(api, baseline, Evidence(), summary)
                self.assertEqual(summary['result'], 'pass')
                self.assertEqual(summary['pausedSamples'], 5)
                self.assertTrue(summary['pausedActionRejected'])
        self.assertEqual(api.calls, [False, True])
        self.assertFalse(api.paused)
        self.assertTrue(summary['resumed'])


class CombatObservationTests(unittest.TestCase):
    def test_attack_trial_preserves_sequence_and_does_not_claim_completion(self):
        unit = dict(id='18', incarnation=1, revision=0, enrolled=True, position=[0., 0., 0.])
        baseline = dict(generation='match', commandRevision=0, playing=True, paused=False)
        target = dict(identity=dict(id='19', incarnation=1, owner='4'), entityId=1234, observedPosition=[300., 0., 0.])
        class Api:
            def __init__(self, accepted): self.requests, self.accepted = [], accepted
            def trialstance(self, options):
                self.requests.append(options)
                if options['action'] == 'attack_query': return dict(status='queried', targets=[target])
                if options['action'] == 'attack': return dict(status='serialized' if self.accepted else 'unknown')
                return dict(status='queried', projectileEvents=[dict(key=1)], simulationTicks=1000)
        class Evidence:
            def write(self, record): pass
        api, summary = Api(True), {}
        with patch('tactical_scenarios.time.monotonic', side_effect=[0, 0, 31]), patch('tactical_scenarios.time.sleep'):
            weapon_trial(api, baseline, unit, Evidence(), summary, 'attack', 10)
        self.assertEqual([r['sequence'] for r in api.requests], [11, 12, 13])
        self.assertEqual([r['action'] for r in api.requests], ['attack_query', 'attack', 'weapon_query'])
        self.assertTrue(summary['attackSerialized'])
        self.assertFalse(summary['attackCompleted'])
        self.assertEqual(summary['attributedBulletConstructions'], 1)
        api = Api(False)
        with self.assertRaisesRegex(RuntimeError, 'no replay'):
            weapon_trial(api, baseline, unit, Evidence(), {}, 'attack', 10)
        self.assertEqual(len(api.requests), 2)
        target['observedPosition'] = [1001., 0., 0.]
        api = Api(True)
        with self.assertRaisesRegex(RuntimeError, 'distance bound'):
            weapon_trial(api, baseline, unit, Evidence(), {}, 'attack', 10)
        self.assertEqual(len(api.requests), 1)

    def test_capture_proximity_uses_strict_native_3d_zone(self):
        for position, reached in (([589., 0., 0.], True), ([600., 0., 0.], False),
                                  ([589., 0., 200.], False)):
            with self.subTest(position=position):
                unit = dict(id='18', incarnation=1, revision=0, movementBits=0,
                            controlLockRaw=0, eligible=True, owner='2', enrolled=True, nativeDeadPredicate=False, squadLeader=False, stance=0, squadMembers=['18'], position=[1200., 0., 0.])
                flag = dict(key='flag', position=[0., 0., 0.], occupant='b', captureRadius=600.)
                baseline = dict(generation='match', simulationTicks=0, owner='2', team='a',
                    commandRevision=0, units=[unit], events=[], playing=True, paused=False, capabilities={}, objectives=[flag])
                class Api:
                    samples = 0
                    def snapshot(self):
                        self.samples += 1
                        return {**baseline, 'simulationTicks': self.samples * 200,
                            'units': [{**unit, 'position': position if self.samples > 1 else unit['position'],
                                       'eligible': self.samples < 3}],
                            'objectives': [{**flag, 'occupant': 'a' if self.samples > 1 else 'b'}]}
                    def trialstance(self, options):
                        return dict(status='queried' if options['action'].endswith('_query') else 'serialized')
                class Evidence:
                    def write(self, record): pass
                summary = {}
                with patch('tactical_scenarios.time.sleep'):
                    if reached:
                        objective_trial(Api(), baseline, unit, Evidence(), summary, True)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'yielded'):
                            objective_trial(Api(), baseline, unit, Evidence(), summary, True)
                self.assertEqual(summary['unitReachedObjective'], reached)
                self.assertEqual(summary['objectiveProximityBasis'], 'native shared capture zone')

    def test_objective_rejects_inactive_match_before_api_access(self):
        for state in (dict(playing=False, paused=False), dict(playing=True, paused=True), {}):
            with self.subTest(state=state), self.assertRaisesRegex(RuntimeError, 'active unpaused'):
                objective_trial(None, state, {}, None, {})

    def test_objective_lost_after_baseline_can_be_approached(self):
        unit = dict(id='18', incarnation=1, revision=0, movementBits=0,
                    controlLockRaw=0, eligible=True, owner='2', enrolled=True, nativeDeadPredicate=False, squadLeader=False, stance=0, squadMembers=['18'], position=[0., 0., 0.])
        baseline = dict(generation='match', simulationTicks=0, owner='2', team='a',
                        commandRevision=0, units=[unit], events=[], playing=True, paused=False, capabilities={},
                        objectives=[dict(key='flag', position=[2000., 0., 0.], occupant='a')])
        class Api:
            requests = []
            samples = 0
            def snapshot(self):
                self.samples += 1
                return {**baseline, 'simulationTicks': self.samples * 200,
                    'units': [{**unit, 'eligible': self.samples == 1}],
                    'objectives': [{**baseline['objectives'][0], 'occupant': 'b'}]}
            def trialstance(self, options):
                self.requests.append(options)
                return dict(status='serialized')
        class Evidence:
            def write(self, record):
                pass
        api = Api()
        with patch('tactical_scenarios.time.sleep'), self.assertRaisesRegex(RuntimeError, 'yielded'):
            objective_trial(api, baseline, unit, Evidence(), {})
        self.assertEqual([request['action'] for request in api.requests], ['move'])

    def test_combat_approach_uses_friendly_objective_without_claiming_capture(self):
        unit = dict(id='18', incarnation=1, revision=0, movementBits=0,
                    controlLockRaw=0, eligible=True, owner='2', enrolled=True, nativeDeadPredicate=False, squadLeader=False, stance=0, squadMembers=['18'], position=[0., 0., 0.])
        baseline = dict(generation='match', simulationTicks=0, owner='2', team='a',
            commandRevision=0, units=[unit], events=[], playing=True, paused=False, capabilities={},
            objectives=[dict(key='flag', position=[2000., 0., 0.], occupant='a')])
        class Api:
            def __init__(self): self.requests, self.samples = [], 0
            def snapshot(self):
                self.samples += 1
                return {**baseline, 'simulationTicks': self.samples * 200,
                        'units': [{**unit, 'eligible': self.samples < 3}]}
            def trialstance(self, options):
                self.requests.append(options)
                return dict(status='serialized' if options['action'] == 'move' else 'queried', targets=[])
        class Evidence:
            def write(self, record): pass
        api, summary = Api(), {}
        with patch('tactical_scenarios.time.sleep'), self.assertRaisesRegex(RuntimeError, 'yielded'):
            objective_trial(api, baseline, unit, Evidence(), summary, True, True)
        self.assertEqual([r['action'] for r in api.requests], ['weapon_query', 'attack_query', 'move'])
        self.assertIn('friendly objective', summary['approachPurpose'])
        self.assertNotIn('objectiveCaptured', summary)

    def test_admission_cancellation_replans_but_unknown_ack_stops(self):
        unit = dict(id='18', incarnation=1, revision=0, movementBits=0,
                    controlLockRaw=0, eligible=True, owner='2', enrolled=True, nativeDeadPredicate=False, squadLeader=False, stance=0, squadMembers=['18'], position=[0., 0., 0.])
        baseline = dict(generation='match', simulationTicks=0, owner='2', team='a',
            commandRevision=0, units=[unit], events=[], playing=True, paused=False, capabilities={},
            objectives=[dict(key='flag', position=[2000., 0., 0.], occupant='b')])
        class Api:
            def __init__(self, rejected): self.requests, self.samples, self.rejected = [], 0, rejected
            def snapshot(self):
                self.samples += 1
                return {**baseline, 'simulationTicks': self.samples * 1000,
                    'units': [{**unit, 'position': [self.samples * 10., 0., 0.], 'eligible': self.samples < 3}]}
            def trialstance(self, options):
                self.requests.append(options)
                if len(self.requests) == 1:
                    return dict(error='distance bound', rejected=self.rejected)
                return dict(status='serialized')
        class Evidence:
            def write(self, record): pass
        for rejected in (True, False):
            api, summary = Api(rejected), {}
            with patch('tactical_scenarios.time.sleep'), self.assertRaisesRegex(
                    RuntimeError, 'yielded' if rejected else 'Uncertain command'):
                objective_trial(api, baseline, unit, Evidence(), summary)
            self.assertEqual(len(api.requests), 2 if rejected else 1)
            if rejected:
                self.assertEqual(summary['admissionCancellations'], 1)
                self.assertEqual([r['sequence'] for r in api.requests], [1, 2])
                self.assertNotEqual(api.requests[0]['destination'], api.requests[1]['destination'])
            else:
                self.assertNotIn('admissionCancellations', summary)

    def test_objective_trial_uses_native_loading_guard(self):
        unit = dict(id='18', incarnation=1, revision=0, movementBits=0,
                    controlLockRaw=0, eligible=True, owner='2', enrolled=True, nativeDeadPredicate=False, squadLeader=False, stance=0, squadMembers=['18'], position=[0., 0., 0.])
        baseline = dict(generation='match', simulationTicks=0, owner='2', team='a',
            commandRevision=0, units=[unit], events=[], playing=True, paused=False,
            capabilities=dict(ammoLoading=True),
            objectives=[dict(key='flag', position=[2000., 0., 0.], occupant='b')])
        class Api:
            def __init__(self): self.samples, self.issued_at = 0, []
            def snapshot(self):
                self.samples += 1
                return {**baseline, 'simulationTicks': self.samples * 1000,
                    'units': [{**unit, 'eligible': self.samples < 3,
                        'ammunition': dict(simulationTicks=self.samples * 1000,
                            ammoCount=0 if self.samples == 1 else 8, nativeLoading=self.samples == 1)}]}
            def trialstance(self, options):
                self.issued_at.append(self.samples)
                return dict(status='serialized')
        class Evidence:
            def write(self, record): pass
        api = Api()
        with patch('tactical_scenarios.time.sleep'), self.assertRaisesRegex(RuntimeError, 'yielded'):
            objective_trial(api, baseline, unit, Evidence(), {})
        self.assertEqual(api.issued_at, [2])

    def test_queries_and_moves_share_sequence_and_preserve_rejected_events(self):
        unit = dict(id='18', incarnation=1, revision=0, movementBits=0,
                    controlLockRaw=0, eligible=True, owner='2', enrolled=True, nativeDeadPredicate=False, squadLeader=False, stance=0, squadMembers=['18'], position=[0., 0., 0.])
        baseline = dict(generation='match', simulationTicks=0, owner='2', team='a',
                        commandRevision=0, units=[unit], events=[], playing=True, paused=False, capabilities={},
                        objectives=[dict(key='flag', position=[2000., 0., 0.], occupant='b')])
        death = dict(key=1, kind='owned_death', id='18', incarnation=1,
                     position=[0., 0., 0.], simulationTicks=1000)
        class Api:
            requests = []
            ticks = -1000
            def snapshot(self):
                self.ticks += 1000
                return {**baseline, 'simulationTicks': self.ticks}
            def trialstance(self, options):
                self.requests.append(options)
                if len(self.requests) == 4:
                    return dict(rejected=True, observedEvents=[death, death])
                return dict(status='serialized' if options['action'] == 'move' else 'queried')
        class Evidence:
            def write(self, record):
                pass
        api, summary = Api(), {}
        with patch('tactical_scenarios.time.sleep'), self.assertRaisesRegex(RuntimeError, 'lost admission'):
            objective_trial(api, baseline, unit, Evidence(), summary, combat_observation=True)
        self.assertEqual([r['sequence'] for r in api.requests], [1, 2, 3, 4])
        self.assertEqual([r['action'] for r in api.requests],
                         ['weapon_query', 'sensor_query', 'move', 'weapon_query'])
        self.assertEqual(summary['observedNativeEvents'], {'owned_death': 1})
        self.assertEqual(summary['combatQueryCount'], 2)


if __name__ == '__main__':
    unittest.main()
