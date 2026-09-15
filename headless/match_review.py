"""Read-only SQLite queries and a self-contained, searchable match review page."""
from contextlib import closing
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile


def load_matches(database):
    path=Path(database).resolve()
    if not path.is_file():
        raise ValueError(f'No match database yet: {path}')
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            records=[]
            if {'matches','results'}<=tables:
                records=db.execute('SELECT m.match_id,m.observation_json,r.normalized_json FROM matches m JOIN results r USING(match_id)').fetchall()
            exported={row[0] for row in records}
            progress={}
            progress_metadata={}
            observation_events={}
            if {'completion_captures','match_journal'}<=tables:
                for mid,snapshot,normalized,captured_at in db.execute('''
                    SELECT c.match_id,j.snapshot_json,c.normalized_json,c.captured_at
                    FROM completion_captures c JOIN match_journal j USING(match_id)'''):
                    if mid in exported:
                        continue
                    metadata=json.loads(snapshot)
                    metadata.update(completion_captured_at=captured_at,
                                    trigger='normal_completion_observed')
                    records.append((mid,json.dumps(metadata),normalized))
            known={row[0] for row in records}
            if 'match_snapshots' in tables:
                for mid,recorded,sampled,reason,encoded in db.execute('''
                        SELECT match_id,recorded_at,sampled_at,reason,snapshot_json
                        FROM match_snapshots ORDER BY sequence'''):
                    snapshot=json.loads(encoded);sample=snapshot.get('sample') or {}
                    from modules.live_game_data.statistics import normalize_live_statistics
                    statistics=normalize_live_statistics(snapshot['metadata'],sample.get('live'))
                    progress_metadata[mid]=snapshot['metadata']
                    progress.setdefault(mid,[]).append(dict(recorded_at=recorded,sampled_at=sampled,reason=reason,
                        hud=(sample.get('live') or {}).get('hud',[]),
                        roster=[{k:r.get(k) for k in ('displayName','memberIdRaw','typeRaw','teamRaw')}
                                for r in (sample.get('roster') or {}).get('rows',[])],
                        per_player_statistics_status=statistics['status'],player_statistics=statistics))
                for mid,metadata in progress_metadata.items():
                    if mid in known:continue
                    rows=[]
                    for p in metadata.get('participants',[]):
                        if p.get('role')!='participant':continue
                        fields={k:None for k in ('player','victory_points','infantry','vehicles','score','resources')}
                        fields['player']={'text':p.get('display_name')}
                        rows.append(dict(kind='player',row_id=p['participant_key'],participant_key=p['participant_key'],
                                         steam_id=p.get('steam_id'),fields=fields))
                    records.append((mid,json.dumps(metadata),json.dumps(dict(rows=rows,engine_outcome=None))))
            if 'match_observation_events' in tables:
                for mid,stamp,kind,evidence in db.execute('''SELECT match_id,observed_at,kind,evidence_json
                        FROM match_observation_events ORDER BY observed_at,event_id'''):
                    observation_events.setdefault(mid,[]).append(dict(observed_at=stamp,kind=kind,evidence=json.loads(evidence)))
            from match_adjudication import read_adjudications
            adjudications=read_adjudications(db)
    except sqlite3.Error as error:
        raise ValueError(f'Cannot read saved matches: {error}') from error
    output=[]
    for mid,observation,normalized in records:
        m=json.loads(observation);r=json.loads(normalized)
        if mid in adjudications:m['operator_adjudication']=adjudications[mid]
        roster=m.get('loaded_roster') or m.get('starting_roster') or m.get('pre_quit_roster') or {}
        stamp=next((m[k] for k in ('results_observed_at','observed_at','completion_captured_at','loaded_at','created_at') if m.get(k)),None)
        from match_outcomes import automatic_winner,final_vp
        winner=automatic_winner(r,m,path)
        target=final_vp(r,m,path)
        capture_stage='lobby_results' if mid in exported else 'progress_snapshot' if mid in progress and mid not in known else 'finish_capture'
        if capture_stage=='progress_snapshot':winner=None
        adjudication=m.get('operator_adjudication') or {}
        manual_winner=False
        if (adjudication.get('source')=='explicit_user_confirmation' and adjudication.get('match_id')==mid
                and adjudication.get('winning_team') in ('a','b') and winner in (None,adjudication['winning_team'])):
            winner=adjudication['winning_team']
            manual_winner=True
        output.append({'id':mid,'timestamp':stamp,'date':datetime.fromtimestamp(stamp,timezone.utc).isoformat() if stamp else None,
            'map':m.get('map') or roster.get('map'),'settings':m.get('effective_settings') or roster.get('settings') or {},
            'trigger':m.get('trigger'),'winner':winner,'outcome':f'Team {winner.upper()} wins' if winner else 'Winner undetermined',
            'capture_stage':capture_stage,'final_vp':target,
            'final_results_source':r.get('source'),
            'replay':r.get('replay'),
            'statistics_check':r.get('statistics_check'),
            'native_final_statistics':r.get('native_final_statistics'),
            'progress_snapshots':progress.get(mid,[]),'observation_events':observation_events.get(mid,[]),
            'outcome_source':'explicit_user_confirmation' if manual_winner else 'native_result' if winner else None,
            'players':sum(x['kind']=='player' for x in r['rows']),
            'rows':r['rows'],'participants':m.get('participants') or [],'metadata':m})
    from match_ratings import stored
    ratings=stored(database).get('matches',{})
    from modules.live_game_data import history
    events={}
    for event in history(database):
        events.setdefault(event['match_id'],[]).append(event)
    for match in output:
        match['rating']=ratings.get(match['id'],{'status':'not_processed','updates':{}})
        match['participation_events']=events.get(match['id'],[])
        from match_review_presentation import decorate
        decorate(match,database)
    return sorted(output,key=lambda r:(r['timestamp'] or 0,r['id']),reverse=True)


def print_matches(records):
    if not records:
        return 'No saved matches yet.'
    lines=['DATE (UTC)           PLAYERS  OUTCOME              MAP / MATCH ID']
    for r in records:
        lines.append(f"{(r['date'] or 'unknown')[:19]:19}  {r['players']:7}  {r['outcome']:20} {r['map'] or 'unknown'} / {r['id']}")
    return '\n'.join(lines)


def render_review(records,database,service_token=None):
    from match_review_presentation import rank_icons
    payload={'matches':records,'database':str(Path(database).resolve()),'generated_at':datetime.now(timezone.utc).isoformat(),
             'service_token':service_token,'rank_icons':rank_icons()}
    # Prevent names/maps from terminating the JSON script element. DOM uses textContent.
    encoded=json.dumps(payload,ensure_ascii=True).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return PAGE.replace('__MATCH_DATA__',encoded)


def write_review(records,path,database):
    path=Path(path).resolve()
    page=render_review(records,database)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False,suffix='.html.tmp') as output:
            temporary=Path(output.name)
            output.write(page)
        os.replace(temporary,path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return path


PAGE=r'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MOW · Match review</title>
<style>
:root{color-scheme:dark;font:15px/1.5 system-ui,sans-serif;background:#0c111b;color:#e8edf6}
*{box-sizing:border-box}body{margin:0;width:100%;min-height:100dvh;padding:20px;display:flex;flex-direction:column}h1{font-size:30px;margin:0}h2{font-size:20px;margin:0 0 12px}p{margin:6px 0 20px;color:#9eaec5}.eyebrow{color:#73d8bd;font-size:12px;letter-spacing:2px;font-weight:700}header{display:flex;justify-content:space-between;align-items:center;gap:20px}.pill{border:1px solid #315548;border-radius:20px;padding:5px 12px;color:#8cdfbb;font-size:12px}
.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:26px 0}.card,section{background:#131c29;border:1px solid #253247;border-radius:12px}.card{padding:16px 20px}.card strong{display:block;font-size:29px}.muted{color:#9eaec5;font-size:13px}
.tools{display:flex;gap:12px;margin-bottom:16px}input,select,button{font:inherit;border:1px solid #354863;border-radius:7px;background:#192638;color:#e8edf6;padding:10px}input{flex:1;min-width:80px}button{cursor:pointer}button:hover{background:#293e58}.layout{display:grid;flex:1;grid-template-columns:minmax(310px,0.9fr) minmax(0,1.5fr);gap:18px}section{padding:20px;min-width:0}#list{max-height:max(280px,calc(100dvh - 340px));overflow:auto}.match{display:block;width:100%;text-align:left;margin:0 0 10px;padding:14px;line-height:1.5}.match[aria-pressed=true]{border-color:#73d8bd;background:#17332f}.match span{display:block}.match .name{font-weight:650}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:10px 8px;border-bottom:1px solid #2a3547;white-space:nowrap}th{color:#a9bbd0;font-weight:500}.team td{background:#1c2b3e;font-weight:650}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;color:#b9c8da;max-height:360px;overflow:auto}details{margin-top:20px}summary{cursor:pointer;color:#9ed8ff}#context{overflow-wrap:anywhere}footer{margin-top:20px;color:#8495ad;font-size:12px;overflow-wrap:anywhere}@media(max-width:950px){.layout{grid-template-columns:1fr}#list{max-height:300px}body{padding:16px}.metrics{gap:8px}.card{padding:12px}.tools{flex-wrap:wrap}}
</style>
<style>textarea{display:block;width:100%;font:inherit;background:#192638;color:#e8edf6;border:1px solid #354863;border-radius:7px;padding:10px;margin:8px 0 14px}fieldset{border:0;padding:0;margin:0}button:disabled{opacity:.5;cursor:default}.decisionTeams{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:0 0 20px}.decisionTeams button[aria-pressed=true]{border-color:#73d8bd;background:#17332f}.decisionMessage:empty{display:none}caption{text-align:left;font-size:12px;color:#9eaec5;padding:0 0 12px}.rankIcon{display:block;object-fit:contain;image-rendering:auto}.departure{color:#efba83;white-space:normal;min-width:130px;font-size:12px}.departedPlayer{color:#efba83}.tools{margin-top:22px}#refreshHint:empty{display:none}.layout{grid-template-columns:clamp(260px,22vw,360px) minmax(0,1fr)}th,td{padding:10px 6px}#context{font-size:13px}#rows td:first-child{font-weight:600}@media(max-width:1050px){.layout{grid-template-columns:1fr}}
.tools select:focus{outline:none;box-shadow:none;border-color:#354863;border-radius:7px}
.tools select:focus-visible{border-color:#73d8bd}
.matchTile{position:relative}.matchTile .match{padding-right:62px}.matchConfig{position:absolute;right:9px;top:9px;padding:5px 8px;font-size:12px}
.manualBadge{color:#efba83;font-weight:650;margin-top:5px}
#decisionSection{position:fixed;inset:0 0 0 auto;margin:0;width:min(440px,100vw);max-width:100vw;height:100dvh;max-height:100dvh;padding:24px;border:0;border-left:1px solid #354863;background:#131c29;color:#e8edf6;overflow-y:auto;box-shadow:-16px 0 48px #0005}
#decisionSection[open]{animation:drawerIn .18s ease-out}#decisionSection::backdrop{background:#0007}
.drawerHeader{display:flex;align-items:flex-start;gap:12px;margin-bottom:24px}.drawerHeader h2{flex:1}.drawerHeader button{padding:5px 10px}
#manualReason{margin-top:20px;padding:16px;border:1px solid #745938;border-radius:7px;background:#29251e}#manualReason h3{margin:0 0 8px;color:#efba83;font-size:15px}#manualReason p{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;color:#e8edf6}#manualReason .muted{display:block;margin-bottom:8px}
#decisionStatus{white-space:pre-wrap}#winnerConfirm{width:100%}
@keyframes drawerIn{from{transform:translateX(100%)}to{transform:translateX(0)}}@media(prefers-reduced-motion:reduce){#decisionSection[open]{animation:none}}
/* Fit desktop panels to the remaining viewport; scroll their contents. */
@media(min-width:1051px) and (min-height:600px){
 body{height:100dvh;min-height:0}
 body>header,body>p,body>.tools{flex-shrink:0}
 .layout{min-height:0;grid-template-rows:minmax(0,1fr)}
 .layout>section{display:flex;flex-direction:column;min-height:0}
 .layout>section>h2,.layout>section>p{flex-shrink:0}
 #list,.layout .scroll{flex:1;min-height:0;max-height:none;overflow:auto}

}
</style>
<style>
[hidden]{display:none!important}
.layout{grid-template-columns:180px clamp(280px,23vw,380px) minmax(0,1fr)}
.navigation{background:#131c29;border:1px solid #253247;border-radius:12px;padding:16px}
.navigation .match{padding:12px;font-weight:600}.navigation .muted{display:block;margin:2px 0 16px}
.ratingStats{display:flex;gap:28px;flex-wrap:wrap;padding:0 0 20px;border-bottom:1px solid #2a3547;margin-bottom:20px}
.ratingStats strong{display:block;font-size:24px;font-weight:650}.positive{color:#73d8bd}.negative{color:#efba83}
.ratingRow{display:grid;grid-template-columns:28px minmax(0,1fr) auto;align-items:center;gap:8px}
.ratingRow .name{overflow-wrap:anywhere}.ratingValue{text-align:right}.ratingValue strong{font-size:18px}
#ratingContent{overflow:auto;min-height:0}#ratingContext{overflow-wrap:anywhere}
.trendChart{width:100%;height:180px;display:block;color:#73d8bd}.trendLabels{display:flex;justify-content:space-between;margin-bottom:24px}
.ratingHeading{font-size:15px;margin:0 0 12px}.historyLink{padding:0;border:0;background:none;color:#e8edf6;text-align:left}.historyLink:hover{text-decoration:underline;background:none}
button:focus-visible{outline:2px solid #73d8bd;outline-offset:2px}
@media(max-width:1200px){.layout{grid-template-columns:150px 280px minmax(0,1fr)}}
@media(max-width:1050px){.layout{grid-template-columns:260px minmax(0,1fr)}.navigation{grid-column:1/-1;display:flex;gap:10px}.navigation .muted{display:none}.navigation .match{width:auto;margin:0}#list{max-height:65dvh}}
@media(max-width:700px){.layout{grid-template-columns:minmax(0,1fr)}#list{max-height:280px}.ratingStats{gap:20px}.tools input{flex-basis:100%}}
</style>
<style>
.headerActions{display:flex;align-items:center;gap:12px}#eloOpen{color:#73d8bd;border-color:#426f65;font-weight:700}
#eloDialog{width:min(640px,calc(100vw - 32px));max-height:calc(100dvh - 32px);padding:24px;border:1px solid #354863;border-radius:16px;background:#131c29;color:#e8edf6;overflow:auto;box-shadow:0 24px 80px #0008}
#eloDialog::backdrop{background:#050a12bb}#eloDialog h2{margin:0}#eloDialog .drawerHeader{margin-bottom:8px}#eloDialog p{font-size:13px;margin:8px 0 16px}
.eloFlow{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;align-items:center;gap:8px;margin:20px 0}.eloStep{text-align:center;background:#192638;border:1px solid #354863;border-radius:10px;padding:12px 6px;font-size:12px}.eloStep strong{display:block;font-size:19px;color:#73d8bd}.eloArrow{color:#73d8bd}
.eloFactors{display:grid;grid-template-columns:1fr 1fr;gap:12px}.eloFactor{border-left:3px solid #73d8bd;padding:0 12px}.eloFactor strong{font-size:14px}#eloDialog .eloFactor p{margin:4px 0 12px}
.eloFormula{font-size:13px;color:#73d8bd}#eloDialog details{margin-top:14px;font-size:13px}#eloDialog details p{margin-bottom:0}
@media(max-width:480px){#eloDialog{padding:18px}.eloFactors{grid-template-columns:1fr}.eloStep strong{font-size:16px}.eloFlow{gap:4px}.headerActions{gap:6px}}
</style>
<header><div><div class="eyebrow">MEN OF WAR · LOCAL HISTORY</div><h1>Match review</h1></div><div class="headerActions"><span id="modeLabel" class="pill">Read-only snapshot</span><button id="eloOpen" type="button" aria-haspopup="dialog" aria-controls="eloDialog">ELO</button></div></header>
<dialog id="eloDialog" aria-labelledby="eloTitle">
<div class="drawerHeader"><h2 id="eloTitle">How your rating moves</h2><button id="eloClose" type="button" aria-label="Close rating explanation" autofocus>×</button></div>
<div class="eloFlow" aria-label="Start at 1000, update after each eligible result, then rank by current rating"><div class="eloStep"><strong>1000</strong>Starting rating</div><span class="eloArrow" aria-hidden="true">→</span><div class="eloStep"><strong>Win / loss</strong>Eligible match</div><span class="eloArrow" aria-hidden="true">→</span><div class="eloStep"><strong>↑ / ↓</strong>Updated rating</div></div>
<div class="eloFactors">
<div class="eloFactor"><strong>01 · Team result</strong><p>Winners gain rating; losers lose rating.</p></div>
<div class="eloFactor"><strong>02 · Strength of both teams</strong><p>Beating a stronger team gives a bigger boost.</p></div>
<div class="eloFactor"><strong>03 · Rating uncertainty</strong><p>Teammates can receive different changes from the same win.</p></div>
<div class="eloFactor"><strong>04 · Team size</strong><p>Larger teams generally mean smaller individual changes.</p></div>
</div>
<details><summary>Formula</summary><p class="eloFormula">Displayed rating = 1000 + 40 × (estimated skill − 25)</p><p><strong>Starting point</strong><br>Every player begins with an estimated skill of 25, which appears as 1000 on the leaderboard. Each skill point is worth 40 rating points: a skill estimate of 27.5 gives a rating of 1100.</p><p><strong>After each rated match</strong><br>The model updates your skill estimate using the team result, both teams’ strength and each player’s uncertainty. The formula above converts that estimate into the rating you see. The leaderboard places higher ratings first.</p><p><strong>Provisional ratings</strong><br>Uncertainty starts at 8.33 and describes how confidently the model estimates your skill. Your rating stays provisional while uncertainty is above 6. As rated results build a clearer picture of your skill, uncertainty usually falls; the provisional label clears when it reaches 6 or below.</p></details>
</dialog>
<p id="refreshHint">Search matches and review player results.</p>
<div class="tools"><input id="search" aria-label="Search matches" placeholder="Search player, map, Steam ID or match ID…"><select id="players" aria-label="Players"><option value="all">All players</option><option value="human" selected title="At least one human player on each team; bots may also participate">Players only</option></select><select id="outcome" aria-label="Outcome"><option value="all">All outcomes</option><option value="win">Confirmed winner</option><option value="other">No confirmed winner</option></select></div>
<div class="layout"><nav class="navigation" aria-label="Review views"><span class="muted">Local history</span><button id="savedGamesNav" class="match" type="button" aria-pressed="true">Saved Games</button><button id="playerRatingNav" class="match" type="button" aria-pressed="false">Player Rating</button></nav><section><h2 id="listTitle">Saved games</h2><div id="list"></div></section><section id="matchPanel"><h2 id="title">Select a match</h2><p id="context"></p><div class="scroll"><table><caption id="tableContext"></caption><thead><tr><th>Player</th><th title="In-game rank, based on games played">Rank</th><th>Army Mode</th><th>Player Army</th><th>Team</th><th title="Victory points earned by this player's team">Team VP</th><th title="Enemy kills / losses">Infantry</th><th title="Enemy kills / losses">Vehicles</th><th>Score</th><th title="Ordinary / special resources">Resources</th><th title="Estimated skill; provisional ratings have higher uncertainty">Skill</th><th>Change</th><th>Status</th></tr></thead><tbody id="rows"></tbody></table><aside id="manualReason" hidden><h3>Manual winner decision</h3><span id="manualReasonMeta" class="muted"></span><p id="manualReasonText"></p></aside></div></section><section id="ratingPanel" hidden><h2 id="ratingTitle">Player Rating</h2><p id="ratingContext"></p><div id="ratingContent"><div id="ratingStats" class="ratingStats"></div><h3 class="ratingHeading">Rating trend</h3><div id="ratingTrend"></div><h3 class="ratingHeading">Match history</h3><div class="scroll"><table><caption>Saved results · newest first</caption><thead><tr><th>Date</th><th>Map</th><th>Result</th><th>Rating</th><th>Change</th></tr></thead><tbody id="ratingHistory"></tbody></table></div></div></section></div>
<dialog id="decisionSection" aria-labelledby="decisionTitle"><div class="drawerHeader"><h2 id="decisionTitle">Set manual winner</h2><button id="decisionClose" type="button" aria-label="Close winner settings">×</button></div>
<fieldset id="decisionFields"><div class="decisionTeams"><button id="winnerA" type="button" aria-pressed="false">Team A</button><button id="winnerB" type="button" aria-pressed="false">Team B</button></div>
<label for="winnerReason">Reason for the decision (required)</label>
<textarea id="winnerReason" required maxlength="2000" rows="3" placeholder="For example: Team B conceded after their players left."></textarea>
<button id="winnerConfirm" type="button" disabled>Confirm winner</button></fieldset>
<p id="decisionStatus"></p><p id="decisionMessage" class="decisionMessage" role="status" aria-live="polite"></p></dialog>
<script id="data" type="application/json">__MATCH_DATA__</script>
<script>
'use strict';
const data=JSON.parse(document.getElementById('data').textContent), all=data.matches;
const el=id=>document.getElementById(id), text=(id,value)=>{el(id).textContent=value};
el('eloOpen').onclick=()=>el('eloDialog').showModal();
el('eloClose').onclick=()=>el('eloDialog').close();
el('eloDialog').addEventListener('click',event=>{if(event.target!==el('eloDialog'))return;const r=el('eloDialog').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)el('eloDialog').close()});
const mapName=m=>(m||'Map unavailable').replace(/^multi\//,'').replace(/:/g,' · ').replace(/_/g,' ');
let selected=all[0]?.id,saving=false,decisionMatch=null,activeView='games',selectedPlayer=null;
const drafts=new Map(),service=Boolean(data.service_token)&&location.protocol==='http:';
if(service){el('modeLabel').hidden=true;text('refreshHint','')}
function show(m){
 const decision=m.metadata?.operator_adjudication;
 const manual=m.outcome_source==='explicit_user_confirmation';
 el('manualReason').hidden=!decision;
 if(decision){
  text('manualReasonMeta',`Team ${decision.winning_team.toUpperCase()} · ${new Date(decision.confirmed_at*1000).toLocaleString()}${manual?'':' · Superseded by completed result'}`);
  text('manualReasonText',decision.reason);
 }
 text('decisionTitle',`Winner settings · ${mapName(m.map)}`);
 el('decisionFields').disabled=!service||saving||Boolean(m.winner);
 const draft=decision?{reason:decision.reason,team:decision.winning_team}:drafts.get(m.id)||{reason:'',team:null};
 el('winnerReason').value=draft.reason;el('winnerReason').setCustomValidity('');
 text('decisionStatus',m.winner?(manual?'This manual decision has been confirmed.': 'The recorded winner reached Final VP.') : !service?'Start the local review service to confirm a winner.':'Choose a team and enter a reason. The decision is saved only when you confirm.');
 updateSelection(draft);
 const progress=m.display_source==='progress';
 text('title',m.winner?m.outcome:progress?'Awaiting replay':m.outcome);
 const stamp=m.display_sampled_at?` · Updated ${new Date(m.display_sampled_at*1000).toLocaleTimeString()}`:'';
 text('context',`${m.date?new Date(m.date).toLocaleString():'Time unavailable'} · ${mapName(m.map)} · ${m.players} players${stamp}`);
 if(m.outcome_source==='explicit_user_confirmation')text('title',`${m.outcome} (manual decision)`);
 const settings=m.settings||{};
 text('tableContext',[m.display_source==='replay'?'Replay results':progress?'Live snapshot':'Saved results',m.final_vp!=null?`Final VP: ${m.final_vp}`:null,settings.totalManpower!=null?`${settings.totalManpower} MP`:null,settings.preparationTime!=null?`${settings.preparationTime}s preparation`:null].filter(Boolean).join(' · '));
 el('rows').replaceChildren();
 const cell=(tr,v,title)=>{const td=document.createElement('td');td.textContent=v;if(title)td.title=title;tr.append(td);return td};
 for(const r of m.player_rows||(m.display_rows||m.rows).filter(r=>r.kind==='player')){
  const tr=document.createElement('tr');if(r.kind==='team')tr.className='team';
  const p=m.participants.find(p=>(r.participant_key&&p.participant_key===r.participant_key)||(r.steam_id&&p.steam_id===r.steam_id));
  const departure=m.departures?.[r.steam_id];
  const name=cell(tr,r.fields.player?.text||r.row_id,r.steam_id?`Steam ID: ${r.steam_id}`:null);
  const rank=cell(tr,'');const badge=m.ranks?.[r.steam_id];
  if(r.kind==='player'&&badge&&data.rank_icons?.[badge.tier]){
   const img=document.createElement('img');img.src=data.rank_icons[badge.tier];
   img.alt=`${badge.games_played} games played`;img.title=`${badge.games_played} games played`;
   img.className='rankIcon';img.width=16;img.height=20;img.tabIndex=0;rank.append(img);
  }else rank.textContent='—';
  cell(tr,m.army_mode||'—');
  cell(tr,r.player_army||'—');
  cell(tr,r.team_label||'—');
  for(const key of ['victory_points','infantry','vehicles','score','resources']){
   const f=r.fields[key];cell(tr,f?.values_in_display_order?.join(' / ')??f?.text??'—');
  }
  const rating=m.rating?.updates?.[r.steam_id];
  cell(tr,rating?`${Math.round(rating.after.value)}${rating.after.provisional?' (provisional)':''}`:'—',rating?`Previous skill: ${Math.round(rating.before.value)}`:null);
  const delta=rating?Math.round(rating.after.value)-Math.round(rating.before.value):null;
  cell(tr,delta===null?'—':`${delta>=0?'+':''}${delta}`);
  const status=cell(tr,departure?`${departure.label} · ${departure.reason}${departure.returned?' · Rejoined':''}`:p?.controller_kind==='ai'?'AI':r.kind==='team'?'—':progress?'Last observed':'—');
  if(departure){status.className='departure';name.className='departedPlayer'}
  el('rows').append(tr);
 }
}
function render(){
 const ratingView=activeView==='ratings';
 el('matchPanel').hidden=ratingView;el('ratingPanel').hidden=!ratingView;
 el('players').hidden=ratingView;el('outcome').hidden=ratingView;
 el('search').placeholder=ratingView?'Search player or Steam ID…':'Search player, map, Steam ID or match ID…';
 el('search').setAttribute('aria-label',ratingView?'Search players':'Search matches');
 el('savedGamesNav').setAttribute('aria-pressed',String(!ratingView));el('playerRatingNav').setAttribute('aria-pressed',String(ratingView));
 if(ratingView){renderRatings();return}
 const query=el('search').value.toLowerCase().trim(),mode=el('outcome').value;
 const humansOnly=el('players').value==='human';
 const filtered=all.filter(m=>(!humansOnly||m.has_human_opponents===true)&&(mode==='all'||(mode==='win'?!!m.winner:!m.winner))&&(!query||JSON.stringify(m).toLowerCase().includes(query)));
 text('listTitle',`Saved games (${filtered.length})`);el('list').replaceChildren();
 if(!filtered.some(m=>m.id===selected))selected=filtered[0]?.id;
 if(decisionMatch&&decisionMatch!==selected)closeDecision();
 for(const m of filtered){
  const tile=document.createElement('div');tile.className='matchTile';
  const b=document.createElement('button');b.className='match';b.setAttribute('aria-pressed',String(m.id===selected));
  for(const [label,cls] of [[mapName(m.map),'name'],[`${m.date?new Date(m.date).toLocaleString():'Time unavailable'} · ${m.players} players`,'muted'],[m.outcome,'muted']]){
   const span=document.createElement('span');span.className=cls;span.textContent=label;b.append(span);
  }
  if(m.outcome_source==='explicit_user_confirmation'){const badge=document.createElement('span');badge.className='manualBadge';badge.textContent='Manual winner';b.append(badge)}
  b.onclick=()=>{selected=m.id;text('decisionMessage','');render()};tile.append(b);
  const config=document.createElement('button');config.className='matchConfig';config.textContent='⚙';config.title='Winner settings';config.setAttribute('aria-label',`Winner settings · ${mapName(m.map)}`);
  config.onclick=()=>{selected=m.id;decisionMatch=m.id;text('decisionMessage','');render();el('decisionSection').showModal()};tile.append(config);el('list').append(tile);
 }
 if(selected)show(filtered.find(m=>m.id===selected));
 else {closeDecision();el('manualReason').hidden=true;text('list','No matches found.');text('title','No match selected');text('context','');text('tableContext','');el('rows').replaceChildren()}
}
const viewQueries={games:'',ratings:''};
function switchView(view){viewQueries[activeView]=el('search').value;activeView=view;el('search').value=viewQueries[view];closeDecision();render()}
el('savedGamesNav').onclick=()=>switchView('games');el('playerRatingNav').onclick=()=>switchView('ratings');
const signed=value=>`${value>=0?'+':''}${value}`;
const change=u=>Math.round(u.after.value)-Math.round(u.before.value);
function node(tag,label,cls){const n=document.createElement(tag);if(label!=null)n.textContent=label;if(cls)n.className=cls;return n}
function playerRatings(){
 const players=new Map();
 // Games is the published rating sequence, which can differ from capture time.
 for(const m of all){
  if(m.rating?.status!=='rated')continue;
  for(const [id,u] of Object.entries(m.rating.updates||{})){
   if(!Number.isFinite(u.after?.value)||!Number.isFinite(u.before?.value))continue;
   if(!players.has(id))players.set(id,{id,rated:[],history:[]});
   players.get(id).rated.push({match:m,update:u});
  }
 }
 for(const p of players.values()){
  p.rated.sort((a,b)=>a.update.after.games-b.update.after.games||a.match.id.localeCompare(b.match.id));
  p.current=p.rated.at(-1).update.after;p.name=p.id;
  for(const m of [...all].sort((a,b)=>(b.timestamp||0)-(a.timestamp||0)||b.id.localeCompare(a.id))){
   const participant=(m.participants||[]).find(r=>r.steam_id===p.id&&r.role!=='spectator');
   const row=(m.player_rows||m.rows||[]).find(r=>r.steam_id===p.id&&r.kind==='player');
   const update=p.rated.find(r=>r.match.id===m.id)?.update;
   if(!participant&&!row&&!update)continue;
   if(p.name===p.id)p.name=row?.fields?.player?.text||participant?.display_name||p.id;
   const team=update?.team||participant?.starting_team;
   const winner=update?m.rating.winner:m.winner;
   p.history.push({match:m,update,result:winner&&['a','b'].includes(team)?(team===winner?'Win':'Loss'):'Undetermined'});
  }
  p.wins=p.rated.filter(r=>r.update.team===r.match.rating.winner).length;
  p.losses=p.rated.length-p.wins;
  const recent=p.rated.slice(-5);p.trend=Math.round(p.current.value)-Math.round(recent[0].update.before.value);
 }
 const sorted=[...players.values()].sort((a,b)=>b.current.value-a.current.value||a.name.localeCompare(b.name)||a.id.localeCompare(b.id));
 sorted.forEach((p,i)=>p.rank=i&&p.current.value===sorted[i-1].current.value?sorted[i-1].rank:i+1);
 return sorted;
}
function renderRatings(){
 const scrollTop=el('list').scrollTop;
 const query=el('search').value.toLowerCase().trim(),players=playerRatings();
 const filtered=players.filter(p=>`${p.name} ${p.id}`.toLowerCase().includes(query));
 text('listTitle',`Leaderboard (${filtered.length})`);el('list').replaceChildren();
 if(!filtered.some(p=>p.id===selectedPlayer))selectedPlayer=filtered[0]?.id;
 for(const p of filtered){
  const b=node('button',null,'match');b.type='button';b.setAttribute('aria-pressed',String(p.id===selectedPlayer));
  const row=node('div',null,'ratingRow');row.append(node('span',p.rank,'muted'));
  const label=node('div');label.append(node('span',p.name,'name'));label.append(node('span',`${p.rated.length} rated · ${p.wins}W / ${p.losses}L`,'muted'));row.append(label);
  const score=node('div',null,'ratingValue');score.append(node('strong',Math.round(p.current.value)));score.append(node('span',signed(p.trend),p.trend<0?'negative':'positive'));score.title=`Change over last ${Math.min(5,p.rated.length)} rated matches`;row.append(score);b.append(row);
  b.onclick=()=>{selectedPlayer=p.id;renderRatings()};el('list').append(b);
 }
 el('list').scrollTop=scrollTop;
 const p=filtered.find(p=>p.id===selectedPlayer);el('ratingContent').hidden=!p;
 if(!p){text('list',players.length?'No players found.':'No rated players yet.');text('ratingTitle','Player Rating');text('ratingContext',players.length?'Try another player name or Steam ID.':'Eligible saved matches will appear here once ratings are published.');return}
 text('ratingTitle',p.name);text('ratingContext',`#${p.rank} · Robz Battle Zones · ${p.id}${p.current.provisional?' · Provisional rating':''}`);
 el('ratingStats').replaceChildren();
 for(const [label,value,cls] of [['Rating',Math.round(p.current.value),''],['Rated matches',p.rated.length,''],['Win rate',`${Math.round(p.wins/p.rated.length*100)}%`,''],[`Last ${Math.min(5,p.rated.length)} rated`,signed(p.trend),p.trend<0?'negative':'positive']]){
  const stat=node('div');stat.append(node('span',label,'muted'));stat.append(node('strong',value,cls));el('ratingStats').append(stat);
 }
 drawTrend(p);el('ratingHistory').replaceChildren();
 for(const h of p.history){
  const m=h.match,tr=node('tr');tr.append(node('td',m.date?new Date(m.date).toLocaleString():'Time unavailable'));
  const map=node('td'),link=node('button',mapName(m.map),'historyLink');link.type='button';link.title='Open saved game';
  link.onclick=()=>{selected=m.id;viewQueries.games='';el('players').value='all';el('outcome').value='all';switchView('games')};map.append(link);tr.append(map);
  tr.append(node('td',h.result,h.result==='Win'?'positive':h.result==='Loss'?'negative':'muted'));
  tr.append(node('td',h.update?Math.round(h.update.after.value):'Unrated'));
  tr.append(node('td',h.update?signed(change(h.update)):'—',h.update?(change(h.update)<0?'negative':'positive'):'muted'));el('ratingHistory').append(tr);
 }
}
function drawTrend(p){
 const values=[p.rated[0].update.before.value,...p.rated.map(r=>r.update.after.value)];
 const low=Math.floor((Math.min(...values)-20)/50)*50,high=Math.ceil((Math.max(...values)+20)/50)*50;
 const width=Math.max(280,el('ratingTrend').clientWidth||760);
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox',`0 0 ${width} 180`);svg.setAttribute('class','trendChart');svg.setAttribute('role','img');svg.setAttribute('aria-label',`Rating trend from ${Math.round(values[0])} to ${Math.round(values.at(-1))} across ${p.rated.length} rated matches`);
 const shape=(tag,attrs,label)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(label!=null)n.textContent=label;svg.append(n);return n};
 const x=i=>48+i/(values.length-1)*(width-68),y=v=>155-(v-low)/(high-low)*135;
 for(const v of [low,Math.round((low+high)/2),high]){shape('line',{x1:48,x2:width-20,y1:y(v),y2:y(v),stroke:'#2a3547'});shape('text',{x:0,y:y(v)+4,fill:'#9eaec5','font-size':12},v)}
 shape('polyline',{points:values.map((v,i)=>`${x(i)},${y(v)}`).join(' '),fill:'none',stroke:'currentColor','stroke-width':2.5,'stroke-linejoin':'round'});
 values.forEach((v,i)=>{const dot=shape('circle',{cx:x(i),cy:y(v),r:4,fill:'currentColor',tabindex:0});const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=i?`${mapName(p.rated[i-1].match.map)} · ${Math.round(v)} (${signed(change(p.rated[i-1].update))})`:`Starting rating: ${Math.round(v)}`;dot.setAttribute('aria-label',title.textContent);dot.append(title)});
 const labels=node('div',null,'trendLabels muted');labels.append(node('span','Starting rating'));labels.append(node('span',`Latest · ${p.rated.length} rated matches`));el('ratingTrend').replaceChildren();el('ratingTrend').append(svg);el('ratingTrend').append(labels);
}
function closeDecision(){el('decisionSection').close();decisionMatch=null}
if(typeof window!=='undefined')window.addEventListener('resize',()=>{if(activeView==='ratings'){const p=playerRatings().find(p=>p.id===selectedPlayer);if(p)drawTrend(p)}});
el('decisionClose').onclick=closeDecision;
el('decisionSection').addEventListener('close',()=>{decisionMatch=null});
function updateSelection(draft){for(const team of ['a','b'])el(team==='a'?'winnerA':'winnerB').setAttribute('aria-pressed',String(draft.team===team));el('winnerConfirm').disabled=!service||saving||Boolean(all.find(m=>m.id===selected)?.winner)||!draft.team||!draft.reason.trim()}
function keepDraft(team){el('winnerReason').setCustomValidity('');const draft={reason:el('winnerReason').value,team:team||(drafts.get(selected)||{}).team||null};drafts.set(selected,draft);updateSelection(draft)}
el('winnerReason').addEventListener('input',()=>keepDraft());
const updates=service&&typeof BroadcastChannel==='function'?new BroadcastChannel('mow-match-review'):null;
let refreshPending=false,refreshing=false;
async function receiveUpdate(){
 if(saving){refreshPending=true;return}if(refreshing)return;refreshing=true;
 const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),10000);
 try{const response=await fetch('/api/matches',{signal:abort.signal});if(!response.ok)throw Error('Refresh failed');const result=await response.json();if(JSON.stringify(all)!==JSON.stringify(result.matches)){all.splice(0,all.length,...result.matches);render()}text('refreshHint','');}
 catch(error){text('refreshHint','Connection interrupted. Retrying automatically…');}
 finally{clearTimeout(timer);refreshing=false}
}
if(service&&typeof setInterval==='function')setInterval(receiveUpdate,5000);

if(updates)updates.onmessage=event=>{if(event.data?.kind==='match_updated')receiveUpdate()};
async function saveWinner(){
 if(!service||saving||!selected||decisionMatch!==selected||all.find(m=>m.id===selected)?.winner)return;
 const mid=selected,reason=el('winnerReason').value.trim(),team=drafts.get(mid)?.team;
 if(!team)return;
 if(!reason)el('winnerReason').setCustomValidity('Enter a reason for the winner.');
 if(!el('winnerReason').reportValidity())return;
 const body={match_id:mid,winning_team:team,reason};
 saving=true;el('decisionFields').disabled=true;text('decisionMessage','Saving winner and reason…');
 const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),20000);
 try{
  const response=await fetch('/api/adjudications',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':data.service_token},body:JSON.stringify(body),signal:abort.signal});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Could not save the decision.');
  all.splice(0,all.length,...result.matches);selected=mid;drafts.delete(mid);closeDecision();el('outcome').value='all';render();
  updates?.postMessage({kind:'match_updated',match_id:mid});
 }catch(error){text('decisionMessage',error.name==='AbortError'?'Save not confirmed. Retry the same decision; duplicate saves are safe.':error.message)}
 finally{clearTimeout(timer);saving=false;el('decisionFields').disabled=!service||Boolean(all.find(m=>m.id===selected)?.winner);updateSelection(drafts.get(selected)||{reason:'',team:null});if(refreshPending){refreshPending=false;receiveUpdate()}}
}
el('winnerA').onclick=()=>keepDraft('a');el('winnerB').onclick=()=>keepDraft('b');el('winnerConfirm').onclick=saveWinner;
el('players').addEventListener('change',render);el('search').addEventListener('input',render);el('outcome').addEventListener('change',render);render();
</script></html>'''
