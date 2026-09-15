"""Compare repeat-match memory at declared elapsed times using saved evidence."""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sqlite3
import time
from headless_host import ROOT
from summarize_allocations import rows


def compare(directories, observers, journal):
    matches={}
    for directory in directories:
        for r in rows(directory/'memory.jsonl'):
            if r.get('phase')!='playing' or r.get('PrivateUsage') is None or not r.get('match_id'):continue
            key=(r['pid'],r['match_id'])
            item=matches.setdefault(key,{'pid':key[0],'match_id':key[1],'directories':[],
                '_memory':[],'_space':[],'_owners':[],'_terminal':[]})
            if str(directory) not in item['directories']:item['directories'].append(str(directory))
            item['_memory'].append({'time':r['time'],'private':r['PrivateUsage']})
        for r in rows(directory/'address_space.jsonl'):
            key=(r.get('pid'),r.get('match_id'))
            if key in matches and r.get('phase')=='playing':
                matches[key]['_space'].append({k:r.get(k) for k in
                    ['time','free_bytes','largest_free_region','reserved_bytes','committed_bytes']})
        for r in rows(directory/'activity.jsonl'):
            if r.get('manager_state')==3:
                for key,item in matches.items():
                    if key[1]==r.get('match_id'):item['_terminal'].append(r)
    for r in rows(observers/'engine_owners.jsonl'):
        key=(r.get('identity',{}).get('pid'),r.get('match_id'))
        if key in matches and r.get('phase')=='playing':matches[key]['_owners'].append(r)
    censuses={}
    for pid in {key[0] for key in matches}:
        for path in (observers/'resource_census').glob(f'resources_{pid}_*.json'):
            try:r=json.loads(path.read_text())
            except (OSError,ValueError):continue
            context=r.get('context',{});key=(pid,context.get('match_id'))
            if key not in matches or context.get('phase')!='playing' or not r.get('completed'):continue
            if key not in censuses or r['started']<censuses[key][1]['started']:censuses[key]=(path,r)
    result={'generated_at':time.time(),'matches':[],'limitations':[
        'Offsets are relative to each first playing memory sample, not an identical engine tick.',
        'Observer/resource snapshots are non-atomic; sample ages are reported.',
        'Resource census covers named texture/animation payloads, not every engine allocation.',
        'Allocation/free wrapper counters count calls, not live blocks or bytes.',
        'Instrumentation overhead is not subtracted. This comparison uses external counters, not traced survivor cohorts.']}
    previous_resources={}
    with sqlite3.connect(journal.resolve().as_uri()+'?mode=ro',uri=True) as db:
        for key,item in sorted(matches.items(),key=lambda pair:min(r['time'] for r in pair[1]['_memory'])):
            memory=sorted(item.pop('_memory'),key=lambda r:r['time']);space=item.pop('_space');owners=item.pop('_owners');terminal=item.pop('_terminal')
            first=memory[0]['time'];item.update(first_memory_time=first,first_private_mib=round(memory[0]['private']/2**20,2),
                peak_private_mib=round(max(r['private'] for r in memory)/2**20,2),latest_memory_time=memory[-1]['time'],samples=[])
            if space:item['minimum_largest_free_mib']=round(min(r['largest_free_region'] for r in space)/2**20,2)
            for offset in [30,60,120]:
                eligible=[r for r in memory if r['time']>=first+offset]
                if not eligible:continue
                m=eligible[0];sample={'requested_offset_s':offset,'elapsed_s':round(m['time']-first,2),'private_mib':round(m['private']/2**20,2)}
                if space:
                    v=min(space,key=lambda r:abs(r['time']-m['time']));sample['va_age_s']=round(m['time']-v['time'],2)
                    sample.update({k+'_mib':round(v[k]/2**20,2) for k in ['free_bytes','largest_free_region','reserved_bytes','committed_bytes']})
                if owners:
                    o=min(owners,key=lambda r:abs(r['time']-m['time']));sample.update(owners=o['owners'],owner_age_s=round(m['time']-o['time'],2))
                item['samples'].append(sample)
            row=db.execute('SELECT state FROM match_journal WHERE match_id=?',(key[1],)).fetchone()
            item['journal_state']=row[0] if row else None
            item['completion_saved']=bool(db.execute('SELECT 1 FROM completion_captures WHERE match_id=?',(key[1],)).fetchone())
            if terminal:item['terminal_hud']=min(terminal,key=lambda r:r['time'])['hud']
            if key in censuses:
                path,c=censuses[key];names={x['name'] for x in c['loaded']}
                resource={'file':str(path),'started':c['started'],'loaded_count':c['loaded_count'],'types':c['loaded_by_vtable'],
                    'distinct_hardware_texture_addresses':len({x['surface']['texture_address'] for x in c['loaded']
                        if x.get('surface') and x['surface']['texture_address']!='0x0'})}
                if key[0] in previous_resources:
                    resource.update(added_names=sorted(names-previous_resources[key[0]]),removed_names=sorted(previous_resources[key[0]]-names))
                previous_resources[key[0]]=names;item['resources']=resource
            result['matches'].append(item)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories',type=Path,nargs='+')
    parser.add_argument('--observers',type=Path,default=ROOT/'validation/overnight_20260906_003755')
    parser.add_argument('--journal',type=Path,default=ROOT/'data/rankbot.sqlite3')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=compare(args.directories,args.observers,args.journal)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2))
    for item in result['matches']:
        minute=next((s['private_mib'] for s in item['samples'] if s['requested_offset_s']==60),None)
        print(json.dumps({'pid':item['pid'],'match':item['match_id'],'one_minute_private_mib':minute,
            'peak_private_mib':item['peak_private_mib'],'minimum_largest_free_mib':item.get('minimum_largest_free_mib'),
            'journal_state':item['journal_state'],'completion_saved':item['completion_saved']}))


if __name__=='__main__':main()
