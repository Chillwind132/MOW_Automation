import _test_paths
from dataclasses import replace
import unittest
from math import dist

from tactical_controller import Runtime
from tactical_operations import ForcePlanner, TacticalMetrics
from tactical_policy import Contact, Cover, Event, Policy
from test_tactical_policy import I, J, E, U, O, CAPS, scene
from test_tactical_adapter import Evidence


class OperationsTests(unittest.TestCase):
    def test_continuous_emergencies_do_not_starve_waiting_reinforcement(self):
        urgent = tuple(replace(U, identity=replace(I, unit=str(n)), squad=str(n), urgent_danger=True)
                       for n in range(4))
        reinforcement = replace(U, identity=J, squad='reinforcement', position=(-100., 0.))
        # Give the reinforcement an identity distinct from every emergency.
        reinforcement = replace(reinforcement, identity=replace(J, unit='reserve'))
        policy = Policy()
        policy.MAX_DECISIONS = 4
        first_service = None
        for stamp in range(13):
            orders = policy.step(scene(float(stamp), units=urgent + (reinforcement,)))
            if any(o.identity == reinforcement.identity for o in orders):
                first_service = stamp
                break
        self.assertIsNotNone(first_service)
        self.assertLessEqual(first_service, 7)

    def test_coverer_requires_current_personal_relevant_contact(self):
        support = replace(U, weapon_model='bar', covering=True, readiness='ready', ammo=20)
        mover = replace(U, identity=J)
        enemy = Contact(E, (190., 0.), 0., True, True, strength=.01, visible_to=frozenset({I}))
        for contacts in ((), (replace(enemy, observed_at=-2.),),
                         (replace(enemy, visible_to=frozenset({J})),),
                         (replace(enemy, position=(350., 0.)),)):
            policy = Policy()
            orders = policy.step(scene(units=(support, mover), contacts=contacts))
            self.assertEqual({o.identity for o in orders}, {I, J})
            self.assertEqual(policy.squads[U.squad].moving, set())

    def test_failed_at_attack_repositions_once_without_cancelling_approach(self):
        launcher = replace(U, weapon_model='bazooka', ammo=1, readiness='ready')
        vehicle = Contact(E, (70., 0.), 0., True, True, kind='vehicle', visible_to=frozenset({I}))
        policy = Policy()
        attack, = policy.step(scene(units=(launcher,), contacts=(vehicle,)))
        policy.acknowledge(attack, 'uncertain')
        move, = policy.step(scene(1., units=(launcher,), contacts=(replace(vehicle, observed_at=1.),)))
        self.assertEqual((move.action, move.reason), ('move', 'AT firing reposition'))
        self.assertLessEqual(dist(launcher.position, move.destination), 8.)
        self.assertEqual(policy.step(scene(2., units=(launcher,), contacts=(replace(vehicle, observed_at=2.),))), [])
        self.assertEqual(policy.members[I].action, move)
        policy.acknowledge(move, 'completed')
        after = replace(launcher, position=move.destination)
        attack, = policy.step(scene(11., units=(after,), contacts=(replace(vehicle, observed_at=11.),)))
        self.assertEqual(attack.action, 'attack')
        policy.acknowledge(attack, 'completed')
        self.assertEqual(policy.members[I].armor_failures, 0)
        self.assertEqual(policy.members[I].armor_repositions, 0)

    def test_at_reposition_preserves_reload_and_does_not_approach_nearby_infantry(self):
        launcher = replace(U, weapon_model='bazooka', ammo=1)
        vehicle = Contact(E, (70., 0.), 0., True, True, kind='vehicle')
        for reload in (False, True):
            policy = Policy()
            attack, = policy.step(scene(units=(launcher,), contacts=(vehicle,)))
            policy.acknowledge(attack, 'uncertain')
            threat = Contact(replace(E, unit='infantry'), (20., 0.), 1., True, True, strength=.01)
            unit = replace(launcher, readiness='reloading') if reload else launcher
            orders = policy.step(scene(1., units=(unit,), contacts=(replace(vehicle, observed_at=1.), threat)))
            self.assertFalse(any(o.reason == 'AT firing reposition' for o in orders))

    def test_defensive_cover_outside_capture_center_does_not_expire_as_shelter(self):
        owned = replace(O, position=(10., 0.), owner='local')
        cover = Cover('wall', (7., 0.), reachable=True, native_score=10., observer=I)
        policy = Policy()
        order, = policy.step(scene(objectives=(owned,), covers=(cover,), capabilities=CAPS | {'nativeCover'}))
        policy.acknowledge(order, 'completed')
        unit = replace(U, position=cover.position, in_cover=True)
        self.assertEqual(policy.step(scene(5., units=(unit,), objectives=(owned,), covers=(cover,),
                                           capabilities=CAPS | {'nativeCover'})), [])
        self.assertEqual(policy.members[I].wait_reason, 'defensive hold')

    def test_service_wait_does_not_count_time_spent_holding(self):
        runtime = Runtime(lambda _: 'accepted', Evidence())
        metrics = TacticalMetrics()
        snapshot = scene()
        runtime.step(snapshot)
        state = runtime.policy.members[I]
        state.wait_reason = 'holding objective'
        metrics.sample(snapshot, runtime, ())
        report = metrics.sample(replace(snapshot, time=100.), runtime, ())
        self.assertEqual(report['prolongedWaitingReasons'], {'holding objective': 1})
        state.wait_reason = 'awaiting service'
        report = metrics.sample(replace(snapshot, time=101.), runtime, ())
        self.assertEqual(report['serviceWaitMaxSeconds'], 0.)
        report = metrics.sample(replace(snapshot, time=104.), runtime, ())
        self.assertEqual(report['serviceWaitMaxSeconds'], 3.)

    def test_three_failed_routes_reassign_individual_without_moving_squad_goal(self):
        policy = Policy()
        alternative = replace(O, key='backup', position=(0., 200.))
        for stamp in (0., 11., 22.):
            order, = policy.step(scene(stamp, objectives=(O, alternative)))
            policy.acknowledge(order, 'failed')
        order, = policy.step(scene(33., objectives=(O, alternative)))
        self.assertEqual(policy.squads[U.squad].goal, O.key)
        self.assertEqual(policy.members[I].assignment, 'backup')
        self.assertGreater(order.destination[1], order.destination[0])

    def test_leader_follows_actual_subgroup_when_everyone_else_holds(self):
        leader = replace(U, squad_leader=True)
        peer = replace(U, identity=J, position=(0., 30.))
        policy = Policy()
        orders = policy.step(scene(units=(leader, peer)))
        order = next(o for o in orders if o.identity == I)
        self.assertGreater(order.destination[1], 20.)
        self.assertAlmostEqual(order.destination[0], 0.)

    def test_at_coordination_has_deadline_and_urgent_bypass(self):
        launcher = replace(U, weapon_model='bazooka', ammo=1, readiness='ready')
        peer = replace(launcher, identity=J, readiness='reloading', ammo=0)
        vehicle = Contact(E, (70., 0.), 0., True, True, kind='vehicle', visible_to=frozenset({I,J}))
        policy = Policy()
        self.assertFalse(policy.step(scene(units=(launcher, peer), contacts=(vehicle,))))
        self.assertEqual(policy.members[I].wait_reason, 'AT readiness window')
        orders = policy.step(scene(1.6, units=(launcher, peer), contacts=(replace(vehicle, observed_at=1.6),)))
        self.assertTrue(any(o.identity == I and o.action == 'attack' for o in orders))
        near = replace(vehicle, position=(30., 0.))
        self.assertTrue(any(o.identity == I and o.action == 'attack' for o in
                            Policy().step(scene(units=(launcher, peer), contacts=(near,)))))

    def test_attack_completion_precedes_empty_magazine_but_player_reclamation_wins(self):
        launcher = replace(U, weapon_model='bazooka', ammo=1)
        vehicle = Contact(E, (70., 0.), 0., True, True, kind='vehicle')
        for reclaimed in (False, True):
            evidence = Evidence()
            runtime = Runtime(lambda _: 'accepted', evidence)
            attack, = runtime.step(scene(units=(launcher,), contacts=(vehicle,)))
            events = (Event('manual', 'move', (I,)),) if reclaimed else ()
            runtime.step(scene(1., units=(replace(launcher, ammo=0),), events=events), [(attack, 'completed')])
            self.assertEqual(any('terminal' in r and r['status'] == 'completed' for r in evidence.records), not reclaimed)

    def test_empty_launcher_does_not_advance_into_enemy_objective(self):
        policy = Policy()
        unit = replace(U, weapon_model='bazooka', ammo=0)
        self.assertEqual(policy.step(scene(units=(unit,))), [])
        self.assertEqual(policy.members[I].wait_reason, 'AT ammunition unavailable')

    def test_occupied_defensive_cover_survives_small_score_improvement(self):
        owned = replace(O, position=(10., 0.), owner='local')
        first = Cover('a', (10., 0.), reachable=True, native_score=10., observer=I)
        policy = Policy()
        order, = policy.step(scene(objectives=(owned,), covers=(first,), capabilities=CAPS | {'nativeCover'}))
        policy.acknowledge(order, 'completed')
        unit = replace(U, position=first.position, in_cover=True)
        second = replace(first, key='b', position=(11., 0.), native_score=11.)
        orders = policy.step(scene(2., units=(unit,), objectives=(owned,), covers=(first, second), capabilities=CAPS | {'nativeCover'}))
        self.assertFalse(any(o.action == 'cover' for o in orders))

    def test_purchase_armor_memory_and_hysteresis_then_infantry_support(self):
        planner, policy = ForcePlanner(), Policy()
        vehicle = Contact(E, (70., 0.), 0., True, True, kind='vehicle')
        snapshot = scene(contacts=(vehicle,))
        policy.step(snapshot)
        self.assertEqual(planner.choose(snapshot, policy), 'anti_tank')
        self.assertEqual(planner.choose(scene(16.), policy), 'anti_tank')
        self.assertEqual(planner.choose(scene(32.), policy), 'rifle')

    def test_smg_shortage_does_not_starve_baseline_at_purchase(self):
        rifles = tuple(replace(U, identity=replace(I, unit=str(n)), position=O.position,
                               weapon_model='garand', ammo=8) for n in range(8))
        policy = Policy()
        snapshot = scene(units=rifles)
        policy.step(snapshot)
        planner = ForcePlanner()
        self.assertEqual(planner.choose(snapshot, policy), 'anti_tank')
        launcher = replace(U, identity=replace(I, unit='launcher'), position=O.position,
                           weapon_model='bazooka', ammo=1)
        later = scene(16., units=rifles + (launcher,))
        policy.step(later)
        self.assertEqual(planner.choose(later, policy), 'assault')

    def test_stranded_launchers_do_not_count_as_deployed_strength(self):
        vehicle = Contact(E, (70., 0.), 0., True, True, kind='vehicle')
        launchers = tuple(replace(U, identity=replace(I, unit=str(n)), weapon_model='bazooka', ammo=1,
                                  position=(60., 0.)) for n in range(1, 5))
        near = scene(units=launchers, contacts=(vehicle,))
        policy = Policy(); policy.step(near)
        planner = ForcePlanner()
        self.assertEqual(planner.choose(near, policy), 'rifle')
        far = replace(near, units=tuple(replace(u, position=(-300., 0.)) for u in launchers))
        self.assertEqual(ForcePlanner().choose(far, policy), 'anti_tank')

    def test_metrics_count_timeout_failures_and_do_not_infer_damage(self):
        evidence = Evidence()
        runtime = Runtime(lambda _: 'accepted', evidence)
        metrics = TacticalMetrics()
        initial = scene()
        order, = runtime.step(initial)
        metrics.sample(initial, runtime, ())
        later = scene(order.expires + .1)
        runtime.step(later)
        report = metrics.sample(later, runtime, ())
        self.assertEqual(report['departedInitialPosition'], 0)
        self.assertEqual(report['failures']['move:uncertain'], 1)
        self.assertIn('unavailable', report['damageConfirmation'])
        self.assertGreaterEqual(report['timing']['commands'], 1)

    def test_reserve_reinforces_threat_without_reassigning_every_squad(self):
        units = tuple(replace(U, identity=replace(I, unit=str(n)), squad=str(n), position=(float(n), 0.))
                      for n in range(4))
        owned = replace(O, position=(20., 0.), owner='local')
        policy = Policy()
        policy.step(scene(units=units, objectives=(owned,)))
        self.assertEqual(sum(s.reserve for s in policy.squads.values()), 1)
        original = policy.reserve_squad
        threat = Contact(E, (25., 0.), 3., True, True)
        policy.step(scene(3., units=units, objectives=(owned,), contacts=(threat,)))
        self.assertEqual(policy.reserve_squad, original)
        self.assertFalse(any(s.reserve for s in policy.squads.values()))
        self.assertEqual({s.goal for s in policy.squads.values()}, {owned.key})

    def test_supported_advance_is_short_and_preserves_observing_coverer(self):
        support = replace(U, weapon_model='bar', covering=True, readiness='ready', ammo=20)
        mover = replace(U, identity=J, weapon_model='thompson', ammo=20)
        enemy = Contact(E, (70., 0.), 0., True, True, visible_to=frozenset({I,J}))
        orders = Policy().step(scene(units=(support, mover), contacts=(enemy,)))
        cover_order = next(o for o in orders if o.identity == I)
        advance = next(o for o in orders if o.identity == J)
        self.assertEqual(cover_order.action, 'attack')
        self.assertEqual(advance.action, 'move')
        from math import dist
        self.assertLessEqual(dist(mover.position, advance.destination), 10.)

    def test_single_smg_uses_nearby_support_and_stops_advancing_when_support_reloads(self):
        support = replace(U, squad='support', weapon_model='bar', covering=True, readiness='ready', ammo=20)
        mover = replace(U, identity=J, squad='single_smg', weapon_model='thompson', ammo=20)
        enemy = Contact(E, (70., 0.), 0., True, True, visible_to=frozenset({I, J}))
        policy = Policy()
        orders = policy.step(scene(units=(support, mover), contacts=(enemy,)))
        advance = next(o for o in orders if o.identity == J)
        self.assertEqual(advance.reason, 'supported advance')
        self.assertLessEqual(dist(mover.position, advance.destination), 10.)
        policy.acknowledge(advance, 'completed')
        later = scene(2., units=(replace(support, readiness='reloading', ammo=0),
                                replace(mover, position=advance.destination)),
                      contacts=(replace(enemy, observed_at=2.),))
        orders = policy.step(later)
        self.assertFalse(any(o.identity == J and o.action == 'move' for o in orders))
        self.assertTrue(any(o.identity == J and o.action == 'attack' for o in orders))

    def test_capture_identity_controls_victory_and_defeat(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from unittest.mock import patch
        from tactical_scenarios import collect_battle_result
        cases = [('a', 'same', 123, 123, 0, 'victory'), ('b', 'same', 123, 123, 0, 'defeat'),
                 ('a', 'other', 123, 123, 0, 'unknown'), ('a', 'same', None, None, 0, 'unknown'),
                 ('a', 'same', 123, 456, 0, 'unknown'), ('a', 'same', 123, 123, 1, 'unknown')]
        for winner, identity, start, observed_start, code, expected in cases:
            with TemporaryDirectory() as folder:
                output = Path(folder)
                capture = output / 'completion' / 'run_fixture'
                capture.mkdir(parents=True)
                files = {'completion_normalized.json': {'engine_outcome': {'winning_team': winner}},
                         'completion_raw.json': {'match_id': 'same', 'native_game_start_time': start},
                         'match_observation.json': {'match_id': identity, 'native_game_start_time': start}}
                for name, value in files.items():
                    (capture / name).write_text(json.dumps(value), encoding='utf-8')
                summary = dict(matchCompleted=True, localTeam='a', stop={'stopped': True},
                               postDetachCode={str(i): True for i in range(12)}, battleNativeStartTime=observed_start)
                import subprocess
                for cleanup in (SimpleNamespace(returncode=0, stdout='', stderr=''),
                                SimpleNamespace(returncode=1, stdout='', stderr='guard rejected'),
                                subprocess.TimeoutExpired('save-ai-results', 60)):
                    with patch('tactical_scenarios.subprocess.run', side_effect=[
                            SimpleNamespace(returncode=code, stdout='', stderr=''), cleanup]) as command:
                        collect_battle_result(123, output, summary)
                    self.assertEqual(summary['outcome'], expected)
                    self.assertEqual(json.loads((output / 'summary.json').read_text())['outcome'], expected)
                    self.assertEqual(command.call_count, 1 if expected == 'unknown' else 2)
                    if expected != 'unknown':
                        self.assertIn('save-ai-results', command.call_args.args[0])
                        self.assertEqual(summary['resultCleanup']['status'],
                                         'saved' if getattr(cleanup, 'returncode', None) == 0 else 'failed')

    def test_unverified_detach_persists_unknown_without_attempting_capture(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from tactical_scenarios import collect_battle_result
        with TemporaryDirectory() as folder:
            summary = dict(matchCompleted=True, outcome='victory')
            with patch('tactical_scenarios.subprocess.run') as command:
                collect_battle_result(123, Path(folder), summary)
            command.assert_not_called()
            saved = json.loads((Path(folder) / 'summary.json').read_text())
            self.assertEqual(saved['outcome'], 'unknown')
            self.assertEqual(saved['resultCollection']['status'], 'withheld')

    def test_vehicle_death_after_shot_is_observed_without_kill_attribution(self):
        evidence = Evidence()
        runtime = Runtime(lambda _: 'accepted', evidence)
        metrics = TacticalMetrics()
        launcher = replace(U, weapon_model='bazooka', ammo=1)
        vehicle = Contact(E, (70., 0.), 0., True, True, kind='vehicle')
        first = scene(units=(launcher,), contacts=(vehicle,))
        attack, = runtime.step(first)
        metrics.sample(first, runtime, ())
        fired = scene(1., units=(replace(launcher, ammo=0),), contacts=(replace(vehicle, observed_at=1.),))
        completions = [(attack, 'completed')]
        runtime.step(fired, completions)
        report = metrics.sample(fired, runtime, completions)
        self.assertEqual(report['vehicleEngagements']['shotsObserved'], 1)
        self.assertNotIn('targetDeathObserved', report['vehicleEngagements'])
        destroyed = scene(2., units=(replace(launcher, ammo=0),),
                          contacts=(replace(vehicle, observed_at=2., dead=True, enemy=None),))
        runtime.step(destroyed)
        report = metrics.sample(destroyed, runtime, ())
        self.assertEqual(report['vehicleEngagements']['targetDeathAfterShotObserved'], 1)
        self.assertIn('kill attribution unavailable', report['damageConfirmation'])


if __name__ == '__main__':
    unittest.main()
