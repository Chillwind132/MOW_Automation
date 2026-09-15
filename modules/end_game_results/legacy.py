"""Historical UI decoders for old records and diagnostics only.

Example for formatting an archived cell:
    from modules.end_game_results.legacy import plain, cell
    text = plain("<c(ffffff)>12 / 3")
    values = cell(text)["values_in_display_order"]

New integrations must use modules.end_game_results for final results;
these compatibility helpers are not an authoritative final-results API.
"""
import json
import re
import sqlite3
import struct
from contextlib import closing
from pathlib import Path


def plain(text):
    return re.sub(r'<[^>]*>', '', text).strip()


def cell(raw):
    if raw is None:
        return None
    text = plain(raw)
    values = None
    if re.fullmatch(r'-?\d+(?:\s*(?:/|\s)\s*-?\d+)*', text):
        values = [int(value) for value in re.findall(r'-?\d+', text)]
    return {'raw':raw, 'text':text, 'values_in_display_order':values}


def normalize_completion(raw, roster, participant_records):
    """Five-column terminal overlay, captured before Exit; unit details are optional."""
    nodes=raw['nodes']
    by_id={n['address']:n for n in nodes}
    roots=[n for n in nodes if n['name']=='mp_result' and n['vtable']==0xe2f8a4]
    if len(roots)!=1:
        raise ValueError('Expected one native end-of-match result overlay')
    children={}
    for n in nodes:
        children.setdefault(n['parent'],[]).append(n)
    def descendants(node):
        for child in children.get(node['address'],[]):
            yield child
            yield from descendants(child)
    content=list(descendants(roots[0]))
    titles=[plain(n['text']) for n in content if n['name']=='title' and n.get('text')]
    if len(titles)!=1 or titles[0] not in ('A Team wins!','B Team wins!'):
        raise ValueError('Unsupported or missing native winning-team title')
    row_nodes=[n for n in content if n['vtable']==0xd82e0c and (n['name'] in ('ta','tb') or re.fullmatch(r'p\d+',n['name'] or ''))]
    if len({n['parent'] for n in row_nodes})!=1:
        raise ValueError('Ambiguous terminal result table')
    columns=['player','victory_points','infantry','vehicles','score']
    headers={plain(n.get('text') or ''):n for n in content}
    labels=['Player','Victory Points','Infantry','Vehicles','Score']
    if any(label not in headers for label in labels):
        raise ValueError('Incomplete terminal result headers')
    bounds=lambda n:struct.unpack_from('<4i',bytes.fromhex(n['rawHeaderHex']),0x5c)
    ranges=[(key,bounds(headers[label])[0],bounds(headers[label])[2]) for key,label in zip(columns,labels)]
    records={p['native_member_id']:p for p in participant_records}
    rows=[]
    for n in row_nodes:
        fields={key:None for key in columns+['resources']}
        for child in descendants(n):
            if not child.get('text'):
                continue
            x=bounds(child)[0]
            owner=by_id[child['parent']]
            while owner['address']!=n['address']:
                x+=bounds(owner)[0]
                owner=by_id[owner['parent']]
            matching=[key for key,left,width in ranges if left<=x<left+width]
            if len(matching)!=1 or fields[matching[0]] is not None:
                raise ValueError('Unsupported terminal result cell layout')
            fields[matching[0]]=cell(child['text'])
        row={'row_id':n['name'],'kind':'team' if n['name'].startswith('t') else 'player','steam_id':None,'fields':fields}
        if row['kind']=='player':
            member=int(n['name'][1:])
            p=records.get(member)
            native=[r for r in roster['rows'] if r['memberIdRaw']==member]
            if not p or len(native)!=1 or native[0]['typeRaw']!=(2 if p['controller_kind']=='ai' else 1):
                raise ValueError('Terminal row has no approved native member')
            if p['steam_id'] is not None and str((native[0]['identityWordsRaw'][1]<<32)|native[0]['identityWordsRaw'][0])!=p['steam_id']:
                raise ValueError('Terminal Steam identity changed')
            row.update(participant_key=p['participant_key'],steam_id=p['steam_id'],controller_kind=p['controller_kind'],
                       native_member_id=member,identity_source='native_terminal_row_p_memberId_and_approved_session_roster')
        rows.append(row)
    if {r.get('participant_key') for r in rows if r['kind']=='player'}!={p['participant_key'] for p in participant_records if p['role']=='participant'}:
        raise ValueError('Incomplete terminal participant results')
    if len({r['row_id'] for r in rows})!=len(rows):
        raise ValueError('Duplicate terminal result row')
    if {r['row_id'] for r in rows if r['kind']=='team'}!={'ta','tb'}:
        raise ValueError('Incomplete terminal team results')
    for row in rows:
        fields=row['fields']
        for key,count in [('infantry',2),('vehicles',2),('score',1)]+([('victory_points',1)] if row['kind']=='team' else []):
            value=fields[key]
            if value is None or value['values_in_display_order'] is None or len(value['values_in_display_order'])!=count:
                raise ValueError('Incomplete terminal numeric results')
    return {'schema_version':2,'source':'native_in_game_result_ui','engine_outcome':{'winning_team':titles[0][0].lower(),'raw_title':titles[0]},
            'paired_counter_meanings':None,'rows':rows,'unavailable_fields':['resources']}


def normalize_statistics(raw, bindings=None):
    nodes = raw['nodes']
    by_id = {node['address']:node for node in nodes}
    if len(by_id) != len(nodes):
        raise ValueError('Repeated statistics node identity')
    children = {}
    for node in nodes:
        children.setdefault(node['parent'], []).append(node)
    tabs = [node for node in nodes if node['vtable'] == 0xe1ef14 and node['name'] == 'result_tab']
    if len(tabs) != 1:
        raise ValueError('Expected one native Game Result panel')
    def descendants(node):
        for child in children.get(node['address'], []):
            yield child
            yield from descendants(child)
    def bounds(node):
        return struct.unpack_from('<4i', bytes.fromhex(node['rawHeaderHex']), 0x5c)
    column_names = {'Player':'player', 'Victory Points':'victory_points', 'Infantry':'infantry',
                    'Vehicles':'vehicles', 'Score':'score', 'Resources':'resources'}
    content = list(descendants(tabs[0]))
    main_lists={n['parent'] for n in content if n['vtable']==0xd82e0c and n['name'] in ('ta','tb')}
    if len(main_lists)>1:
        raise ValueError('Ambiguous Game Result participant table')
    headers = [node for node in content if plain(node.get('text') or '') in column_names]
    if len(headers) != 6 or len({plain(node['text']) for node in headers}) != 6:
        raise ValueError('Unsupported or incomplete Game Result headers')
    columns = [(column_names[plain(node['text'])],bounds(node)[0],bounds(node)[2]) for node in headers]
    rows = []
    for row in content:
        parent = by_id.get(row['parent'])
        if row['vtable'] != 0xd82e0c or not parent or parent['vtable'] != 0xd8e30c:
            continue
        if main_lists and row['parent'] not in main_lists:
            continue  # Ignore optional unit details from older or explicitly full captures.
        fields = {key:None for key, _, _ in columns}
        for node in descendants(row):
            if not node.get('text'):
                continue
            x = bounds(node)[0]
            owner = by_id[node['parent']]
            while owner['address'] != row['address']:
                x += bounds(owner)[0]
                owner = by_id[owner['parent']]
            matching = [key for key,left,width in columns if left <= x < left+width]
            if len(matching) != 1:
                raise ValueError('Result cell does not align with an observed header')
            key = matching[0]
            if fields[key] is not None:
                raise ValueError('Multiple text nodes in result cell; unsupported layout')
            fields[key] = cell(node['text'])
        row_id = row['name']
        steam = row_id if re.fullmatch(r'\d{17}',row_id or '') else None
        kind = 'player' if steam or re.fullmatch(r'p\d+',row_id or '') else 'team' if row_id in ('ta','tb') else 'unknown'
        entry={'row_id':row_id,'kind':kind,'steam_id':steam,'fields':fields}
        if bindings is not None and kind=='player':
            matches=[b for b in bindings if b['result_row_id']==row_id]
            if len(matches)!=1:
                raise ValueError('Missing or ambiguous participant result binding')
            binding=matches[0]
            if steam!=binding['steam_id']:
                raise ValueError('Result binding Steam identity mismatch')
            entry.update(participant_key=binding['participant_key'],controller_kind=binding['controller_kind'],
                         identity_source=binding['source'])
        rows.append(entry)
    if not any(row['kind'] == 'player' for row in rows):
        raise ValueError('No player result rows observed; activate Game Result before export')
    if len({r['row_id'] for r in rows})!=len(rows):
        raise ValueError('Duplicate native result row identity')
    return {'schema_version':2 if bindings is not None else 1,'source':'native_statistics_ui', 'engine_outcome':None,
            'paired_counter_meanings':None,'rows':rows}


def result_bindings(raw, match):
    bindings=[]
    for p in match['participants']:
        if p['role']=='spectator':
            continue
        rows=[r for r in raw.get('backing',[]) if r['typeRaw']<18 and r['nativeIdRaw']==p['native_member_id']]
        if len(rows)!=1:
            raise ValueError('Missing native final backing participant')
        row=rows[0]
        steam=str((row['steamWordsRaw'][1]<<32)|row['steamWordsRaw'][0])
        if bool(row['aiFlagRaw'])!=(p['controller_kind']=='ai') or row['teamRaw']!=p['starting_team']:
            raise ValueError('Final backing participant kind/team mismatch')
        if (p['steam_id'] is None and steam!='0') or (p['steam_id'] is not None and steam!=p['steam_id']):
            raise ValueError('Final backing participant Steam identity mismatch')
        bindings.append({'result_row_id':p['steam_id'] or 'p'+str(p['native_member_id']),
            'participant_key':p['participant_key'],'steam_id':p['steam_id'],'controller_kind':p['controller_kind'],
            'source':'native_final_backing_memberId_aiFlag_steamWords_and_approved_roster'})
    return bindings


def save_result(database, match, raw, result):
    """An identical export is a no-op; a conflicting export cannot overwrite facts."""
    match_id = match['match_id']
    if match.get('participants') is not None:
        expected={p['participant_key'] for p in match['participants'] if p['role']=='participant'}
        observed=[r.get('participant_key') for r in result['rows'] if r['kind']=='player']
        if not expected or set(observed)!=expected or len(observed)!=len(expected) or any(r['kind']=='unknown' for r in result['rows']):
            raise ValueError('Result participant identities do not match the approved roster')
        identities={p['participant_key']:p for p in match['participants']}
        for row in result['rows']:
            if row['kind']=='player' and row['steam_id']!=identities[row['participant_key']]['steam_id']:
                raise ValueError('Participant Steam identity mismatch')
    else:
        roster = match['pre_quit_roster']
        if any(row['typeRaw']!=1 for row in roster['rows']):
            raise ValueError('AI export requires explicit participant identities')
        expected = {str((row['identityWordsRaw'][1] << 32) | row['identityWordsRaw'][0])
                    for row in roster['rows']}
        observed = {row['steam_id'] for row in result['rows'] if row['kind'] == 'player'}
        if observed != expected:
            raise ValueError('Result Steam identities do not match the captured quit roster')
    encoded = json.dumps(result, sort_keys=True, separators=(',',':'))
    Path(database).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute('CREATE TABLE IF NOT EXISTS matches (match_id TEXT PRIMARY KEY, observation_json TEXT NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS results (match_id TEXT PRIMARY KEY REFERENCES matches(match_id), normalized_json TEXT NOT NULL, raw_json TEXT NOT NULL)')
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('BEGIN IMMEDIATE')
        existing = connection.execute('SELECT normalized_json FROM results WHERE match_id=?',(match_id,)).fetchone()
        if existing:
            if existing[0] != encoded:
                raise ValueError('Conflicting results for existing match ID')
            stored=json.loads(connection.execute('SELECT observation_json FROM matches WHERE match_id=?',(match_id,)).fetchone()[0])
            for field in ('process_identity','host_session_id','native_game_start_time','participants'):
                if stored.get(field)!=match.get(field):
                    raise ValueError('Conflicting match association for existing result')
            created=False
        else:
            connection.execute('INSERT INTO matches VALUES (?,?)',(match_id,json.dumps(match,sort_keys=True)))
            connection.execute('INSERT INTO results VALUES (?,?,?)',(match_id,encoded,json.dumps(raw,sort_keys=True)))
            created=True
    from headless.match_ratings import refresh
    refresh(database)
    return created
