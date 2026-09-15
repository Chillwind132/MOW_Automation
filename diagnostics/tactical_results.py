"""Summarize tactical evidence without converting local trials into release claims."""
import argparse
import json
from pathlib import Path
import statistics
import math


class MovementMetrics:
    """Offline physical displacement; acknowledgements cannot manufacture movement."""
    def __init__(self, selected):
        self.selected = set(selected or ())
        self.initial, self.previous, self.first_moved = {}, {}, {}
        self.fractions = []
        self.generation = None
        self.last_ticks = None

    def observe(self, raw):
        if not isinstance(raw, dict) or 'units' not in raw or 'simulationTicks' not in raw:
            return
        ticks = raw['simulationTicks']
        generation = raw.get('generation')
        if self.generation is not None and generation != self.generation:
            raise ValueError('Movement report cannot combine match generations')
        if self.last_ticks is not None and ticks < self.last_ticks:
            raise ValueError('Movement report simulation time reversed')
        self.generation = generation
        if ticks == self.last_ticks or raw.get('paused'):
            return
        rows = {(r['id'],r['incarnation']): tuple(r['position'][:2]) for r in raw['units']
                if r['id'] in self.selected and r.get('eligible') is True}
        moving = comparable = 0
        for identity, position in rows.items():
            if len(position)!=2 or not all(math.isfinite(v) for v in position):
                raise ValueError('Invalid physical position')
            self.initial.setdefault(identity,(ticks,position))
            origin_ticks,origin = self.initial[identity]
            if math.dist(position,origin)>1.:
                self.first_moved.setdefault(identity,(ticks-origin_ticks)/1000.)
            if identity in self.previous:
                comparable += 1
                moving += math.dist(position,self.previous[identity])>1.
        if comparable:
            if len(self.fractions)>=20000:
                raise ValueError('Movement sample bound exceeded')
            self.fractions.append(dict(simulationTicks=ticks,moving=moving,observed=comparable,fraction=moving/comparable))
        self.previous,self.last_ticks = rows,ticks

    def result(self):
        def spacing(points):
            points=list(points)
            nearest=[min(math.dist(p,q) for j,q in enumerate(points) if i!=j) for i,p in enumerate(points)] if len(points)>1 else []
            return dict(units=len(points),nearestNeighborMedianWorld=statistics.median(nearest) if nearest else None,
                        nearestNeighborMinWorld=min(nearest) if nearest else None,
                        unitsWithNeighborWithin60World=sum(n<60. for n in nearest))
        starts=list(self.first_moved.values())
        return dict(observedIdentities=len(self.initial),movedIdentities=len(starts),
            firstMovementSeconds={f'{key[0]}:{key[1]}':value for key,value in self.first_moved.items()},
            firstMovementSpreadSeconds=max(starts)-min(starts) if starts else None,
            movingFractions=self.fractions,initialSpacing=spacing(p for _,p in self.initial.values()),
            finalSpacing=spacing(self.previous.values()),
            scope='Sampled displacement above one native world unit; spacing is not validated protection from weapons')


def summarize(directories):
    runs, groups = [], {}
    for directory in directories:
        path = directory / 'summary.json'
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        scenario = data.get('scenario', data.get('mode', 'unknown'))
        observations = directory / 'observations.jsonl'
        archives = sorted((p for p in directory.glob('observations.*.jsonl')
                           if p.name.split('.')[1].isdigit()), key=lambda p: int(p.name.split('.')[1]))
        observation_files = archives + ([observations] if observations.exists() else [])
        retention = data.get('evidenceRetention')
        complete_evidence = bool(observation_files) and (
            retention.get('discardedRecords', 0) == 0 if retention is not None else not archives)
        metrics = {'issued': 0, 'queries': 0, 'serialized': 0, 'unconfirmedSubmissions': 0,
                   'completed': 0, 'rejected': 0, 'errors': 0,
                   'terminalFailed': 0, 'terminalCancelled': 0, 'terminalUncertain': 0,
                   'retired': 0, 'retiredAtDeadline': 0, 'retiredBeforeDeadline': 0,
                   'retiredWithoutTiming': 0}
        records_read = 0
        movement = MovementMetrics(data.get('selectedUnits'))
        for observations in observation_files:
            with observations.open(encoding='utf-8') as file:
                for line in file:
                    record = json.loads(line)
                    records_read += 1
                    if movement.selected:
                        movement.observe(record.get('observation',record.get('baseline',record)))
                    query = record.get('intent', {}).get('action', record.get('action', '')).endswith('_query')
                    issued = 'intent' in record or ('action' in record and 'reply' in record)
                    metrics['issued'] += int(issued and not query)
                    metrics['queries'] += int(query or 'query' in record)
                    metrics['completed'] += int('completed' in record or
                                                ('terminal' in record and record.get('status') == 'completed'))
                    ack = record.get('ack', record.get('reply', {}))
                    metrics['serialized'] += int(ack.get('status') == 'serialized')
                    metrics['unconfirmedSubmissions'] += int(ack.get('status') == 'submitted_unconfirmed')
                    metrics['rejected'] += int(ack.get('rejected') is True)
                    metrics['errors'] += int('error' in ack)
                    if 'terminal' in record:
                        for status, field in (('failed', 'terminalFailed'), ('cancelled', 'terminalCancelled'),
                                              ('uncertain', 'terminalUncertain')):
                            metrics[field] += int(record.get('status') == status)
                    if 'retired' in record:
                        metrics['retired'] += 1
                        now, deadline = record.get('simulationTime'), record['retired'].get('expires')
                        if all(type(v) in (int, float) and math.isfinite(v) for v in (now, deadline)):
                            metrics['retiredAtDeadline' if now >= deadline else 'retiredBeforeDeadline'] += 1
                        else:
                            metrics['retiredWithoutTiming'] += 1
        if retention is not None and records_read != retention.get('retainedRecords'):
            complete_evidence = False
        if records_read == 0 or data.get('evidenceLoss'):
            complete_evidence = False
        run = {'directory': str(directory), 'scenario': scenario, 'result': data.get('result', 'unverified'),
               'error': data.get('error'), 'sourceHashes': data.get('sourceHashes'),
               'executableSha256': data.get('executableIdentity', {}).get('sha256'), 'metrics': metrics,
               'completeEvidence': complete_evidence, 'evidenceRetention': retention,
               'evidenceLoss': data.get('evidenceLoss'),
               'metricsScope': 'full recorded run' if complete_evidence else 'retained records only',
               'simulationSeconds': data.get('simulationSeconds', data.get('elapsedSimulationSeconds')),
               'objective': data.get('objective'),
               'postDetachCode': data.get('postDetachCode'), 'auditCorrection': data.get('auditCorrection'),
               'captureAttribution': data.get('captureAttribution'),
               'unitReachedObjective': data.get('unitReachedObjective')}
        if scenario in {'serialized_bot_army_combat', 'serialized_bot_battle', 'serialized_army_objectives'}:
            run['physicalMovement'] = movement.result()
            run['army'] = {k: data.get(k) for k in ('selectedUnits', 'orders', 'samples', 'reachedUnits',
                'visibleContactSamples', 'firingGuardSamples', 'nativeDeaths', 'aliveEligible',
                'nativeObservationMaxMs', 'runtimeStepMaxMs', 'readinessSamples', 'peakPressureRatio',
                'squadStateSamples', 'withdrawalOrders', 'withdrawalArrivals', 'gateScope')}
        if scenario.startswith('serialized_barricade'):
            run['construction'] = {k: data.get(k) for k in ('createdEntities', 'kitCountDecrease',
                'nativeCoverAssociated', 'usableDefense', 'returnedToStart', 'postInterruptionSimulationSeconds', 'gateScope')}
        if scenario == 'serialized_squad_advance':
            run['squadAdvance'] = {k: data.get(k) for k in ('selectedUnits', 'orders', 'arrivals',
                'completedLegsByUnit', 'maxConcurrentOrders', 'minConcurrentEndpointGapWorld',
                'initialMinPhysicalGapWorld', 'lastMinPhysicalGapWorld', 'elapsedSimulationSeconds', 'gateScope')}
        if scenario == 'serialized_reject_unavailable':
            run['unavailableUnit'] = {k: data.get(k) for k in ('unavailableUnitRejected',
                'nativeDeadPredicate', 'confirmedDeath', 'ordersIssued')}
        if scenario in {'serialized_pause', 'serialized_pause_watchdog'}:
            run['pause'] = {k: data.get(k) for k in ('pausedSamples', 'frozenSimulationTicks',
                'pausedActionRejected', 'resumed', 'automaticResumeValidated', 'ordersIssued', 'pauseRequests')}
        if scenario == 'serialized_friendly_reload_watch':
            run['friendlyReload'] = {k: data.get(k) for k in ('reloadCycles', 'activeLoadingSamples',
                'ordersIssued', 'samples', 'gateScope')}
        if scenario == 'serialized_friendly_aim_watch':
            run['friendlyPlacement'] = {k: data.get(k) for k in ('placementSamples', 'placementResults',
                'placementWaitingSamples', 'ordersIssued', 'samples', 'gateScope')}
        if scenario == 'serialized_friendly_cover_watch':
            run['friendlyCover'] = {k: data.get(k) for k in ('coverAssessmentSamples', 'weightedCoverSamples',
                'weightedCoverWithInputs', 'weightedCoverWithTarget', 'ordersIssued', 'samples', 'gateScope')}
        if scenario == 'serialized_combat_approach':
            run['combatObservation'] = {k: data.get(k) for k in ('combatQueryCount',
                'observedNativeEvents', 'combatValidated')}
        if scenario in {'serialized_cover', 'serialized_scored_cover'} and data.get('selectedCover'):
            run['selectedCover'] = data['selectedCover']
        if data.get('scenarioSourceSha256'):
            run['sourceHashes'] = dict(run['sourceHashes'] or {},
                                      scenario=data['scenarioSourceSha256'])
        for field in ('diagnosticBridgeSha256', 'nativeHelperSha256', 'nativePumpSha256'):
            if data.get(field):
                run['sourceHashes'] = dict(run['sourceHashes'] or {}, **{field: data[field]})
        runs.append(run)
        # Different goals/scenes/builds are not matched baseline/treatment trials.
        key = (scenario, run['executableSha256'], json.dumps(run['sourceHashes'], sort_keys=True), run['objective'])
        groups.setdefault(key, []).append(run)
    aggregates = []
    for (scenario, executable, hashes, objective), group in groups.items():
        samples = [r['simulationSeconds'] for r in group if r['result'] == 'pass' and
                   r['completeEvidence'] and r['simulationSeconds'] is not None]
        aggregates.append({'scenario': scenario, 'objective': objective, 'executableSha256': executable,
            'sourceHashes': json.loads(hashes), 'runs': len(group),
            'passed': sum(r['result'] == 'pass' and r['completeEvidence'] for r in group),
            'incompleteEvidenceRuns': sum(not r['completeEvidence'] for r in group),
            'simulationSeconds': {'n': len(samples), 'mean': statistics.mean(samples),
                'min': min(samples), 'max': max(samples), 'stdev': statistics.stdev(samples) if len(samples) > 1 else None}
                if samples else None})
    return {'runs': runs, 'aggregates': aggregates, 'releaseReady': False,
            'unverified': ['independent-client synchronization', 'combat baseline/treatment benefit',
                'death and ID reuse in live combat', 'match transition',
                'injected-script loss during combat/construction',
                'cover protection/firing access', 'construction placement, interruption and resource accounting'],
            'note': 'Pass describes the named bounded trial only. Retirement timing does not prove native cancellation. '
                    'No accuracy or multiplayer benefit is inferred.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = summarize(args.directories)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    report = ['Tactical validation: release NOT verified', '']
    for r in result['runs']:
        report.append(f"{r['result'].upper()}: {r['scenario']} ({r['directory']})" +
                  (f" — {r['error']}" if r['error'] else '') +
                  (' — evidence incomplete; metrics cover retained records only' if not r['completeEvidence'] else '') +
                  (f" — Audit: {r['auditCorrection']}" if r['auditCorrection'] else ''))
        metrics = r['metrics']
        report.append(f"  Recorded orders: {metrics['issued']} issued, {metrics['serialized']} serialized, "
                      f"{metrics['completed']} completion records; {metrics['retiredAtDeadline']} retired at/after "
                      f"deadline, {metrics['retiredBeforeDeadline']} before deadline, "
                      f"{metrics['retiredWithoutTiming']} without timing.")
        if 'army' in r:
            army = r['army']
            count = lambda value: len(value) if isinstance(value, list) else 'unknown'
            report.append(f"  Army: {count(army['selectedUnits'])} selected, "
                          f"{count(army['reachedUnits'])} with observed arrivals; "
                          f"{r['simulationSeconds']} simulation seconds, "
                          f"{army['runtimeStepMaxMs']} ms maximum runtime step.")
    report += ['', 'Unverified: ' + '; '.join(result['unverified']), '', result['note']]
    args.output.with_suffix('.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    print(json.dumps({'runs': len(result['runs']), 'releaseReady': False, 'report': str(args.output)}))


if __name__ == '__main__':
    main()
