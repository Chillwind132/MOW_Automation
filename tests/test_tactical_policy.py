import _test_paths
import unittest
from math import dist
from dataclasses import replace
from tactical_policy import Contact, Cover, Event, Identity, Objective, Policy, Snapshot, Unit
from tactical_controller import IntentQueue, Runtime


I = Identity('match', '1', 1)
J = Identity('match', '2', 1)
E = Identity('match', 'enemy', 1)
U = Unit(I, 'local', 'alpha', (0., 0.), move_at_will=True)
O = Objective('flag', (100., 0.), 'enemy', reachable=True)
CAPS = frozenset({'move', 'stance', 'cover', 'attack', 'build'})


def scene(time=0., units=(U,), **kwargs):
    values = dict(match='match', time=time, owner='local', units=units,
                  objectives=(O,), capabilities=CAPS)
    values.update(kwargs)
    return Snapshot(**values)


def support_scene(time=0., units=(U,), **kwargs):
    # A current personal sighting near the objective but outside attack range
    # isolates movement coordination from target selection in these tests.
    contact = Contact(E, (190., 0.), time, True, True, strength=.01,
                      visible_to=frozenset(u.identity for u in units))
    return scene(time, units, contacts=(contact,), **kwargs)


class PolicyTests(unittest.TestCase):
    def test_failed_move_uses_another_endpoint_after_cooldown(self):
        policy = Policy()
        first, = policy.step(scene())
        self.assertEqual(first.action, 'move')
        policy.acknowledge(first, 'failed')
        self.assertEqual(policy.step(scene(2.)), [])
        second, = policy.step(scene(11.))
        self.assertEqual(second.action, 'move')
        self.assertGreaterEqual(dist(first.destination, second.destination), 3.)
        self.assertLessEqual(dist(U.position, second.destination), policy.MAX_MOVE_LEG)

    def test_loaded_at_can_respond_to_vehicle_pressure_without_ignoring_urgent_danger(self):
        unit = replace(U, weapon_model='bazooka', ammo=1)
        vehicle = Contact(E, (30., 0.), 0., True, True, kind='vehicle', strength=4., visible_to=frozenset({I}))
        policy = Policy()
        order, = policy.step(scene(units=(unit,), contacts=(vehicle,)))
        self.assertEqual((order.action, order.reason), ('attack', 'anti-armor response'))
        self.assertEqual(policy.step(scene(.2, units=(unit,), contacts=(vehicle,))), [])
        self.assertEqual(policy.members[I].action, order)
        # A teammate's continued sighting cannot preserve this soldier's attack.
        policy.step(scene(.3, units=(unit,), contacts=(replace(vehicle, visible_to=frozenset({J})),)))
        self.assertIsNone(policy.members[I].action)
        for changed in (replace(unit, urgent_danger=True), replace(unit, ammo=0), replace(unit, readiness='reloading')):
            self.assertFalse(any(o.action == 'attack' for o in Policy().step(scene(units=(changed,), contacts=(vehicle,)))))

    def test_rifle_grenade_vehicle_selection_requires_loaded_heat_identity(self):
        vehicle = Contact(E, (60., 0.), 0., True, True, kind='vehicle')
        for projectile, expected in (('garand_heat_ammo', True), ('em_mk3_ammo', False), ('garand_wp_ammo', False), (None, False)):
            unit = replace(U, weapon_model='garand_grenade', projectile_model=projectile, ammo=1)
            orders = Policy().step(scene(units=(unit,), contacts=(vehicle,)))
            self.assertEqual(any(o.action == 'attack' for o in orders), expected)
        unit = replace(U, weapon_model='garand_grenade', projectile_model='garand_heat_ammo', ammo=1)
        self.assertFalse(any(o.action == 'attack' for o in Policy().step(scene(units=(unit,), contacts=(replace(vehicle, kind='infantry'),)))))

    def test_intermediate_native_cover_does_not_permanently_stop_advance(self):
        cover = Cover('native', (25., 0.), reachable=True, native_score=4., observer=I)
        policy = Policy()
        order, = policy.step(scene(covers=(cover,), capabilities=CAPS | {'nativeCover'}))
        policy.acknowledge(order, 'completed')
        settled = replace(U, position=cover.position, in_cover=True, stance='standing')
        self.assertEqual(policy.step(scene(1.1, units=(settled,), covers=(cover,), capabilities=CAPS | {'nativeCover'})), [])
        move, = policy.step(scene(3., units=(settled,), covers=(cover,), capabilities=CAPS | {'nativeCover'}))
        self.assertEqual(move.action, 'move')

    def test_nearby_native_cover_before_combat_preserves_active_weapon_work(self):
        cover = Cover('native', (2., 0.), reachable=True, native_score=4., observer=I)
        contact = Contact(E, (60., 0.), 0., True, True)
        options = dict(covers=(cover,), contacts=(contact,), capabilities=CAPS | {'nativeCover'})
        order, = Policy().step(scene(**options))
        self.assertEqual((order.action, order.reason), ('cover', 'nearby combat cover'))
        for readiness in ('firing', 'aiming', 'reloading'):
            self.assertEqual(Policy().step(scene(units=(replace(U, readiness=readiness),), **options)), [])
        order, = Policy().step(scene(units=(replace(U, in_cover=True),), **options))
        self.assertEqual(order.action, 'attack')

    def test_native_cover_preference_does_not_imply_protection_or_other_observers(self):
        cover = Cover('native', (25., 0.), reachable=True, native_score=4., observer=I)
        enabled = CAPS | {'nativeCover'}
        order, = Policy().step(scene(covers=(cover,), capabilities=enabled))
        self.assertEqual((order.action, order.site), ('cover', 'native'))
        for candidate, capabilities in ((cover, CAPS), (replace(cover, observer=J), enabled),
                (replace(cover, reachable=False), enabled), (replace(cover, occupied=True), enabled),
                (replace(cover, destroyed=True), enabled), (replace(cover, position=(-4., 0.)), enabled)):
            orders = Policy().step(scene(covers=(candidate,), capabilities=capabilities))
            self.assertFalse(any(order.action == 'cover' for order in orders))

    def test_bazooka_vehicle_opportunity_interrupts_travel(self):
        unit = replace(U, weapon_model='bazooka', ammo=1)
        contact = Contact(E, (60., 0.), .3, True, True, kind='vehicle', visible_to=frozenset({I}))
        policy = Policy()
        move, = policy.step(scene(units=(unit,)))
        self.assertEqual(move.action, 'move')
        policy.acknowledge(move, 'accepted')
        attack, = policy.step(scene(.3, units=(unit,), contacts=(contact,)))
        self.assertEqual((attack.action, attack.target), ('attack', E))
        self.assertGreater(attack.revision, move.revision)
        self.assertFalse(policy.acknowledge(move, 'completed'))

    def test_bazooka_keeps_travel_without_usable_local_vehicle_sighting(self):
        unit = replace(U, weapon_model='bazooka', ammo=1)
        contact = Contact(E, (60., 0.), .3, True, True, kind='vehicle', visible_to=frozenset({I}))
        for changed, target in ((unit, replace(contact, visible_to=frozenset({J}))),
                (unit, replace(contact, kind='infantry')), (replace(unit, ammo=0), contact),
                (replace(unit, readiness='reloading'), contact), (replace(unit, readiness='firing'), contact),
                (unit, replace(contact, position=(101., 0.)))):
            policy = Policy()
            move, = policy.step(scene(units=(unit,)))
            self.assertEqual(policy.step(scene(.3, units=(changed,), contacts=(target,))), [])
            self.assertEqual(policy.members[I].action, move)

    def test_near_cover_requires_actual_occupation_before_settling(self):
        cover = Cover('wall', (20., 0.), reachable=True, protection=1., firing_access=True, escape=True)
        objective = replace(O, position=cover.position)
        for occupied in (False, None):
            unit = replace(U, position=cover.position, stance='prone', in_cover=occupied)
            order, = Policy().step(scene(units=(unit,), covers=(cover,), objectives=(objective,)))
            self.assertEqual((order.action, order.site), ('cover', 'wall'))
        unit = replace(U, position=cover.position, in_cover=True)
        order, = Policy().step(scene(units=(unit,), covers=(cover,), objectives=(objective,)))
        self.assertEqual((order.action, order.reason), ('stance', 'settle in cover'))
        # Occupation of another nearby position is not arrival at this slot.
        unit = replace(unit, position=(18., 0.))
        order, = Policy().step(scene(units=(unit,), covers=(cover,), objectives=(objective,)))
        self.assertEqual(order.action, 'cover')

    def test_loaded_bazookas_prefer_a_shared_visible_vehicle_without_claiming_readiness(self):
        first=replace(U,weapon_model='bazooka',ammo=1,readiness='unknown')
        second=replace(first,identity=J,position=(80.,0.))
        a=Contact(E,(30.,0.),0.,True,True,kind='vehicle')
        b=replace(a,identity=replace(E,unit='other'),position=(70.,0.))
        orders=Policy().step(scene(units=(first,second),contacts=(a,b)))
        self.assertEqual(len(orders),2)
        self.assertEqual(len({o.target for o in orders}),1)
        # Shared sightings never permit a launcher to target what it cannot see.
        orders=Policy().step(scene(units=(first,second),contacts=(replace(a,visible_to=frozenset({I})),replace(b,visible_to=frozenset({J})))))
        self.assertEqual({o.identity:o.target for o in orders},{I:E,J:b.identity})

    def test_bazooka_targets_observed_vehicle_and_preserves_rocket_from_infantry(self):
        bazooka=replace(U,weapon_model='bazooka',ammo=1)
        vehicle=Contact(E,(30.,0.),0.,True,True,kind='vehicle')
        order,=Policy().step(scene(units=(bazooka,),contacts=(vehicle,)))
        self.assertEqual((order.action,order.target),('attack',E))
        for unit,contact in ((replace(bazooka,ammo=0),vehicle),(bazooka,replace(vehicle,kind='infantry'))):
            self.assertFalse(any(o.action=='attack' for o in Policy().step(scene(units=(unit,),contacts=(contact,)))))

    def test_captured_majority_prioritizes_retention_then_recovers_lost_flags(self):
        owned=replace(O,key='a',position=(10.,0.),owner='local')
        other=replace(owned,key='b',position=(200.,0.))
        enemy=replace(O,key='c',position=(12.,0.))
        policy=Policy();policy.step(scene(objectives=(owned,other,enemy)))
        self.assertEqual(policy.squads[U.squad].goal,'a')
        policy.step(scene(3.,objectives=(owned,replace(other,owner='enemy'),enemy)))
        self.assertEqual(policy.squads[U.squad].goal,'c')

    def test_weapon_preference_preserves_alternating_cover_groups(self):
        mg=replace(U,identity=replace(I,unit='0'),weapon_model='bar',covering=True,readiness='ready',ammo=20)
        rifle=replace(mg,identity=I,weapon_model='garand')
        smg=replace(mg,identity=replace(I,unit='9'),weapon_model='thompson')
        policy=Policy();first,=policy.step(support_scene(units=(mg,rifle,smg)))
        self.assertEqual(first.identity,smg.identity)
        policy.acknowledge(first,'completed')
        second,=policy.step(support_scene(2.,units=(mg,rifle,replace(smg,position=first.destination))))
        self.assertNotEqual(second.identity,smg.identity)
        self.assertEqual(second.action,'move')

    def test_travel_posture_waits_for_stance_then_advances_without_repeating(self):
        policy=Policy();prone=replace(U,stance='prone')
        order,=policy.step(scene(units=(prone,)))
        self.assertEqual((order.action,order.stance),('stance','standing'))
        self.assertEqual(policy.step(scene(.5,units=(prone,))),[])
        policy.acknowledge(order,'completed')
        move,=policy.step(scene(2.,units=(U,)))
        self.assertEqual(move.action,'move')

    def test_travel_posture_preserves_local_threat_and_weapon_work(self):
        prone=replace(U,stance='prone')
        contact=Contact(E,(70.,0.),0.,True,True,visible_to=frozenset({J}))
        orders=Policy().step(scene(units=(prone,),contacts=(contact,)))
        self.assertFalse(any(o.action=='stance' for o in orders))
        for readiness in ('aiming','firing','reloading'):
            self.assertEqual(Policy().step(scene(units=(replace(prone,readiness=readiness),))),[])
        orders=Policy().step(scene(units=(prone,),capabilities=frozenset({'move'})))
        self.assertEqual([o.action for o in orders],['move'])

    def test_native_posture_reversion_does_not_trigger_repeated_stand_orders(self):
        policy=Policy();prone=replace(U,stance='prone')
        stance,=policy.step(scene(units=(prone,)))
        policy.acknowledge(stance,'completed')
        move,=policy.step(scene(2.,units=(prone,)))
        self.assertEqual(move.action,'move')
        policy.acknowledge(move,'completed')
        stance,=policy.step(scene(31.,units=(prone,)))
        self.assertEqual(stance.action,'stance')

    def test_vehicle_is_a_threat_without_unverified_infantry_attack(self):
        policy=Policy();enemy=Contact(E,(20.,0.),0.,True,True)
        order,=policy.step(scene(contacts=(enemy,)))
        self.assertEqual(order.action,'attack')
        orders=policy.step(scene(1.,contacts=(replace(enemy,observed_at=1.,kind='vehicle'),)))
        self.assertTrue(policy.danger(U.position)>0)
        self.assertFalse(any(o.action=='attack' for o in orders))
        self.assertIsNone(policy.members[I].action)
        self.assertEqual(policy.members[I].last_status,'cancelled')

    def test_owned_identity_invalidates_former_enemy_memory(self):
        policy=Policy();policy.step(scene(contacts=(Contact(E,(20.,0.),0.,True,True),)))
        self.assertIn(E,policy.memory)
        policy.step(scene(1.,units=(U,replace(U,identity=E)),contacts=(Contact(E,(20.,0.),1.,True,True),)))
        self.assertNotIn(E,policy.memory)

    def test_reinforcement_counts_living_soldiers_not_fragmented_squads(self):
        a=replace(O,key='a',position=(10.,0.));b=replace(O,key='b',position=(20.,0.))
        defenders=tuple(replace(U,identity=replace(I,unit='a'+str(i)),squad='a'+str(i),position=a.position)
                        for i in range(12)) + tuple(
            replace(U,identity=replace(I,unit='b'+str(i)),squad='b',position=b.position) for i in range(12))
        policy=Policy();policy.step(scene(units=defenders,objectives=(a,b)))
        for key,squad in policy.squads.items():
            squad.goal='a' if key.startswith('a') else 'b';squad.next_goal=1000.
        policy.step(scene(1.,units=(U,)+defenders,objectives=(a,b)))
        # Both objectives have twelve defenders. Twelve surviving fragments
        # must not count as twelve times the force of one intact squad.
        self.assertEqual(policy.squads[U.squad].goal,'a')

    def test_objective_threat_accounts_for_friendly_strength(self):
        contacts=tuple(Contact(replace(E,unit='enemy'+str(i)),O.position,0.,True,True) for i in range(5))
        friendly=replace(O,key='home',owner='local',position=(10.,0.))
        for count, expected in ((4,'home'),(40,'flag')):
            units=tuple(replace(U,identity=replace(I,unit=str(i))) for i in range(count))
            policy=Policy()
            policy.step(scene(units=units,objectives=(O,friendly),contacts=contacts))
            self.assertEqual(policy.squads['alpha'].goal,expected)

    def test_capture_positions_are_stable_inside_observed_area_and_disperse_units(self):
        objective=replace(O,capture_radius=30.)
        units=[replace(U,identity=replace(I,unit=str(i))) for i in range(64)]
        points=[Policy._objective_position(u,objective) for u in units]
        self.assertEqual(len(set(points)),64)
        self.assertTrue(all(0 < dist(p,objective.position) <= 22.5 for p in points))
        self.assertEqual(points,[Policy._objective_position(u,objective) for u in units])
        self.assertEqual(Policy._objective_position(U,O),O.position)
        for radius in (0., -1., True, float('nan')):
            with self.assertRaisesRegex(ValueError,'capture radius'):
                Policy().step(scene(objectives=(replace(O,capture_radius=radius),)))

    def test_verified_visible_ally_support_expires_and_is_not_double_counted(self):
        ally = Contact(J, (0., 0.), 0., True, False, allied=True)
        for change in ({}, {'visible': False}, {'dead': True}, {'allied': False},
                       {'observed_at': -3.}, {'observed_at': 1.}, {'identity': I},
                       {'identity': replace(J, match='old')}):
            policy = Policy()
            policy.step(scene(contacts=(replace(ally, **change),)))
            self.assertEqual(policy._support((0., 0.)), 1. if change else 2.)
        policy = Policy()
        policy.step(scene(contacts=(ally,), contact_identities=(replace(J, incarnation=2),)))
        self.assertEqual(policy._support((0., 0.)), 1.)
        policy.step(scene(1., contacts=(ally,)))
        self.assertEqual(policy._support((0., 0.)), 1.)

    def test_observed_ally_can_prevent_unsupported_retreat(self):
        enemy = Contact(E, (5., 0.), 0., True, True, strength=2.)
        ally = Contact(J, (0., 0.), 0., True, False, allied=True)
        alone, supported = Policy(), Policy()
        alone.step(scene(contacts=(enemy,)))
        supported.step(scene(contacts=(enemy, ally)))
        self.assertEqual(alone.squads['alpha'].state, 'withdraw')
        self.assertNotEqual(supported.squads['alpha'].state, 'withdraw')

    def test_shared_contact_guides_movement_but_only_observer_attacks(self):
        other = replace(U, identity=J, squad='other', position=(0., 10.))
        contact = Contact(E, (40., 0.), 0., True, True, visible_to=frozenset({I}))
        orders = Policy().step(scene(units=(U, other), contacts=(contact,)))
        self.assertEqual(next(i for i in orders if i.identity == I).action, 'attack')
        self.assertEqual(next(i for i in orders if i.identity == J).action, 'move')
        for observers in (frozenset({Identity('other-match', '1', 1)}), {I}):
            with self.assertRaisesRegex(ValueError, 'contact observers'):
                Policy().step(scene(contacts=(replace(contact, visible_to=observers),)))

    def test_unknown_fallback_requires_native_path_preflight_capability(self):
        support = replace(U,identity=J,squad='rear',position=(-100.,0.),move_at_will=False)
        contact = Contact(E,(5.,0.),0.,True,True,strength=10.,urgent=True)
        for capability, reachable in ((False,None),(True,None),(True,False)):
            p=Policy()
            orders=p.step(scene(units=(U,replace(support,reachable=reachable)),contacts=(contact,),
                capabilities=CAPS | (frozenset({'path'}) if capability else frozenset())))
            withdrawing=[i for i in orders if i.identity==I and i.reason=='withdraw']
            self.assertEqual(bool(withdrawing),capability and reachable is None)
            if withdrawing:
                self.assertEqual(withdrawing[0].destination, (-29., 0.))
                self.assertLess(p.danger(withdrawing[0].destination), p.danger(U.position))

    def test_failed_withdrawal_tries_another_anchor_without_replaying_failed_legs(self):
        support = replace(U, identity=J, squad='rear', position=(-100., 0.), move_at_will=False)
        other = replace(support, identity=replace(J, unit='rear2'), position=(-100., 80.))
        contact = Contact(E, (5., 0.), 0., True, True, strength=10., urgent=True)
        policy = Policy()
        def snapshot(t):
            return scene(t, units=(U, support, other), contacts=(replace(contact, observed_at=t),),
                         capabilities=CAPS | {'path'})
        first, = policy.step(snapshot(0.))
        self.assertEqual(first.reason, 'withdraw')
        policy.acknowledge(first, 'failed')
        second, = policy.step(snapshot(1.1))
        self.assertEqual(second.reason, 'withdraw')
        self.assertNotEqual(first.destination, second.destination)
        self.assertLess(policy.danger(second.destination), policy.danger(U.position))
        policy.acknowledge(second, 'failed')
        self.assertEqual(policy.step(snapshot(2.2)), [])

    def test_decision_budget_keeps_urgent_invalidation_for_the_whole_army(self):
        units = tuple(replace(U, identity=replace(I, unit=str(i)), squad=str(i), position=(0., i * 5.))
                      for i in range(100))
        policy = Policy()
        for tick in range(4):
            policy.step(scene(tick * .2, units=units, objectives=(replace(O, position=(10000., 0.)),)))
        self.assertTrue(all(m.action is not None for m in policy.members.values()))
        urgent = tuple(replace(u, urgent_danger=True) for u in units)
        self.assertEqual(policy.step(scene(1., units=urgent, objectives=(replace(O, position=(10000., 0.)),))), [])
        self.assertTrue(all(m.action is None for m in policy.members.values()))
        self.assertEqual(policy._decisions_this_step, Policy.MAX_DECISIONS)

    def test_rotating_schedule_preserves_balanced_objective_commitment(self):
        units = tuple(replace(U, identity=replace(I, unit=str(i)), squad=str(i),
            position=(float(i) * 4, 0.)) for i in range(12))
        objectives = tuple(replace(O, key=str(i), position=(float(i - 2) * 30, 200.)) for i in range(5))
        p = Policy()
        p.step(scene(units=units, objectives=objectives))
        initial = {key: squad.goal for key, squad in p.squads.items()}
        for tick in range(1, 51):
            p.step(scene(tick * .2, units=units, objectives=objectives))
            self.assertEqual({key: squad.goal for key, squad in p.squads.items()}, initial)

    def test_thousand_units_receive_bounded_orders_without_starvation(self):
        units = tuple(replace(U, identity=replace(I, unit=str(i)), squad=str(i // 12),
            position=(float(i % 32) * 10, float(i // 32) * 10)) for i in range(1024))
        p, addressed = Policy(), set()
        for tick in range(40):
            orders = p.step(scene(tick * .2, units=units,
                objectives=(replace(O, position=(2000., 2000.)),)))
            self.assertLessEqual(len(orders), 32)
            self.assertFalse(addressed.intersection(o.identity for o in orders))
            addressed.update(o.identity for o in orders)
            if len(addressed) == len(units):
                break
        self.assertEqual(len(addressed), 1024)
        # Reclamation applies immediately even when new-order work is capped.
        reclaimed = units[-1].identity
        p.step(scene(8.2, units=units, events=(Event('manual-large', 'move', (reclaimed,)),)))
        self.assertFalse(p.members[reclaimed].enrolled)
        self.assertIsNone(p.members[reclaimed].action)

    def test_aggregated_support_is_exact_nearby_and_conservative_far_away(self):
        from math import dist
        units = tuple(replace(U, identity=replace(I, unit=str(i)),
            position=(float(i % 16) * 15, float(i // 16) * 15)) for i in range(256))
        p = Policy()
        p.step(scene(units=units, objectives=(), capabilities=frozenset()))
        for position in ((0., 0.), (100., 100.), (500., 500.)):
            exact = sum(1. / (1. + dist(position, u.position) / 30.) for u in units)
            self.assertLessEqual(p._support(position), exact + 1e-10)
            self.assertGreaterEqual(p._support(position), exact * .9)
        nearby = Policy()
        nearby.step(scene(units=units[:4], objectives=()))
        self.assertAlmostEqual(nearby._support((0., 0.)),
            sum(1. / (1. + dist((0., 0.), u.position) / 30.) for u in units[:4]))

    def test_pressure_shortcut_preserves_threshold_decisions(self):
        units=tuple(replace(U,identity=replace(I,unit=str(i)),position=(float(i)*10,0.)) for i in range(4))
        p=Policy()
        for tick,strength in enumerate((.1,1.,3.,8.,30.,.2)):
            contact=Contact(Identity('match','enemy',1),(10.,0.),float(tick),True,True,strength=strength)
            p.step(scene(float(tick),units=units,contacts=(contact,),capabilities=frozenset()))
            for unit in units:
                exact=p.danger(unit.position)/max(1.,p._support(unit.position))
                estimate=p.pressure(unit.position)
                self.assertGreaterEqual(estimate+1e-10,exact)
                self.assertEqual(estimate<.7,exact<.7)
                self.assertEqual(estimate>1.6,exact>1.6)

    def test_emergency_gets_order_before_large_ordinary_wave(self):
        ordinary = tuple(replace(U, identity=replace(I, unit=str(i)), squad='a',
            position=(float(i) * 10, 1000.)) for i in range(64))
        urgent = replace(U, identity=replace(I, unit='urgent'), squad='z', urgent_danger=True)
        fallback = replace(U, identity=replace(I, unit='support'), squad='safe',
            position=(-50., 0.), move_at_will=False, reachable=True)
        p = Policy()
        orders = p.step(scene(units=ordinary + (urgent, fallback),
            contacts=(Contact(E, (10., 0.), 0., True, True),)))
        self.assertEqual(orders[0].identity, urgent.identity)
        self.assertEqual(orders[0].reason, 'withdraw')
        self.assertLessEqual(len(orders), 32)

    def test_identity_only_replacement_rejects_stale_contact_without_death(self):
        p = Policy()
        contact = Contact(E, (30., 0.), 0., True, True)
        p.step(scene(contacts=(contact,)))
        p.step(scene(.2, contacts=(contact,), contact_identities=(replace(E, incarnation=2),)))
        self.assertFalse(p.memory)
        self.assertFalse(p.casualties)
        for identities in ((E, E), (replace(E, match='old'),),
                (replace(E, incarnation=0),), (replace(E, incarnation=True),),
                tuple(Identity('match', str(n), 1) for n in range(4097))):
            with self.subTest(count=len(identities)):
                with self.assertRaises(ValueError):
                    Policy().step(scene(contact_identities=identities))

    def test_contact_freshness_has_a_bounded_source_interval(self):
        for interval in (0., 2.01, float('inf'), float('nan')):
            with self.assertRaisesRegex(ValueError, 'invalid contact'):
                Policy().step(scene(contacts=(Contact(E, (30., 0.), 0., True, True, fresh_for=interval),)))

    def test_delayed_casualty_ages_from_observation_and_expires(self):
        p = Policy()
        death = Event('late', 'allied_death', position=(0., 0.), confirmed=True, observed_at=0.)
        p.step(scene(90., events=(death,), capabilities=frozenset()))
        self.assertEqual(p.casualties[(0, 0)], (1., 0.))
        self.assertAlmostEqual(p.danger((0., 0.)), .25)
        p.step(scene(121., capabilities=frozenset()))
        self.assertEqual(p.casualties, {})

    def test_older_casualty_does_not_refresh_cell_timestamp(self):
        p = Policy()
        death = Event('newer', 'allied_death', position=(0., 0.), confirmed=True, observed_at=30.)
        p.step(scene(60., events=(death,), capabilities=frozenset()))
        p.step(scene(90., events=(replace(death, key='older', observed_at=0.),), capabilities=frozenset()))
        self.assertEqual(p.casualties[(0, 0)], (1.75, 30.))
        expired = Policy()
        expired.step(scene(151., events=(death,), capabilities=frozenset()))
        self.assertEqual(expired.casualties, {})

    def test_invalid_event_observation_time_is_rejected(self):
        for stamp in (-1., 2., float('inf'), float('nan')):
            with self.assertRaisesRegex(ValueError, 'event observation time'):
                Policy().step(scene(1., events=(Event('bad', 'allied_death', observed_at=stamp),)))

    def test_spawn_pile_uses_lateral_endpoints_for_concurrent_departure(self):
        p = Policy()
        units = tuple(replace(U, identity=replace(I, unit=str(i))) for i in range(1, 5))
        orders = p.step(scene(units=units))
        self.assertEqual(len(orders), 4)
        points = [order.destination for order in orders]
        self.assertTrue(any(y != 0. for x, y in points))
        self.assertTrue(all(0. < x <= 29. and dist((0.,0.), (x,y)) <= 29.000001 for x,y in points))
        self.assertTrue(all(dist(a,b) >= 3. for i,a in enumerate(points) for b in points[i+1:]))

    def test_stationary_endpoint_blockers_do_not_prevent_progress(self):
        p = Policy()
        blockers = tuple(replace(U, identity=replace(I, unit=str(i)), position=(x, 0.), move_at_will=False)
                         for i, x in enumerate((29., 21.75, 14.5), 2))
        order, = p.step(scene(units=(U, *blockers)))
        self.assertNotEqual(order.destination[1], 0.)
        # Keep a clear shorter straight route available at a narrow approach.
        order, = Policy().step(scene(units=(U, blockers[0])))
        self.assertEqual(order.destination, (21.75, 0.))

    def test_dense_spawn_can_dispatch_most_of_a_wave_without_arrival_waits(self):
        units=tuple(replace(U,identity=replace(I,unit=str(i))) for i in range(32))
        orders=Policy().step(scene(units=units))
        self.assertGreaterEqual(len(orders),24)
        self.assertLessEqual(len(orders),32)
        points=[o.destination for o in orders]
        self.assertTrue(all(dist(U.position,p)<=29.000001 for p in points))
        self.assertTrue(all(dist(a,b)>=3. for i,a in enumerate(points) for b in points[i+1:]))

    def test_alternating_failure_falls_back_without_claiming_arrival(self):
        for status in ('failed', 'uncertain', 'cancelled'):
            p = Policy()
            coverer = replace(U, covering=True, readiness='ready', ammo=8)
            mover = replace(U, identity=J)
            order, = p.step(support_scene(units=(coverer, mover)))
            self.assertEqual(order.identity, J)
            p.acknowledge(order, status)
            orders = p.step(support_scene(1., units=(coverer, mover)))
            self.assertEqual(p.squads['alpha'].moving, set())
            self.assertGreater(p.squads['alpha'].individual_until, 1.)
            if status != 'cancelled':
                self.assertFalse(any(i.identity == J for i in orders))

    def test_alternating_switch_requires_completed_move_and_ready_cover(self):
        p = Policy()
        coverer = replace(U, covering=True, readiness='ready', ammo=8)
        mover = replace(U, identity=J)
        order, = p.step(support_scene(units=(coverer, mover)))
        p.acknowledge(order, 'accepted')
        self.assertEqual(p.step(support_scene(1., units=(coverer, mover))), [])
        self.assertEqual(p.squads['alpha'].moving, {J})
        p.acknowledge(order, 'completed')
        arrived = replace(mover, position=order.destination, covering=True, readiness='ready', ammo=8)
        orders = p.step(support_scene(2., units=(coverer, arrived)))
        self.assertEqual(p.squads['alpha'].moving, {I})
        self.assertEqual([i.identity for i in orders], [I])

    def test_opposing_contacts_do_not_cancel_defensive_boundary(self):
        p = Policy()
        unit = replace(U, position=(100., 0.))
        contacts = (Contact(E, (0., 0.), 0., True, True, strength=.1),
                    Contact(replace(E, unit='second'), (200., 0.), 0., True, True, strength=.1))
        objective = replace(O, owner='local')
        p.step(scene(units=(unit,), contacts=contacts, objectives=(objective,), capabilities=frozenset()))
        covers = (Cover('exposed', (160., 0.), True, 100., True, True),
                  Cover('supported', (120., 0.), True, 1., True, True))
        order, = p.step(scene(1., units=(unit,), covers=covers, objectives=(objective,)))
        self.assertEqual(order.site, 'supported')

    def test_defensive_cover_stays_on_local_friendly_side(self):
        p = Policy()
        enemy = Contact(E, (220., 0.), 0., True, True, strength=.1)
        objective = replace(O, owner='local')
        p.step(scene(contacts=(enemy,), objectives=(objective,), capabilities=frozenset()))
        front = Cover('front', (130., 0.), True, 100., True, True)
        rear = Cover('rear', (80., 0.), True, 1., True, True)
        order, = p.step(scene(1., contacts=(replace(enemy, visible=False),),
                             objectives=(objective,), covers=(front, rear)))
        self.assertEqual(order.site, 'rear')
        shifted = replace(enemy, position=(0., 0.), observed_at=2.)
        p.step(scene(2., units=(replace(U, position=(200., 0.)),), contacts=(shifted,), objectives=(objective,), covers=(front, rear),
                     capabilities=frozenset({'cover'})))
        self.assertNotEqual(p.members[I].action, order)
        self.assertNotIn('rear', p.reservations)

    def test_casualty_normalization_requires_observed_presence(self):
        death = Event('death', 'allied_death', position=(0., 0.), confirmed=True)
        raw, normalized = Policy(), Policy()
        raw.step(scene(objectives=(), events=(death,)))
        normalized.step(scene(objectives=(), events=(death,), friendly_presence=((0., 0.),) * 4))
        self.assertEqual(raw.danger((0., 0.)), 1.)
        self.assertEqual(normalized.danger((0., 0.)), .25)
        # Event replay does not add deaths; absent units do not create deaths.
        normalized.step(scene(1., units=(), objectives=(), events=(death,)))
        self.assertEqual(normalized.casualties[(0, 0)][0], 1.)
        normalized.step(scene(121., units=(), objectives=()))
        self.assertEqual(normalized.presence, {})
        self.assertEqual(normalized.danger((0., 0.)), 0.)

    def test_objective_free_rally_uses_stationary_verified_support(self):
        anchor = replace(U, identity=J, squad='bravo', position=(100., 0.),
                         move_at_will=False, reachable=True)
        p = Policy()
        intent, = p.step(scene(units=(U, anchor), objectives=()))
        self.assertEqual((intent.reason, intent.destination), ('friendly support', (29., 0.)))
        self.assertTrue(p.acknowledge(intent, 'completed'))
        near = replace(U, position=(85., 0.))
        intent, = p.step(scene(1., units=(near, anchor), objectives=()))
        self.assertEqual(intent.destination, (90., 0.))
        p.acknowledge(intent, 'completed')
        self.assertEqual(p.step(scene(2., units=(replace(U, position=(90., 0.)), anchor), objectives=())), [])

    def test_rally_does_not_chase_moving_or_unknown_support(self):
        anchor = replace(U, identity=J, squad='bravo', position=(100., 0.),
                         move_at_will=False, reachable=True)
        for changed in (replace(anchor, reachable=None), replace(anchor, alive=False),
                        replace(anchor, owner='foreign'), replace(anchor, direct_control=True),
                        replace(anchor, move_at_will=True)):
            p = Policy()
            self.assertEqual(p.step(scene(units=(U, changed), objectives=())), [])

    def test_rally_loss_invalidates_queued_order(self):
        anchor = replace(U, identity=J, squad='bravo', position=(100., 0.),
                         move_at_will=False, reachable=True)
        p, q = Policy(), IntentQueue()
        q.reset('match')
        order, = p.step(scene(units=(U, anchor), objectives=()))
        q.enqueue(order, 0.)
        current = scene(.1, units=(U, replace(anchor, alive=False)), objectives=())
        self.assertEqual(p.step(current), [])
        self.assertEqual(q.drain(current, p.members), [])

    def test_objective_progress_and_commitment(self):
        p = Policy()
        intent, = p.step(scene())
        self.assertEqual(intent.destination, (29., 0.))
        self.assertEqual(p.step(scene(.2)), [])
        self.assertTrue(p.acknowledge(intent, 'accepted'))
        self.assertEqual(p.step(scene(1.)), [])

    def test_invalidated_goal_cancels_queued_move(self):
        p, q = Policy(), IntentQueue()
        q.reset('match')
        order, = p.step(scene())
        q.enqueue(order, 0.)
        changed = scene(.1, objectives=())
        self.assertEqual(p.step(changed), [])
        self.assertIsNone(p.members[I].action)
        self.assertEqual(q.drain(changed, p.members), [])

    def test_takeover_requires_explicit_reenable(self):
        p = Policy()
        p.step(scene())
        event = Event('move', 'move', (I,))
        self.assertEqual(p.step(scene(1., events=(event,))), [])
        self.assertEqual(p.step(scene(2.)), [])
        intent, = p.step(scene(3., events=(Event('enable', 'mode', (I,), mode='move_at_will'),)))
        self.assertEqual(intent.identity, I)

    def test_native_orders_and_selection_do_not_take_over(self):
        p = Policy()
        p.step(scene(events=(Event('selection', 'selection', (I,)),
                             Event('native', 'move', (I,), origin='native'))))
        self.assertTrue(p.members[I].enrolled)

    def test_individual_reclamation(self):
        p = Policy()
        units = (U, replace(U, identity=J))
        p.step(scene(units=units))
        p.step(scene(1., units, events=(Event('takeover', 'attack', (I,)),)))
        self.assertFalse(p.members[I].enrolled)
        self.assertTrue(p.members[J].enrolled)

    def test_dead_and_foreign_units_never_controlled(self):
        for u in (replace(U, alive=False), replace(U, owner='ally'), replace(U, infantry=False)):
            self.assertEqual(Policy().step(scene(units=(u,))), [])

    def test_identity_reuse_and_match_clear(self):
        p = Policy()
        old, = p.step(scene())
        newer = replace(U, identity=replace(I, incarnation=2))
        p.step(scene(1., (newer,)))
        self.assertNotIn(I, p.members)
        self.assertFalse(p.acknowledge(old, 'completed'))
        p.step(scene(0., (), match='new'))
        self.assertEqual(p.members, {})
        self.assertEqual(p.reservations, {})

    def test_pause_and_clock(self):
        p = Policy()
        self.assertEqual(p.step(scene(1., paused=True)), [])
        self.assertEqual(len(p.step(scene(1.))), 1)
        with self.assertRaises(ValueError):
            p.step(scene(0.))
        with self.assertRaises(ValueError):
            p.step(scene(float('nan')))

    def test_no_capabilities_no_orders(self):
        self.assertEqual(Policy().step(scene(capabilities=frozenset())), [])

    def test_no_invented_objectives(self):
        self.assertEqual(Policy().step(scene(objectives=())), [])
        self.assertEqual(Policy().step(scene(objectives=(replace(O, reachable=False),))), [])

    def test_hidden_contact_position_not_refreshed(self):
        p = Policy()
        contact = Contact(E, (40., 0.), 0., True, True)
        p.step(scene(contacts=(contact,)))
        p.step(scene(1., contacts=(replace(contact, position=(500., 500.), visible=False, observed_at=1.),)))
        self.assertEqual(p.memory[E].contact.position, (40., 0.))
        p.step(scene(16., objectives=()))
        self.assertEqual(p.memory, {})

    def test_confirmed_contact_death_forgets(self):
        p = Policy()
        c = Contact(E, (40., 0.), 0., True, True)
        p.step(scene(contacts=(c,)))
        p.step(scene(1., contacts=(replace(c, dead=True, visible=False),)))
        self.assertNotIn(E, p.memory)

    def test_motion_projection_bounded(self):
        p = Policy()
        c = Contact(E, (40., 0.), 0., True, True)
        p.step(scene(contacts=(c,)))
        p.step(scene(1., contacts=(replace(c, position=(100., 0.), observed_at=1.),)))
        position, confidence = p.memory[E].estimate(10.)
        self.assertLessEqual(position[0], 124.)
        self.assertLess(confidence, 1)

    def test_repeated_observation_preserves_motion(self):
        p = Policy()
        c = Contact(E, (40., 0.), 0., True, True)
        p.step(scene(contacts=(c,)))
        moved = replace(c, position=(42., 0.), observed_at=.2)
        p.step(scene(.2, contacts=(moved,)))
        velocity = p.memory[E].velocity
        p.step(scene(.3, contacts=(moved,)))
        self.assertEqual(p.memory[E].velocity, velocity)
        p.step(scene(.4, contacts=(c,)))
        self.assertEqual(p.memory[E].contact.position, moved.position)

    def test_alternating_group_keeps_verified_coverer_stationary(self):
        p = Policy()
        coverer = replace(U, covering=True, readiness='ready', ammo=10)
        mover = replace(U, identity=J)
        orders = p.step(support_scene(units=(coverer, mover)))
        self.assertEqual([i.identity for i in orders], [J])
        self.assertEqual(p.step(support_scene(.2, units=(coverer, mover))), [])
        # Reclamation or death of the coverer cannot strand the remaining member.
        p.acknowledge(orders[0], 'completed')
        orders = p.step(support_scene(2., units=(mover,)))
        self.assertEqual([i.identity for i in orders], [J])

    def test_unknown_ammo_does_not_claim_covering_fire(self):
        p = Policy()
        units = (replace(U, covering=True, readiness='ready'), replace(U, identity=J))
        self.assertEqual(len(p.step(scene(units=units))), 2)

    def test_event_coordinates_and_duplicate_incarnations_rejected(self):
        for s in (scene(events=(Event('bad', 'allied_death', position=(float('nan'), 0.)),)),
                  scene(units=(U, replace(U, identity=replace(I, incarnation=2))))):
            with self.assertRaises(ValueError):
                Policy().step(s)

    def test_reloading_does_not_replace_orders(self):
        p = Policy()
        c = Contact(E, (40., 0.), 0., True, True)
        self.assertEqual(p.step(scene(units=(replace(U, readiness='reloading'),), contacts=(c,))), [])

    def test_weapon_work_survives_contact_loss_and_then_advances(self):
        for readiness in ('aiming', 'firing', 'reloading'):
            for covers in ((), (Cover('wall', (20., 0.), True, 1., True, True),)):
                with self.subTest(readiness=readiness, cover=bool(covers)):
                    p = Policy()
                    busy = replace(U, readiness=readiness)
                    contact = Contact(E, (40., 0.), 0., True, True)
                    self.assertEqual(p.step(scene(units=(busy,), contacts=(contact,), covers=covers)), [])
                    self.assertEqual(p.step(scene(.6, units=(busy,), contacts=(), covers=covers)), [])
                    self.assertFalse(p.reservations)
                    orders = p.step(scene(1., units=(replace(busy, readiness='ready'),), covers=covers))
                    self.assertEqual(len(orders), 1)
                    self.assertIn(orders[0].action, {'move', 'cover'})

    def test_reload_does_not_block_urgent_withdrawal(self):
        support = replace(U, identity=J, squad='rear', position=(-30., 0.), reachable=True)
        busy = replace(U, readiness='reloading', urgent_danger=True)
        threat = Contact(E, (5., 0.), 0., True, True, strength=10.)
        orders = Policy().step(scene(units=(busy, support), contacts=(threat,)))
        order = next(i for i in orders if i.identity == I)
        self.assertEqual(order.reason, 'withdraw')

    def test_cover_reservation_and_death(self):
        p = Policy()
        c = Cover('wall', (80., 0.), True, 1., True, True)
        orders = p.step(scene(units=(U, replace(U, identity=J)), covers=(c,)))
        self.assertEqual(sum(i.site == 'wall' for i in orders), 1)
        p.step(scene(1., units=(), covers=(c,)))
        self.assertEqual(p.reservations, {})

    def test_unknown_destroyed_occupied_cover_rejected(self):
        c = Cover('wall', (80., 0.), True, 1., True, True)
        for bad in (replace(c, destroyed=True), replace(c, occupied=True),
                    replace(c, protection=None), replace(c, reachable=None), replace(c, escape=False)):
            order, = Policy().step(scene(covers=(bad,)))
            self.assertIsNone(order.site)

    def test_uncertain_action_not_retried_immediately(self):
        p = Policy()
        order, = p.step(scene())
        p.acknowledge(order, 'uncertain')
        self.assertEqual(p.step(scene(2.)), [])
        self.assertEqual(len(p.step(scene(11.))), 1)

    def test_duplicate_death_event_not_counted_twice(self):
        p = Policy()
        event = Event('death', 'allied_death', position=(0., 0.), confirmed=True)
        p.step(scene(events=(event,)))
        p.step(scene(1., events=(event,)))
        self.assertEqual(p.casualties[(0, 0)][0], 1)

    def test_unknown_disappearance_not_casualty(self):
        p = Policy()
        p.step(scene())
        p.step(scene(1., ()))
        self.assertEqual(p.casualties, {})

    def test_fortification_requires_tools_time_and_mobile_squad(self):
        c = Cover('site', (80., 0.), True, 1., True, True,
                  build_seconds=20., tools=True, terrain=True, safe_seconds=40.)
        units = (U, replace(U, identity=J, squad='beta'))
        orders = Policy().step(scene(units=units, objectives=(replace(O, owner='local'),), covers=(c,)))
        self.assertEqual(sum(i.action == 'build' for i in orders), 1)
        orders = Policy().step(scene(units=units, objectives=(replace(O, owner='local'),),
                                    covers=(replace(c, tools=False),)))
        self.assertFalse(any(i.action == 'build' for i in orders))

    def test_withdrawal_and_recovery(self):
        p = Policy()
        rear = replace(U, identity=J, squad='beta', position=(-80., 0.), reachable=True)
        c = Contact(E, (10., 0.), 0., True, True, strength=8.)
        orders = p.step(scene(units=(U, rear), contacts=(c,)))
        self.assertEqual(next(i for i in orders if i.identity == I).reason, 'withdraw')
        self.assertEqual(p.squads['alpha'].state, 'withdraw')
        self.assertFalse(any(i.identity == I for i in p.step(scene(.2, (U, rear), contacts=(c,)))))
        p.step(scene(16., (U, rear)))
        self.assertEqual(p.squads['alpha'].state, 'regroup')
        if p.members[I].action:
            p.acknowledge(p.members[I].action, 'completed')
        p.step(scene(20., (U, rear)))
        self.assertEqual(p.squads['alpha'].state, 'travel')

    def test_destroyed_cover_cancels_pending_action(self):
        p = Policy()
        c = Cover('wall', (80., 0.), True, 1., True, True)
        order, = p.step(scene(covers=(c,)))
        p.step(scene(1., covers=(replace(c, destroyed=True),)))
        self.assertIsNone(p.members[I].action)
        self.assertGreater(p.members[I].revision, order.revision)
        self.assertEqual(p.reservations, {})

    def test_new_incarnation_forgets_old_contact(self):
        p = Policy()
        c = Contact(E, (40., 0.), 0., True, True)
        p.step(scene(contacts=(c,)))
        new = replace(c, identity=replace(E, incarnation=2), observed_at=1.)
        p.step(scene(1., contacts=(new,)))
        self.assertNotIn(E, p.memory)

    def test_invalid_positions_and_work_budget_rejected(self):
        for s in (scene(units=(replace(U, position=(float('nan'), 0)),)),
                  scene(units=(U,) * 129), scene(covers=(Cover('bad', (0., 0.), protection=float('inf')),))):
            with self.assertRaises(ValueError):
                Policy().step(s)

    def test_completed_construction_not_repeated(self):
        p = Policy()
        c = Cover('site', (80., 0.), True, 1., True, True,
                  build_seconds=20., tools=True, terrain=True, safe_seconds=40.)
        units = (U, replace(U, identity=J, squad='beta'))
        s = scene(units=units, objectives=(replace(O, owner='local'),), covers=(c,))
        order = next(i for i in p.step(s) if i.action == 'build')
        self.assertGreater(order.expires, c.build_seconds)
        p.acknowledge(order, 'completed')
        self.assertFalse(any(i.action == 'build' for i in p.step(replace(s, time=2.))))

    def test_completed_defense_can_be_occupied(self):
        p = Policy()
        p.step(scene())
        p.built_sites.add('finished')
        p.acknowledge(p.members[I].action, 'completed')
        cover = Cover('finished', (80., 0.), True, 1., True, True)
        orders = p.step(scene(2., covers=(cover,)))
        self.assertEqual(orders[0].action, 'cover')
        self.assertEqual(orders[0].site, 'finished')

    def test_urgent_danger_invalidates_pending_advance_without_fallback(self):
        p, q = Policy(), IntentQueue()
        q.reset('match')
        order, = p.step(scene())
        q.enqueue(order, 0)
        danger = scene(.1, units=(replace(U, urgent_danger=True),))
        self.assertEqual(p.step(danger), [])
        self.assertIsNone(p.members[I].action)
        self.assertGreater(p.members[I].revision, order.revision)
        self.assertEqual(q.drain(danger, p.members), [])

    def test_event_overflow_does_not_silently_lose_deduplication(self):
        p = Policy()
        p.MAX_EVENTS = 2
        p.step(scene(events=(Event('1', 'selection'), Event('2', 'selection'))))
        with self.assertRaises(ValueError):
            p.step(scene(1., events=(Event('3', 'selection'),)))


class RuntimeTests(unittest.TestCase):
    def test_large_army_generates_only_the_current_dispatch_wave(self):
        units = tuple(replace(U, identity=replace(I, unit=str(i)), squad=str(i // 12),
            position=(float(i % 16) * 10, float(i // 16) * 10)) for i in range(256))
        runtime = self.make_runtime(lambda intent: 'accepted')
        addressed = set()
        for tick in range(40):
            sent = runtime.step(scene(tick * .6, units=units,
                objectives=(replace(O, position=(2000., 2000.)),)))
            self.assertLessEqual(len(sent), runtime.limit)
            self.assertEqual(len(runtime.queue.pending), 0)
            self.assertTrue(all(order.submit_before > tick * .6 for order in sent))
            self.assertFalse(addressed.intersection(o.identity for o in sent))
            addressed.update(o.identity for o in sent)
            if len(addressed) == len(units):
                break
        self.assertEqual(len(addressed), len(units))
        self.assertFalse(any('queueRejected' in r or 'queueDiscarded' in r for r in runtime.evidence.rows))

    def make_runtime(self, submit):
        class Records:
            def __init__(self): self.rows = []
            def write(self, row): self.rows.append(row)
        return Runtime(submit, Records())

    def test_submission_and_completion_are_separate(self):
        calls = []
        runtime = self.make_runtime(lambda intent: calls.append(intent) or 'accepted')
        order, = runtime.step(scene())
        self.assertEqual(runtime.step(scene(.2)), [])
        self.assertEqual(runtime.policy.members[I].action, order)
        runtime.step(scene(.4), ((order, 'completed'),))
        self.assertIsNone(runtime.policy.members[I].action)
        runtime.step(scene(.6), ((order, 'completed'),))
        self.assertEqual(calls, [order])
        self.assertEqual(runtime.inflight, {})

    def test_slow_native_speed_keeps_move_until_observed_arrival(self):
        runtime = self.make_runtime(lambda intent: 'accepted')
        order, = runtime.step(scene())
        # Recorded native infantry travel roughly 20 native units (one policy
        # unit) per second. The previous timeout retired a 29-unit leg early.
        for second in range(1, 30):
            snapshot = scene(float(second), units=(replace(U, position=(float(second), 0.)),))
            self.assertEqual(runtime.step(snapshot), [])
            self.assertEqual(runtime.policy.members[I].action, order)
        runtime.step(snapshot, ((order, 'completed'),))
        self.assertEqual(runtime.policy.members[I].last_status, 'completed')
        self.assertNotIn(I, runtime.inflight)

    def test_stalled_move_still_expires_without_claiming_arrival(self):
        runtime = self.make_runtime(lambda intent: 'accepted')
        order, = runtime.step(scene())
        self.assertLessEqual(order.expires, 60.)
        runtime.step(scene(order.expires + .1))
        self.assertEqual(runtime.policy.members[I].last_status, 'uncertain')
        self.assertIsNone(runtime.policy.members[I].action)

    def test_manual_reclamation_invalidates_late_completion(self):
        runtime = self.make_runtime(lambda intent: 'accepted')
        order, = runtime.step(scene())
        changed = scene(.2, events=(Event('manual', 'move', (I,)),))
        self.assertEqual(runtime.step(changed, ((order, 'completed'),)), [])
        self.assertFalse(runtime.policy.members[I].enrolled)
        self.assertEqual(runtime.inflight, {})

    def test_uncertain_rpc_stops_without_replay(self):
        calls = []
        def submit(intent):
            calls.append(intent)
            raise TimeoutError('reply lost')
        runtime = self.make_runtime(submit)
        with self.assertRaises(TimeoutError): runtime.step(scene())
        with self.assertRaises(RuntimeError): runtime.step(scene(1.))
        self.assertEqual(len(calls), 1)
        self.assertEqual(runtime.queue.pending, {})
        self.assertEqual(runtime.inflight, {})

    def test_authority_change_stops_runtime(self):
        runtime = self.make_runtime(lambda intent: 'accepted')
        runtime.step(scene())
        with self.assertRaises(RuntimeError): runtime.step(replace(scene(1.), owner='other'))
        self.assertTrue(runtime.stopped)

    def test_expired_unsent_order_clears_policy_wait(self):
        runtime = self.make_runtime(lambda intent: 'accepted')
        runtime.limit = 1
        units = (U, replace(U, identity=J))
        runtime.queue.reset('match')
        for order in runtime.policy.step(scene(units=units)):
            runtime.queue.enqueue(order, 0.)
        runtime.step(scene(units=units))
        waiting = next(iter(runtime.queue.pending))
        runtime.step(scene(1., units=units))
        self.assertNotIn(waiting, runtime.queue.pending)
        self.assertIsNone(runtime.policy.members[waiting].action)

    def test_new_firing_or_reload_cancels_unsent_movement(self):
        for readiness in ('aiming', 'firing', 'reloading'):
            calls = []
            runtime = self.make_runtime(lambda intent: calls.append(intent) or 'accepted')
            runtime.limit = 1
            units = (U, replace(U, identity=J))
            runtime.queue.reset('match')
            for order in runtime.policy.step(scene(units=units)):
                runtime.queue.enqueue(order, 0.)
            runtime.step(scene(units=units))
            waiting = next(iter(runtime.queue.pending))
            changed = tuple(replace(u, readiness=readiness) if u.identity == waiting else u for u in units)
            runtime.step(scene(.2, units=changed))
            self.assertEqual(len(calls), 1)
            self.assertNotIn(waiting, runtime.queue.pending)
            self.assertIsNone(runtime.policy.members[waiting].action)

    def test_urgent_withdrawal_can_dispatch_while_firing(self):
        policy = Policy()
        ordinary, = policy.step(scene())
        withdrawal = replace(ordinary, reason='withdraw')
        queue = IntentQueue()
        queue.reset('match')
        queue.enqueue(withdrawal, 0)
        self.assertEqual(queue.drain(scene(units=(replace(U, readiness='firing'),)), policy.members), [withdrawal])


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.p = Policy()
        self.s = scene()
        self.intent, = self.p.step(self.s)
        self.q = IntentQueue()
        self.q.reset('match')

    def test_duplicate_rejected_and_removed_before_submission(self):
        self.assertTrue(self.q.enqueue(self.intent, 0))
        self.assertFalse(self.q.enqueue(self.intent, 0))
        self.assertEqual(self.q.drain(self.s, self.p.members), [self.intent])
        self.assertEqual(self.q.drain(self.s, self.p.members), [])

    def test_reclaimed_pending_not_submitted(self):
        self.q.enqueue(self.intent, 0)
        self.p.step(scene(1., events=(Event('manual', 'move', (I,)),)))
        self.assertEqual(self.q.drain(self.s, self.p.members), [])

    def test_ownership_and_generation_checked_at_drain(self):
        for unit in (replace(U, owner='ally'), replace(U, alive=False),
                     replace(U, identity=replace(I, incarnation=2)), replace(U, direct_control=True)):
            q = IntentQueue()
            q.reset('match')
            q.enqueue(self.intent, 0)
            self.assertEqual(q.drain(scene(units=(unit,)), self.p.members), [])

    def test_expiry_and_pause(self):
        self.q.enqueue(self.intent, 0)
        self.assertEqual(self.q.drain(scene(paused=True), self.p.members), [])
        self.assertEqual(self.q.drain(scene(10.), self.p.members), [])
        self.assertEqual(self.q.pending, {})

    def test_identity_tombstones_bounded_without_eviction(self):
        self.q.MAX_IDENTITIES = 1
        self.q.cancel(I, 2)
        with self.assertRaises(RuntimeError):
            self.q.cancel(J, 1)
        self.assertFalse(self.q.enqueue(self.intent, 0))
        self.assertEqual(self.q.revisions, {I: 2})


if __name__ == '__main__':
    unittest.main()
