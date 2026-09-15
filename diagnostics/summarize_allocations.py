"""Summarize traced allocation cohorts beside external address-space samples."""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
import json
from pathlib import Path
import time

def owners(groups):
    result={}
    for g in groups:
        stack=g['stack']
        owner=('actor_fsm' if '0x83f7ef' in stack else
               'mesh_vertex_buffers' if '0x7749c9' in stack else
               'animation' if '0x6a9dc8' in stack or '0x6a3ec8' in stack else
               'audio_samples' if '0x5c43a6' in stack else
               'audio_stream_buffers' if '0x5c8085' in stack else
               'serialization_pools' if '0x6affcc' in stack else 'other_sampled')
        result[owner]=result.get(owner,0)+g['bytes']
    return {k:round(v/2**20,2) for k,v in result.items()}

def rows(path):
    if path.exists():
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                try:yield json.loads(line)
                except json.JSONDecodeError:continue  # Writer may still be active.

def summarize(directory):
    phases={}
    for r in rows(directory/'allocations.jsonl'):
        c=r['context'];key=(c.get('match_id'),c.get('phase'))
        p=phases.setdefault(key,{'match_id':key[0],'phase':key[1],'first_time':r['time']})
        p.setdefault('first_owners_mib',owners(r['groups']))
        p.update(last_time=r['time'],sampled_live_mib=round(r['sampled_live_bytes']/2**20,2),
                 counters=r['counters'],event_overflow=r['event_overflow'],errors=r['errors'],
                 owners_mib=owners(r['groups']),top_groups=r['groups'][:8])
    for r in rows(directory/'memory.jsonl'):
        key=(r.get('match_id'),r.get('phase'))
        if key in phases and r.get('PrivateUsage') is not None:
            p=phases[key]
            p.setdefault('first_private_mib',round(r['PrivateUsage']/2**20,2))
            p['last_private_mib']=round(r['PrivateUsage']/2**20,2)
    for r in rows(directory/'address_space.jsonl'):
        key=(r.get('match_id'),r.get('phase'))
        if key in phases:
            phases[key]['address_space_sample_time']=r['time']
            phases[key]['address_space_mib']={k:round(r[k]/2**20,2) for k in
                ('free_bytes','largest_free_region','reserved_bytes','committed_bytes')}
    events=[r['message']['payload'] for r in rows(directory/'trace_events.jsonl') if r['message']['type']=='send']
    controller_calls=[]
    for r in rows(directory/'events.jsonl'):
        payload=r.get('message',{}).get('payload',{})
        if payload.get('event')=='command_begin' and payload.get('action') not in ('probe','gate','results'):
            controller_calls.append({'time':r['time'],'action':payload.get('action'),
                'coverage':'Potentially unobserved allocations/frees inside controller JS interceptor callback'})
    result={'directory':str(directory),'phases':list(phases.values()),'events':events,
            'controller_native_call_coverage_gaps':controller_calls,
            'same_map_reload_option_observed':any(e['event']=='no_reload_caching_query' and e.get('present') for e in events),
            'allocation_failures':[e for e in events if e['event']=='allocation_failure'],
            'limitations':['Sampled live bytes are not total private commit or proof of a leak.',
                'Phase cohorts have the sampling interval uncertainty; frame-pointer stacks may be incomplete.',
                'Virtual address snapshots are external; low-level Windows hooks are disabled.',
                'Tracing changes timing and address layout; compare instrumented runs consistently.',
                'Cross-script native hooks miss calls issued inside the controller JS interceptor callback (isolated x86 reproduction).',
                'Tracked live entries may therefore be stale after controller native calls, especially audio reset; these cohorts cannot by themselves prove retained memory.']}
    (directory/'allocation_summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path)
    p.add_argument('--follow',action='store_true',help='Refresh report every 30 seconds until the runner finishes (up to four hours)')
    a=p.parse_args()
    if a.follow:
        deadline=time.monotonic()+4*3600
        while True:
            result=summarize(a.directory)
            if (a.directory/'summary.json').exists() or time.monotonic()>=deadline:break
            time.sleep(30)
        print('Final allocation report:',a.directory/'allocation_summary.json')
        raise SystemExit(0)
    result=summarize(a.directory)
    print(json.dumps({**result,'phases':[{k:v for k,v in x.items() if k!='top_groups'} for x in result['phases']]},indent=2))
