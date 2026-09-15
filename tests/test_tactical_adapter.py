import _test_paths
import copy
import unittest

from tactical_controller import NativeAdapter, Runtime


class NativeDeadlineTests(unittest.TestCase):
    def test_transport_timeout_is_cancelled_without_replaying_action(self):
        from unittest.mock import Mock, patch
        import frida
        from tactical_controller import native_call
        operation=Mock(side_effect=frida.OperationCancelledError('fixture'))
        timer=Mock()
        with patch('tactical_controller.threading.Timer',return_value=timer):
            with self.assertRaisesRegex(TimeoutError,'uncertain, no replay'):
                native_call(operation, {'action':'move'})
        operation.assert_called_once_with({'action':'move'})
        timer.start.assert_called_once()
        timer.cancel.assert_called_once()

    def test_native_call_returns_result_and_cancels_timer_on_other_errors(self):
        from unittest.mock import Mock, patch
        from tactical_controller import native_call
        timer=Mock()
        with patch('tactical_controller.threading.Timer',return_value=timer):
            self.assertEqual(native_call(lambda value:value,42),42)
            with self.assertRaises(ValueError):
                native_call(Mock(side_effect=ValueError('fixture')))
        self.assertEqual(timer.cancel.call_count,2)


def native(ticks=1000):
    return dict(generation='match', owner='2', team='a', simulationTicks=ticks,
        commandRevision=3, paused=False, playing=True, events=[],
        capabilities=dict(move=True, stance=True, objectives=True, death=True),
        objectives=[dict(key='flag', position=[2000., 0., 0.], occupant='b', reachable=None)],
        units=[dict(id='18', incarnation=1, owner='2', revision=7, eligible=True,
            enrolled=True, nativeDeadPredicate=False, squadLeader=False, squadMembers=['17', '18'],
            movementBits=0, controlLockRaw=0, stance=0, position=[0., 0., 10.])])


def with_contact(ticks=2000):
    raw = native(ticks)
    raw['capabilities']['contacts'] = True
    raw['perception'] = [dict(status='queried', generation='match', simulationTicks=ticks,
        observerIdentity=dict(id='18', incarnation=1, owner='2'), visualUpdateTicks=900,
        records=[dict(identity=dict(id='19', incarnation=1, owner='4'), visible=True, enemy=True,
            visualObservedPosition=[600., 0., 0.], visualObservedAtTicks=900,
            positionUpdateTicks=900, nativeDeadPredicate=False, recordedPosition=[99999., 0., 0.])])]
    return raw


class AllianceTests(unittest.TestCase):
    def test_support_requires_native_relationship_and_matching_known_team(self):
        for variation in ('allied', 'perceived_only', 'other_team', 'unknown_team', 'enemy'):
            raw = with_contact()
            record = raw['perception'][0]['records'][0]
            record.update(enemy=variation == 'enemy', nativeOwnerRelation=1 if variation == 'perceived_only' else 2)
            record['identity']['team'] = ('b' if variation == 'other_team' else
                                          None if variation == 'unknown_team' else 'a')
            snapshot = NativeAdapter(Api(), Evidence()).snapshot(raw)
            self.assertEqual(snapshot.contacts[0].allied, variation == 'allied')


class Evidence:
    def __init__(self):
        self.records = []
    def write(self, record):
        self.records.append(record)


class Api:
    def __init__(self, reply=None):
        self.requests = []
        self.reply = reply or dict(status='serialized')
        self.queries = []
        self.preflight = dict(status='queried', generation='match', simulationTicks=2000,
            observerIdentity=dict(id='18', incarnation=1, owner='2'),
            targets=[dict(identity=dict(id='19', incarnation=1, owner='4'), entityId=1234)])
    def trialstance(self, request):
        self.queries.append(request)
        return self.preflight
    def submit(self, request):
        self.requests.append(request)
        return self.reply


class NativeAdapterTests(unittest.TestCase):
    def test_only_proven_controller_group_preserves_movement_and_completions(self):
        from tactical_policy import Intent
        for enabled, proven, expected in ((True, True, True), (False, True, False), (True, False, False)):
            raw = native()
            raw['capabilities']['leaderFollow'] = enabled
            raw['units'][0].update(movementBits=8192, controllerGroup=proven)
            adapter = NativeAdapter(Api(), Evidence())
            snapshot = adapter.snapshot(raw)
            unit = snapshot.units[0]
            self.assertEqual(unit.move_at_will, expected)
            intent = Intent(unit.identity, 1, 1, 'move', 'objective', 40., destination=(0., 0.))
            self.assertEqual(adapter.completions(snapshot, {unit.identity: intent}),
                             [(intent, 'completed')] if expected else [])
            self.assertEqual(adapter.control_coverage()['individualControl'], int(expected))

    def test_control_coverage_explains_group_scope_and_native_mode_without_manual_attribution(self):
        raw = native()
        raw['units'].append(dict(copy.deepcopy(raw['units'][0]), id='17', squadLeader=True,
                                 individualOrder=False, enrolled=False))
        raw['units'][0].update(movementBits=8192, enrolled=False)
        adapter = NativeAdapter(Api(), Evidence())
        adapter.snapshot(raw)
        self.assertEqual(adapter.control_coverage(), dict(eligibleOwned=2, individualControl=0,
            outsideIndividualControl={'native group scope': 1, 'native group movement mode': 1}))

    def test_sideways_loop_fails_without_rejecting_initial_detour(self):
        from tactical_policy import Intent
        adapter = NativeAdapter(Api(), Evidence())
        snapshot = adapter.snapshot(native())
        identity = snapshot.units[0].identity
        intent = Intent(identity, 1, 1, 'move', 'objective', 45., destination=(29., 0.))
        for tick in (1000, 7000, 13000, 19000, 25000):
            raw = native(tick)
            raw['units'][0]['position'][1] = 40. if tick in (7000, 19000) else 0.
            snapshot = adapter.snapshot(raw)
            completed = adapter.completions(snapshot, {identity: intent})
            self.assertEqual(completed, [(intent, 'failed')] if tick == 25000 else [])
        self.assertEqual(adapter.evidence.records[-1]['reason'], 'no endpoint progress')

    def test_native_attack_completion_requires_this_orders_attributed_shot(self):
        from tactical_policy import Identity, Intent
        raw = native(2000)
        adapter = NativeAdapter(Api(), Evidence())
        snapshot = adapter.snapshot(raw)
        identity = snapshot.units[0].identity
        intent = Intent(identity, 1, 1, 'attack', 'visible target', 22.,
                        target=Identity('match', 'enemy', 1), submit_before=2.75)
        self.assertEqual(adapter.completions(snapshot, {identity: intent}), [])
        adapter.last_shots[identity] = 1900
        self.assertEqual(adapter.completions(snapshot, {identity: intent}), [])
        adapter.last_shots[identity] = 2000
        self.assertEqual(adapter.completions(snapshot, {identity: intent}), [(intent, 'completed')])

    def test_cover_entry_stall_does_not_claim_native_occupation(self):
        from tactical_policy import Intent
        adapter = NativeAdapter(Api(), Evidence())
        snapshot = adapter.snapshot(native())
        identity = snapshot.units[0].identity
        intent = Intent(identity, 1, 1, 'cover', 'advance via cover', 40., destination=(10., 0.), site='wall')
        self.assertEqual(adapter.completions(snapshot, {identity: intent}), [])
        later = adapter.snapshot(native(13000))
        self.assertEqual(adapter.completions(later, {identity: intent}), [(intent, 'failed')])

    def test_covering_observation_requires_own_sighting_and_loaded_weapon_work(self):
        for readiness, visible, expected in (('ready', True, True), ('reloading', True, False),
                                            ('unknown', True, False), ('ready', False, False)):
            raw = with_contact()
            raw['capabilities'].update(ammoLoading=True, weaponReadiness=True)
            raw['units'][0]['ammunition'] = dict(simulationTicks=2000, ammoCount=8, weaponModel='bar',
                nativeLoading=readiness == 'reloading', fireState=dict(nativeFirePredicate=readiness == 'ready',
                placementStateRaw=3, readinessCandidate=readiness == 'ready'))
            raw['perception'][0]['records'][0]['visible'] = visible
            self.assertEqual(NativeAdapter(Api(), Evidence()).snapshot(raw).units[0].covering, expected)

    def test_stranded_leader_joins_existing_member_move_with_cooldown(self):
        from tactical_policy import Policy
        for variation in ('follow', 'disabled', 'reclaimed', 'direct', 'cover', 'reloading', 'other_squad', 'ahead', 'native_mode', 'native_stance'):
            raw = native()
            raw['capabilities']['leaderFollow'] = variation != 'disabled'
            leader = dict(copy.deepcopy(raw['units'][0]), id='17', revision=0, squadLeader=True,
                individualOrder=False, enrolled=False, coverState=0, position=[-1000., 0., 0.])
            raw['units'].append(leader)
            if variation == 'native_mode': leader['movementBits'] = 8192
            if variation == 'native_stance': leader['stance'] = 3
            if variation == 'reclaimed': leader['revision'] = 1
            if variation == 'direct': leader['controlLockRaw'] = 1
            if variation == 'cover': leader['coverState'] = 2
            if variation == 'reloading': leader['ammunition'] = dict(nativeLoading=True)
            if variation == 'other_squad': leader['squadMembers'] = ['17', '19']
            if variation == 'ahead': leader['position'] = [600., 0., 0.]
            api = Api(); adapter = NativeAdapter(api, Evidence())
            snapshot = adapter.snapshot(raw)
            order, = Policy().step(snapshot)
            self.assertEqual(adapter.submit(order), 'accepted')
            self.assertEqual('followLeader' in api.requests[-1], variation == 'follow')
            if variation == 'follow':
                self.assertEqual(api.requests[-1]['followLeader'], dict(id='17', incarnation=1, revision=0))
                self.assertEqual(api.requests[-1]['destination'][:2], [v * 20 for v in order.destination])
                adapter.submit(order)
                self.assertNotIn('followLeader', api.requests[-1])

    def test_native_cover_selection_submission_and_observed_occupation(self):
        from tactical_policy import Policy
        class CoverApi(Api):
            def trialstance(self, request):
                self.queries.append(request)
                common = dict(status='queried', generation='match', simulationTicks=1100,
                    observerIdentity=dict(id='18', incarnation=1, owner='2'))
                if request['action'] == 'cover_scored_query':
                    return dict(common, requestVectorReleased=True, ranking='native-weighted-score-descending',
                        candidates=[dict(position=[600., 0.], sourceIdentity=dict(generation='match', entityId=71, incarnation=1),
                            nativeAssessment=dict(weightedScore=4.))])
                return dict(common, vectorReleased=True, reachesRequestedPoint=True, nativeSucceeded=True,
                    partial=False, destination=[600., 0.], endpoint=[600., 0.], origin=[0., 0.], startpoint=[0., 0.])
        api = CoverApi()
        adapter = NativeAdapter(api, Evidence())
        raw = native()
        raw['capabilities']['nativeCover'] = True
        raw['objectives'][0]['position'] = [1000., 0., 0.]
        initial = copy.deepcopy(raw)
        snapshot = adapter.snapshot(raw)
        policy = Policy()
        policy.step(snapshot)
        adapter.prepare_cover(snapshot, policy)
        adapter.prepare_cover(snapshot, policy)
        self.assertEqual(len(api.queries), 2)  # Global probe cadence applies.
        raw['simulationTicks'] = 1200
        snapshot = adapter.snapshot(raw)
        self.assertEqual(len(snapshot.covers), 1)
        self.assertIsNone(snapshot.covers[0].protection)
        self.assertIsNone(snapshot.covers[0].firing_access)
        order, = Policy().step(snapshot)
        self.assertEqual(order.action, 'cover')
        self.assertEqual(adapter.submit(order), 'accepted')
        self.assertEqual(api.requests[-1]['coverSource']['entityId'], 71)
        raw['units'][0].update(position=[600., 0., 10.], coverState=0)
        self.assertEqual(adapter.completions(adapter.snapshot(raw), {order.identity: order}), [])
        raw['units'][0]['coverState'] = 1
        self.assertEqual(adapter.completions(adapter.snapshot(raw), {order.identity: order}), [(order, 'completed')])
        raw['units'][0]['revision'] += 1
        self.assertEqual(adapter.snapshot(raw).covers, ())
        self.assertEqual(adapter.submit(order), 'cancelled')
        for variation in ('blocked', 'expired', 'wrong_owner', 'unreleased', 'bad_endpoint'):
            api = CoverApi()
            original = api.trialstance
            def probe(request):
                reply = original(request)
                if variation == 'expired': reply['simulationTicks'] = 1800
                if variation == 'wrong_owner': reply['observerIdentity']['owner'] = 'foreign'
                if variation == 'unreleased': reply['requestVectorReleased'] = False
                if request['action'] == 'path_query':
                    if variation == 'blocked': reply['reachesRequestedPoint'] = False
                    if variation == 'bad_endpoint': reply['endpoint'] = [900., 0.]
                return reply
            api.trialstance = probe
            adapter = NativeAdapter(api, Evidence())
            snapshot = adapter.snapshot(copy.deepcopy(initial))
            policy = Policy(); policy.step(snapshot)
            if variation in ('wrong_owner', 'unreleased', 'bad_endpoint'):
                with self.assertRaises(RuntimeError): adapter.prepare_cover(snapshot, policy)
            else:
                adapter.prepare_cover(snapshot, policy)
            self.assertFalse(adapter.cover_candidates)

    def test_cover_occupation_requires_supported_native_state(self):
        for state, expected in ((None, None), (0, False), (1, True), (2, True), (3, None)):
            raw = native()
            raw['units'][0]['coverState'] = state
            self.assertIs(NativeAdapter(Api(), Evidence()).snapshot(raw).units[0].in_cover, expected)
        for state in (True, -1, 1.5, '1', 0x100000000):
            raw = native()
            raw['units'][0]['coverState'] = state
            with self.assertRaisesRegex(ValueError, 'cover state'):
                NativeAdapter(Api(), Evidence()).snapshot(raw)

    def test_single_survivor_leader_requires_verified_individual_scope(self):
        from types import SimpleNamespace
        adapter=NativeAdapter(None,SimpleNamespace(write=lambda r:None));raw=native()
        raw['units'][0].update(squadLeader=True,squadMembers=['18'])
        self.assertFalse(adapter.snapshot(raw).units[0].move_at_will)
        raw['units'][0]['individualOrder']=True
        self.assertTrue(adapter.snapshot(raw).units[0].move_at_will)
        raw['units'][0]['individualOrder']=False
        self.assertFalse(adapter.snapshot(raw).units[0].move_at_will)

    def test_weapon_model_observation_validation_and_unknown_fallback(self):
        from types import SimpleNamespace
        adapter=NativeAdapter(None,SimpleNamespace(write=lambda r:None));raw=native()
        raw['capabilities']['ammoLoading']=True
        ammo=dict(simulationTicks=1000,ammoCount=20,nativeLoading=False)
        raw['units'][0]['ammunition']=ammo
        self.assertIsNone(adapter.snapshot(raw).units[0].weapon_model)
        ammo['weaponModel']='thompson'
        self.assertEqual(adapter.snapshot(raw).units[0].weapon_model,'thompson')
        for invalid in ('',4,{},'x'*129):
            ammo['weaponModel']=invalid
            with self.assertRaisesRegex(ValueError,'weapon model'):adapter.snapshot(raw)

    def test_vehicle_threat_uses_visible_sensor_data_only(self):
        from types import SimpleNamespace
        adapter=NativeAdapter(None,SimpleNamespace(write=lambda r:None));raw=with_contact()
        record=raw['perception'][0]['records'][0];record['identity']['kind']='vehicle'
        contact,=adapter.snapshot(raw).contacts
        self.assertEqual((contact.kind,contact.strength,contact.position),('vehicle',4.,(30.,0.)))
        record.update(visible=False,visualObservedPosition=None)
        self.assertFalse(adapter.snapshot(raw).contacts)
        record['identity']['kind']='unsupported'
        with self.assertRaisesRegex(ValueError,'contact kind'):adapter.snapshot(raw)

    def test_capture_radius_conversion_and_validation(self):
        from types import SimpleNamespace
        adapter=NativeAdapter(None,SimpleNamespace(write=lambda r:None))
        raw=native();raw['objectives'][0]['captureRadius']=600.
        self.assertEqual(adapter.snapshot(raw).objectives[0].capture_radius,30.)
        for radius in (0, -1, True, float('nan')):
            raw['objectives'][0]['captureRadius']=radius
            with self.assertRaisesRegex(ValueError,'capture radius'):adapter.snapshot(raw)

    def test_compact_perception_preserves_observations_and_rejects_bad_encoding(self):
        raw=with_contact()
        original=NativeAdapter(Api(),Evidence()).snapshot(raw)
        fields=('identity','visible','enemy','nativeDeadPredicate','nativeOwnerRelation',
                'visualObservedPosition','visualObservedAtTicks','positionUpdateTicks')
        raw['perceptionEncoding']='tuple-v1'
        for report in raw['perception']:
            report['records']=[[record.get(k) for k in fields] for record in report['records']]
        compact=NativeAdapter(Api(),Evidence()).snapshot(raw)
        self.assertEqual(original,compact)
        raw['perception'][0]['records'][0].pop()
        with self.assertRaisesRegex(ValueError,'compact'):NativeAdapter(Api(),Evidence()).snapshot(raw)
        raw['perceptionEncoding']='other'
        with self.assertRaisesRegex(ValueError,'encoding'):NativeAdapter(Api(),Evidence()).snapshot(raw)

    def test_unmapped_stance_quarantines_one_unit_without_inventing_a_death(self):
        raw=native();second=copy.deepcopy(raw['units'][0]);second['id']='19'
        raw['units'].append(second)
        adapter=NativeAdapter(Api(),Evidence())
        original=adapter.snapshot(raw)
        raw['units'][0]['stance']=3
        unavailable=adapter.snapshot(raw)
        self.assertEqual(len(unavailable.units),1)
        self.assertEqual(unavailable.units[0].identity.unit,'19')
        self.assertEqual(unavailable.events,())
        raw['units'][0]['stance']=2
        restored=adapter.snapshot(raw)
        self.assertEqual(restored.units[0].identity,original.units[0].identity)
        self.assertEqual(restored.units[0].stance,'prone')
        for invalid in (-1,256,True):
            raw['units'][0]['stance']=invalid
            with self.assertRaisesRegex(ValueError,'stance/position'):adapter.snapshot(raw)

    def test_withdrawal_requires_current_complete_native_path_before_move(self):
        from dataclasses import replace
        from tactical_policy import Policy
        from itertools import product
        for reason, variation in product(('withdraw', 'friendly support', 'AT firing reposition', 'supported advance'), ('valid','no_capability','unreachable','partial','endpoint','identity','expired','unknown')):
            api, _, adapter, _ = self.setup_runtime()
            raw = native()
            raw['capabilities']['pathQuery'] = variation != 'no_capability'
            snapshot = adapter.snapshot(raw)
            intent = replace(Policy().step(snapshot)[0], reason=reason)
            destination = [v * 20 for v in intent.destination]
            api.preflight = dict(status='queried',generation='match',simulationTicks=1000,
                observerIdentity=dict(id='18',incarnation=1,owner='2'),vectorReleased=True,
                reachesRequestedPoint=True,nativeSucceeded=True,partial=False,
                destination=destination,endpoint=destination[:],origin=[0.,0.],startpoint=[0.,0.])
            if variation=='unreachable':api.preflight['reachesRequestedPoint']=False
            if variation=='partial':api.preflight['partial']=True
            if variation=='endpoint':api.preflight['endpoint'][0]+=20
            if variation=='identity':api.preflight['observerIdentity']['id']='99'
            if variation=='expired':api.preflight['simulationTicks']=5000
            if variation=='unknown':api.preflight=dict(error='reply lost')
            if variation in ('partial','endpoint','identity'):
                with self.assertRaises(RuntimeError):adapter.submit(intent)
            else:
                self.assertEqual(adapter.submit(intent),{'valid':'accepted','unreachable':'rejected',
                    'unknown':'uncertain'}.get(variation,'cancelled'))
            self.assertEqual(len(api.requests),1 if variation=='valid' else 0)
            if variation=='valid':
                self.assertEqual(api.queries[0]['action'],'path_query')
                self.assertEqual(api.queries[0]['sequence'],1)
                self.assertEqual(api.requests[0]['sequence'],2)

    def test_recent_attributed_shot_defers_movement_without_claiming_ready(self):
        api, _, adapter, runtime = self.setup_runtime()
        raw = native()
        raw['capabilities']['shotEvents'] = True
        raw['events'] = [dict(kind='bullet_created', id='18', incarnation=1, simulationTicks=1000)]
        snapshot = adapter.snapshot(raw)
        self.assertEqual(snapshot.units[0].readiness, 'firing')
        self.assertEqual(runtime.step(snapshot), [])
        raw.update(simulationTicks=1800, events=[])
        self.assertEqual(adapter.snapshot(raw).units[0].readiness, 'firing')
        raw['simulationTicks'] = 2001
        snapshot = adapter.snapshot(raw)
        self.assertEqual(snapshot.units[0].readiness, 'unknown')
        self.assertEqual(len(runtime.step(snapshot)), 1)
        self.assertFalse(adapter.last_shots)

    def test_shot_guard_requires_capability_current_identity_and_valid_time(self):
        for variation in ('no_capability', 'reused', 'foreign', 'future', 'boolean', 'reloading'):
            _, _, adapter, _ = self.setup_runtime()
            raw = native()
            raw['capabilities'].update(shotEvents=variation != 'no_capability', ammoLoading=True)
            raw['units'][0]['ammunition'] = dict(simulationTicks=1000, ammoCount=8,
                nativeLoading=variation == 'reloading')
            raw['events'] = [dict(kind='bullet_created', id='other' if variation == 'foreign' else '18',
                incarnation=2 if variation == 'reused' else 1,
                simulationTicks=1001 if variation == 'future' else True if variation == 'boolean' else 1000)]
            if variation in {'future', 'boolean'}:
                with self.assertRaisesRegex(ValueError, 'shot timestamp'):
                    adapter.snapshot(raw)
            else:
                self.assertEqual(adapter.snapshot(raw).units[0].readiness,
                    'reloading' if variation == 'reloading' else 'unknown')

    def test_native_loading_preserves_reload_without_claiming_ready(self):
        api, _, adapter, runtime = self.setup_runtime()
        raw = native()
        raw['capabilities']['ammoLoading'] = True
        raw['units'][0]['ammunition'] = dict(simulationTicks=1000, ammoCount=0, nativeLoading=True)
        snapshot = adapter.snapshot(raw)
        self.assertEqual(snapshot.units[0].readiness, 'reloading')
        self.assertEqual(snapshot.units[0].ammo, 0)
        self.assertEqual(runtime.step(snapshot), [])
        self.assertEqual(api.requests, [])
        raw['simulationTicks'] = 7000
        raw['units'][0]['ammunition'] = dict(simulationTicks=7000, ammoCount=8, nativeLoading=False)
        snapshot = adapter.snapshot(raw)
        self.assertEqual(snapshot.units[0].readiness, 'unknown')
        self.assertEqual(snapshot.units[0].ammo, 8)
        self.assertEqual(len(runtime.step(snapshot)), 1)

    def test_ammunition_requires_capability_and_current_bounded_fields(self):
        _, _, adapter, _ = self.setup_runtime()
        raw = native()
        raw['units'][0]['ammunition'] = dict(simulationTicks=999, ammoCount=8, nativeLoading=True)
        self.assertIsNone(adapter.snapshot(raw).units[0].ammo)
        raw['capabilities']['ammoLoading'] = True
        for change in ({'simulationTicks': 999}, {'ammoCount': True}, {'ammoCount': 10001}, {'nativeLoading': 1}):
            raw['units'][0]['ammunition'] = dict(simulationTicks=1000, ammoCount=8, nativeLoading=False)
            raw['units'][0]['ammunition'].update(change)
            with self.assertRaisesRegex(ValueError, 'ammunition'):
                adapter.snapshot(raw)
        raw['units'][0]['ammunition'] = None
        self.assertEqual(adapter.snapshot(raw).units[0].readiness, 'unknown')

    def test_rifle_readiness_is_gated_and_preserves_loading_and_firing(self):
        for mode in ('ready', 'alternate', 'preparing', 'loading', 'firing', 'unsupported', 'disabled', 'corrupt'):
            with self.subTest(mode=mode):
                _, _, adapter, _ = self.setup_runtime()
                raw = native()
                raw['capabilities'].update(ammoLoading=True, weaponReadiness=mode != 'disabled', shotEvents=True)
                fire = dict(nativeFirePredicate=mode != 'loading', placementStateRaw=4 if mode == 'alternate' else
                            5 if mode == 'preparing' else 3, readinessCandidate=mode not in {'loading', 'preparing'})
                if mode == 'corrupt': fire['readinessCandidate'] = False
                raw['units'][0]['ammunition'] = dict(simulationTicks=1000, ammoCount=8,
                    nativeLoading=mode == 'loading', fireState=None if mode == 'unsupported' else fire)
                if mode == 'firing':
                    raw['events'] = [dict(key=1, kind='bullet_created', id='18', incarnation=1, simulationTicks=1000)]
                if mode == 'corrupt':
                    with self.assertRaisesRegex(ValueError, 'firing readiness'):
                        adapter.snapshot(raw)
                else:
                    expected = ('ready' if mode in {'ready', 'alternate'} else 'reloading' if mode == 'loading' else
                                'firing' if mode == 'firing' else 'unknown')
                    self.assertEqual(adapter.snapshot(raw).units[0].readiness, expected)

    def test_attack_uses_fresh_preflight_and_separate_completion(self):
        api, _, adapter, runtime = self.setup_runtime()
        raw = with_contact()
        raw['capabilities']['attack'] = True
        snapshot = adapter.snapshot(raw)
        self.assertEqual(snapshot.contacts[0].visible_to, frozenset({snapshot.units[0].identity}))
        intent, = runtime.step(snapshot)
        self.assertEqual(intent.action, 'attack')
        self.assertEqual(api.queries[0]['action'], 'attack_query')
        self.assertEqual(api.queries[0]['sequence'], 1)
        request, = api.requests
        self.assertEqual(request['sequence'], 2)
        self.assertEqual(request['target'], dict(generation='match', id='19', incarnation=1, owner='4', entityId=1234))
        self.assertTrue(request['requireEnrolled'])
        self.assertEqual(request['submitBeforeTicks'], intent.submit_before * 1000.)
        self.assertEqual(adapter.completions(snapshot, runtime.inflight), [])

    def test_loaded_bazooka_can_submit_vehicle_attack_with_fresh_preflight(self):
        api,_,adapter,runtime=self.setup_runtime();raw=with_contact()
        raw['capabilities'].update(attack=True,ammoLoading=True)
        raw['units'][0]['ammunition']=dict(simulationTicks=2000,weaponModel='bazooka',ammoCount=1,nativeLoading=False)
        record=raw['perception'][0]['records'][0];record['identity']['kind']='vehicle';record['visualObservedPosition']=[1600.,0.,0.]
        order,=runtime.step(adapter.snapshot(raw))
        self.assertEqual(order.action,'attack');self.assertEqual(api.requests[0]['target']['id'],'19')

    def test_loaded_heat_rifle_grenade_identity_reaches_native_preflight(self):
        api,_,adapter,runtime=self.setup_runtime();raw=with_contact()
        raw['capabilities'].update(attack=True,ammoLoading=True)
        raw['units'][0]['ammunition']=dict(simulationTicks=2000,weaponModel='garand_grenade',
            projectileModel='garand_heat_ammo',ammoCount=1,nativeLoading=False)
        raw['perception'][0]['records'][0]['identity']['kind']='vehicle'
        raw['perception'][0]['records'][0]['visualObservedPosition']=[1600.,0.,0.]
        snapshot=adapter.snapshot(raw)
        self.assertEqual(snapshot.units[0].projectile_model,'garand_heat_ammo')
        order,=runtime.step(snapshot)
        self.assertEqual(order.action,'attack')
        raw['units'][0]['ammunition']['projectileModel']='em_mk3_ammo'
        adapter.snapshot(raw)
        self.assertEqual(adapter.submit(order),'cancelled')

    def test_contact_observer_scope_expires_without_erasing_other_observers(self):
        api, _, adapter, runtime = self.setup_runtime()
        raw = with_contact()
        raw['capabilities']['attack'] = True
        raw['units'].append(dict(raw['units'][0], id='20'))
        second = copy.deepcopy(raw['perception'][0])
        second['observerIdentity']['id'] = '20'
        raw['perception'].append(second)
        snapshot = adapter.snapshot(raw)
        self.assertEqual({i.unit for i in snapshot.contacts[0].visible_to}, {'18', '20'})
        pending = next(i for i in runtime.policy.step(snapshot) if i.identity.unit == '18')
        raw['perception'] = [second]
        snapshot = adapter.snapshot(raw)
        self.assertEqual({i.unit for i in snapshot.contacts[0].visible_to}, {'20'})
        self.assertEqual(adapter.submit(pending), 'cancelled')
        self.assertFalse(api.queries)
        self.assertFalse(api.requests)
        raw['units'][1]['incarnation'] = 2
        self.assertEqual(adapter.snapshot(raw).contacts, ())

    def test_attack_lost_target_or_expired_preflight_cancels_without_order(self):
        for variation in ('lost', 'reuse', 'expired'):
            with self.subTest(variation=variation):
                api, _, adapter, runtime = self.setup_runtime()
                if variation == 'lost': api.preflight['targets'] = []
                elif variation == 'reuse': api.preflight['targets'][0]['identity']['incarnation'] = 2
                else: api.preflight['simulationTicks'] = 2750
                raw = with_contact()
                raw['capabilities']['attack'] = True
                runtime.step(adapter.snapshot(raw))
                self.assertFalse(api.requests)
                self.assertFalse(runtime.inflight)
                self.assertFalse(next(iter(runtime.policy.members.values())).failed)

    def test_attack_preflight_unknown_reply_stops_without_submission(self):
        api, _, adapter, runtime = self.setup_runtime()
        api.preflight = dict(status='unknown')
        raw = with_contact()
        raw['capabilities']['attack'] = True
        with self.assertRaisesRegex(RuntimeError, 'Uncertain submission'):
            runtime.step(adapter.snapshot(raw))
        self.assertTrue(runtime.stopped)
        self.assertFalse(api.requests)

    def test_native_contact_cadence_and_hidden_position_do_not_refresh_memory(self):
        _, _, adapter, runtime = self.setup_runtime()
        raw = with_contact()
        snapshot = adapter.snapshot(raw)
        contact, = snapshot.contacts
        self.assertEqual(contact.position, (30., 0.))
        self.assertEqual(contact.fresh_for, 2.)
        runtime.step(snapshot)
        self.assertIn(contact.identity, runtime.policy.memory)
        raw = with_contact(2200)
        raw['perception'][0]['records'][0]['visible'] = False
        hidden = adapter.snapshot(raw)
        self.assertEqual(hidden.contacts, ())
        runtime.step(hidden)
        self.assertEqual(runtime.policy.memory[contact.identity].contact.position, (30., 0.))
        self.assertEqual(runtime.policy.memory[contact.identity].velocity, (0., 0.))

    def test_native_contact_reuse_and_conflicting_observations(self):
        _, _, adapter, runtime = self.setup_runtime()
        raw = with_contact()
        initial = adapter.snapshot(raw)
        runtime.step(initial)
        self.assertIn(initial.contacts[0].identity, runtime.policy.memory)
        raw['simulationTicks'] += 200
        newer = copy.deepcopy(raw['perception'][0]['records'][0])
        newer['identity']['incarnation'] = 2
        newer['visible'] = False
        raw['perception'][0]['records'].append(newer)
        replacement = adapter.snapshot(raw)
        self.assertEqual(replacement.contacts, ())
        self.assertEqual(replacement.contact_identities[0].incarnation, 2)
        runtime.step(replacement)
        self.assertNotIn(initial.contacts[0].identity, runtime.policy.memory)
        self.assertFalse(runtime.policy.casualties)
        raw = with_contact()
        conflict = copy.deepcopy(raw['perception'][0]['records'][0])
        conflict['visualObservedPosition'][0] += 20.
        raw['perception'][0]['records'].append(conflict)
        self.assertEqual(adapter.snapshot(raw).contacts, ())
        raw['perception'][0]['records'].pop()
        self.assertEqual(adapter.snapshot(raw).contacts, ())  # No resurrection of the ambiguous tick.
        refreshed = with_contact()
        refreshed['perception'][0]['visualUpdateTicks'] = 1200
        refreshed['perception'][0]['records'][0].update(visualObservedAtTicks=1200, positionUpdateTicks=1200)
        self.assertEqual(len(adapter.snapshot(refreshed).contacts), 1)

    def test_same_tick_position_drift_is_quarantined_across_snapshots(self):
        _, _, adapter, _ = self.setup_runtime()
        raw = with_contact()
        self.assertEqual(len(adapter.snapshot(raw).contacts), 1)
        shifted = copy.deepcopy(raw)
        shifted['perception'][0]['records'][0]['visualObservedPosition'][0] += .8
        self.assertEqual(adapter.snapshot(shifted).contacts, ())
        self.assertEqual(adapter.snapshot(raw).contacts, ())
        # A relation conflict is a different contract failure, not positional jitter.
        _, _, adapter, _ = self.setup_runtime()
        opposite = copy.deepcopy(raw['perception'][0]['records'][0])
        opposite['enemy'] = False
        raw['perception'][0]['records'].append(opposite)
        with self.assertRaisesRegex(ValueError, 'relationships'):
            adapter.snapshot(raw)

    def test_native_contact_gates_age_and_observer_authority(self):
        _, _, adapter, _ = self.setup_runtime()
        raw = with_contact(2901)
        self.assertEqual(adapter.snapshot(raw).contacts, ())
        raw = with_contact()
        raw['capabilities']['death'] = False
        self.assertEqual(adapter.snapshot(raw).contacts, ())
        raw = with_contact()
        raw['perception'][0]['observerIdentity']['owner'] = '3'
        with self.assertRaisesRegex(ValueError, 'Foreign perception'):
            adapter.snapshot(raw)

    def test_newly_observed_friendly_contact_clears_enemy_memory(self):
        _, _, adapter, runtime = self.setup_runtime()
        snapshot = adapter.snapshot(with_contact())
        runtime.step(snapshot)
        raw = with_contact(2200)
        raw['perception'][0]['records'][0]['enemy'] = False
        runtime.step(adapter.snapshot(raw))
        self.assertNotIn(snapshot.contacts[0].identity, runtime.policy.memory)

    def test_visible_death_clears_memory_with_unknown_native_relation(self):
        for visible, dead, stamp, cleared in ((True, True, 2100, True),
                (False, True, 2100, False), (True, False, 2100, False),
                (True, True, 100, False)):
            with self.subTest(visible=visible, dead=dead, stamp=stamp):
                _, _, adapter, runtime = self.setup_runtime()
                initial = adapter.snapshot(with_contact())
                runtime.step(initial)
                raw = with_contact(2200)
                report = raw['perception'][0]
                report['visualUpdateTicks'] = stamp
                report['records'][0].update(enemy=None, visible=visible,
                    nativeDeadPredicate=dead, visualObservedAtTicks=stamp,
                    positionUpdateTicks=stamp)
                snapshot = adapter.snapshot(raw)
                if cleared:
                    self.assertIsNone(snapshot.contacts[0].enemy)
                runtime.step(snapshot)
                self.assertEqual(initial.contacts[0].identity not in runtime.policy.memory, cleared)

    def test_delayed_native_death_keeps_its_simulation_timestamp(self):
        _, _, adapter, runtime = self.setup_runtime()
        raw = native(90000)
        raw['events'] = [dict(key=21, kind='owned_death', id='19', incarnation=1,
                             simulationTicks=1100, position=[600., 0., 0.])]
        snapshot = adapter.snapshot(raw)
        self.assertEqual(snapshot.events[0].observed_at, 1.1)
        runtime.step(snapshot)
        self.assertEqual(runtime.policy.casualties[(1, 0)], (1., 1.1))

    def setup_runtime(self, reply=None):
        api, evidence = Api(reply), Evidence()
        adapter = NativeAdapter(api, evidence)
        return api, evidence, adapter, Runtime(adapter.submit, evidence)

    def test_move_conversion_revision_deadline_and_observed_completion(self):
        api, _, adapter, runtime = self.setup_runtime()
        snapshot = adapter.snapshot(native())
        intent, = runtime.step(snapshot)
        request, = api.requests
        self.assertEqual(request['destination'], [580., 0., 10.])
        self.assertEqual(request['unitRevision'], 7)
        self.assertNotEqual(request['unitRevision'], intent.revision)
        self.assertEqual(request['submitBeforeTicks'], intent.submit_before * 1000.)
        self.assertEqual(adapter.completions(snapshot, runtime.inflight), [])
        raw = native(1200)
        raw['units'][0]['position'] = [590., 0., 10.]
        arrived = adapter.snapshot(raw)
        self.assertEqual(adapter.completions(arrived, runtime.inflight), [(intent, 'completed')])
        runtime.step(arrived, adapter.completions(arrived, runtime.inflight))
        self.assertEqual(runtime.inflight, {})

    def test_stationary_move_fails_early_but_detours_and_combat_waits_do_not(self):
        from dataclasses import replace
        for behavior in ('stalled', 'detour', 'reloading', 'paused'):
            _, evidence, adapter, runtime = self.setup_runtime()
            initial = adapter.snapshot(native())
            intent, = runtime.step(initial)
            adapter.completions(initial, runtime.inflight)
            for tick in (7000, 13000):
                raw = native(tick)
                if behavior == 'detour':
                    raw['units'][0]['position'][1] = tick / 100.
                snapshot = adapter.snapshot(raw)
                if behavior == 'reloading':
                    snapshot = replace(snapshot, units=tuple(replace(u, readiness='reloading') for u in snapshot.units))
                if behavior == 'paused':
                    snapshot = replace(snapshot, paused=True)
                result = adapter.completions(snapshot, runtime.inflight)
            self.assertEqual(result, [(intent, 'failed')] if behavior == 'stalled' else [])
            self.assertEqual(any('movementStalled' in r for r in evidence.records), behavior == 'stalled')
            adapter.completions(snapshot, {})
            self.assertEqual(adapter.move_progress, {})

    def test_reenable_cancels_old_action_before_accepting_arrival(self):
        _, evidence, adapter, runtime = self.setup_runtime()
        intent, = runtime.step(adapter.snapshot(native()))
        raw = native(1200)
        raw['units'][0].update(revision=8, position=[600., 0., 10.])
        snapshot = adapter.snapshot(raw)
        runtime.step(snapshot, adapter.completions(snapshot, runtime.inflight))
        self.assertFalse(any('terminal' in r and r.get('status') == 'completed' for r in evidence.records))
        self.assertTrue(any('ignoredCompletion' in r for r in evidence.records))
        self.assertNotEqual(runtime.inflight.get(intent.identity), intent)

    def test_returned_death_event_reaches_casualty_memory_once(self):
        event = dict(key=21, kind='owned_death', id='19', incarnation=1,
                     simulationTicks=1100, position=[600., 0., 0.])
        _, _, adapter, runtime = self.setup_runtime(dict(status='serialized', observedEvents=[event]))
        runtime.step(adapter.snapshot(native()))
        raw = native(1200)
        raw['events'] = [event]
        runtime.step(adapter.snapshot(raw))
        self.assertEqual(runtime.policy.casualties[(1, 0)][0], 1.)
        runtime.step(adapter.snapshot(native(1400)))
        self.assertEqual(runtime.policy.casualties[(1, 0)][0], 1.)

    def test_known_admission_refusal_does_not_become_failed_route(self):
        _, _, adapter, runtime = self.setup_runtime(dict(rejected=True, error='stale admission'))
        snapshot = adapter.snapshot(native())
        self.assertEqual(runtime.step(snapshot), [])
        member, = runtime.policy.members.values()
        self.assertEqual(member.failed, {})
        self.assertIsNone(member.action)

    def test_unknown_features_pause_and_inactive_match(self):
        api, _, adapter, runtime = self.setup_runtime()
        raw = native()
        raw['paused'] = True
        raw['capabilities'].update(attack=True, build=True, cover=True, objectives=False, death=False)
        snapshot = adapter.snapshot(raw)
        self.assertEqual(snapshot.objectives, ())
        self.assertEqual(snapshot.capabilities, frozenset({'move', 'stance'}))
        self.assertEqual(runtime.step(snapshot), [])
        self.assertEqual(api.requests, [])
        raw['playing'] = False
        with self.assertRaisesRegex(RuntimeError, 'not active'):
            adapter.snapshot(raw)

    def test_foreign_units_and_late_completion_are_rejected(self):
        _, _, adapter, runtime = self.setup_runtime()
        intent, = runtime.step(adapter.snapshot(native()))
        raw = native(int(intent.expires * 1000.) + 1)
        raw['units'][0]['position'] = [600., 0., 10.]
        snapshot = adapter.snapshot(raw)
        self.assertEqual(adapter.completions(snapshot, runtime.inflight), [])
        foreign = copy.deepcopy(raw)
        foreign['units'][0]['owner'] = '3'
        with self.assertRaisesRegex(ValueError, 'Foreign'):
            adapter.snapshot(foreign)


if __name__ == '__main__':
    unittest.main()
