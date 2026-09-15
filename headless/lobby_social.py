"""Lobby experience and chat history; at-most-once unattended greetings."""
from contextlib import closing
import hashlib
import json
import random
from pathlib import Path
import re
import sqlite3
import time

from modules.end_game_results.legacy import plain


def badge_tier(games):
    # Native A059E0: ur_rank / gs_rank use the same games-played thresholds.
    return None if games is None else sum(games >= n for n in (1,10,25,50,100,200,400,800,1500,2000))


def normalize_social(raw):
    roster=raw['roster']; nodes=raw['members']; players=[]
    for member in roster['rows']:
        if member['typeRaw'] not in (1,4):
            continue
        steam=str((member['identityWordsRaw'][1]<<32)|member['identityWordsRaw'][0])
        matching=[n for n in nodes if n['vtable']==0xd82e0c and n['name']==str(member['memberIdRaw'])]
        hints=[n.get('hint') for n in nodes if len(matching)==1 and n['parent']==matching[0]['address'] and n.get('hint')]
        def count(pattern):
            values=[int(m.group(1)) for hint in hints if (m:=re.fullmatch(pattern,hint))]
            return values[0] if len(values)==1 else None
        games=count(r'(\d+) Games played')
        ranked=count(r'(\d+) Ranked games played')
        source='native_lobby_badge_tooltip'
        if games is None:
            games=member.get('gamesPlayedRaw')
            source='native_session_member_0x148'
        players.append({'steam_id':steam,'native_member_id':member['memberIdRaw'],
            'display_name':member['displayName'],'games_played':games,'ranked_games_played':ranked,
            'badge_tier':badge_tier(games),'ranked_badge_tier':badge_tier(ranked),
            'source':source,'raw_hints':hints})
    messages=[]; nodes=raw['messages']; by={n['address']:n for n in nodes}; occurrences={}
    for row in nodes:
        if row['vtable']!=0xd82e0c:
            continue
        children=[n for n in nodes if n['parent']==row['address']]
        headers=[n for n in children if n['vtable']==0xd930d8 and n.get('text')]
        bodies=[]
        for n in nodes:
            if n['vtable']!=0xe0df10 or not n.get('text'):
                continue
            parent=n['parent']
            while parent in by and parent!=row['address']:
                parent=by[parent]['parent']
            if parent==row['address']:
                bodies.append(n)
        if len(headers)!=1 or len(bodies)!=1:
            continue
        header=headers[0]; body=bodies[0]['text']
        signature=json.dumps([header['name'],header['text'],body],ensure_ascii=True)
        occurrences[signature]=occurrences.get(signature,0)+1
        key=hashlib.sha256((signature+':'+str(occurrences[signature])).encode()).hexdigest()
        system=bool(re.search(r'\]\s*>+:',plain(header['text'])))
        messages.append({'message_key':key,'sender_name':None if system else header['name'],
            'kind':'system' if system else 'player',
            'header':plain(header['text']),'text':body,'raw_header':header['text'],
            'source':'native_lobby_chat_ui','sender_steam_id':None})
    return {'lobby_id':roster['steamLobbyId'],'players':players,'messages':messages}


def chat_name(name):
    return re.sub(r'[<>\x00-\x1f]','',plain(name))[:24] or 'Player'


def greeting(player, rating=None, games=0):
    text=(f"Hi {chat_name(player['display_name'])}! This is automated MOW lobby. "
          'The match will start as soon as lobby is full. ')
    text+=f'Games: {games}.'
    if rating is not None:
        text+=f" Rating: {round(rating['value'])}"
        if rating.get('provisional'):
            text+=' (provisional)'
        text+='.'
    else:
        text+=' Rating: unrated.'
    return text


def recorded_games(database, steam):
    """Count saved results once per match, excluding spectators and AI."""
    from match_ratings import read_inputs
    with closing(sqlite3.connect(database,timeout=10)) as db:
        records=read_inputs(db)
    return sum(any(p.get('steam_id')==steam and p.get('role')=='participant'
                   and p.get('controller_kind') in ('local_host','remote_human')
                   for p in record['metadata'].get('participants',[]))
               for record in records if record.get('finish') or record.get('lobby'))


def latest_recorded_game_end(database, steam):
    """Use completed replay timestamps to distinguish post-game rejoins."""
    from match_ratings import read_inputs
    with closing(sqlite3.connect(database,timeout=10)) as db:
        records=read_inputs(db)
    return max((float(r['metadata'].get('results_observed_at') or 0)
                for r in records if (r.get('finish') or r.get('lobby')) and
                any(p.get('steam_id')==steam and p.get('role')=='participant' and
                    p.get('controller_kind') in ('local_host','remote_human')
                    for p in r['metadata'].get('participants',[]))),default=0)


def read_history(database):
    path=Path(database).resolve()
    if not path.is_file():
        return {'players':[],'chat':[],'greetings':[]}
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        players=[];chat=[];greetings=[]
        if 'player_experience' in tables:
            seen=set()
            for r in db.execute('SELECT * FROM player_experience ORDER BY last_seen_at DESC,observed_at DESC'):
                if r['steam_id'] not in seen:
                    players.append(dict(json.loads(r['evidence_json']),last_seen_at=r['last_seen_at']))
                    seen.add(r['steam_id'])
        if 'lobby_chat' in tables:
            chat=[dict(r) for r in db.execute('SELECT lobby_id,observed_at,sender_name,text FROM lobby_chat ORDER BY observed_at DESC,rowid DESC LIMIT 30')]
        if 'lobby_greetings' in tables:
            greetings=[dict(r) for r in db.execute('SELECT * FROM lobby_greetings ORDER BY updated_at DESC LIMIT 30')]
    from match_ratings import stored
    ratings=stored(database).get('players',{})
    for player in players:
        player['rating']=ratings.get(player['steam_id'])
    return {'players':players,'chat':chat,'greetings':greetings}


class SocialStore:
    def __init__(self,path):
        self.path=path
        with closing(self.connect()) as db,db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS player_experience (
                    observation_key TEXT PRIMARY KEY, steam_id TEXT NOT NULL, lobby_id TEXT NOT NULL,
                    games_played INTEGER, ranked_games_played INTEGER, badge_tier INTEGER,
                    ranked_badge_tier INTEGER, observed_at REAL NOT NULL, last_seen_at REAL NOT NULL,
                    evidence_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS lobby_chat (
                    lobby_id TEXT NOT NULL, message_key TEXT NOT NULL, observed_at REAL NOT NULL,
                    sender_name TEXT, text TEXT NOT NULL, evidence_json TEXT NOT NULL,
                    PRIMARY KEY(lobby_id,message_key));
                CREATE TABLE IF NOT EXISTS lobby_greeting_history (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    lobby_id TEXT NOT NULL, steam_id TEXT NOT NULL, text TEXT NOT NULL,
                    status TEXT NOT NULL, updated_at REAL NOT NULL, error TEXT,
                    archived_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS lobby_greetings (
                    lobby_id TEXT NOT NULL, steam_id TEXT NOT NULL, text TEXT NOT NULL,
                    status TEXT NOT NULL, updated_at REAL NOT NULL, error TEXT,
                    PRIMARY KEY(lobby_id,steam_id));
            ''')

    def connect(self):
        return sqlite3.connect(self.path,timeout=10)

    def capture(self,observation):
        now=time.time(); lobby=observation['lobby_id']
        with closing(self.connect()) as db,db:
            for p in observation['players']:
                evidence=json.dumps(p,sort_keys=True)
                key=hashlib.sha256((lobby+evidence).encode()).hexdigest()
                db.execute('''INSERT INTO player_experience VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(observation_key) DO UPDATE SET last_seen_at=excluded.last_seen_at''',
                    (key,p['steam_id'],lobby,p['games_played'],p['ranked_games_played'],p['badge_tier'],p['ranked_badge_tier'],now,now,evidence))
            for m in observation['messages']:
                db.execute('''INSERT INTO lobby_chat VALUES (?,?,?,?,?,?)
                    ON CONFLICT(lobby_id,message_key) DO UPDATE SET
                    sender_name=excluded.sender_name,evidence_json=excluded.evidence_json''',
                    (lobby,m['message_key'],now,m['sender_name'],m['text'],json.dumps(m)))

    def renew_after_game_rejoin(self,lobby,steam,games):
        """Re-arm after a post-game entry, or a new entry after a definite rejection.

        Native callbacks survive fast rejoins between social polls and controller
        restarts. Archive the previous claim; uncertain sends are never retried
        within the same completed-game count.
        """
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT text,status,updated_at,error FROM lobby_greetings WHERE lobby_id=? AND steam_id=?',
                           (lobby,steam)).fetchone()
            if not old:return True
            rejected=old[1]=='not_sent'
            count=re.search(r'Games: (\d+)\.(?: Rating.*)?$',old[0])
            if not rejected and (not count or games<=int(count.group(1))):return False
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='participation_events'").fetchone():return False
            ended=0 if rejected else latest_recorded_game_end(self.path,steam)
            if not rejected and not ended:return False
            entries=db.execute("SELECT observed_at,evidence_json FROM participation_events WHERE steam_id=? AND kind='steam_lobby_membership' AND observed_at>?",
                               (steam,max(ended,old[2]))).fetchall()
            entered=False
            for observed,encoded in entries:
                event=json.loads(encoded)
                if (event.get('lobby_id')==lobby and event.get('flags',0)&1
                        and event.get('page_vtable')==0xe2b2cc):
                    entered=True
            if not entered:return False
            db.execute('INSERT INTO lobby_greeting_history(lobby_id,steam_id,text,status,updated_at,error,archived_at) VALUES (?,?,?,?,?,?,?)',
                       (lobby,steam,*old,time.time()))
            db.execute('DELETE FROM lobby_greetings WHERE lobby_id=? AND steam_id=?',(lobby,steam))
            return True

    def claim(self,lobby,steam,text):
        with closing(self.connect()) as db,db:
            return bool(db.execute('INSERT OR IGNORE INTO lobby_greetings VALUES (?,?,?,?,?,NULL)',
                (lobby,steam,text,'attempting',time.time())).rowcount)

    def finish(self,lobby,steam,status,error=None):
        with closing(self.connect()) as db,db:
            db.execute('UPDATE lobby_greetings SET status=?,updated_at=?,error=? WHERE lobby_id=? AND steam_id=?',
                (status,time.time(),error,lobby,steam))

    def confirm_echoes(self,observation,local_name):
        texts={m['text'] for m in observation['messages'] if m['sender_name']==local_name}
        with closing(self.connect()) as db,db:
            for text in texts:
                db.execute("UPDATE lobby_greetings SET status='observed',updated_at=? WHERE lobby_id=? AND text=? AND status='submitted'",
                    (time.time(),observation['lobby_id'],text))


class LobbySocial:
    def __init__(self,controller,rating_lookup=None):
        self.c=controller;self.store=SocialStore(controller.journal.path)
        from match_ratings import stored
        self.rating_lookup=rating_lookup or (lambda steam:stored(controller.journal.path).get('players',{}).get(steam))
        self.last_poll=-float('inf');self.last_send=-float('inf')
        self.latest=None
        self.greeting_due={};self.next_greeting=0
        from game_master import GameMaster,Settings
        settings=getattr(controller,'game_master_settings',None)
        self.game_master=GameMaster(controller,settings) if isinstance(settings,Settings) else None

    def game_master_tick(self,enabled):
        if self.game_master:self.game_master.tick(self,enabled)

    def close(self):
        if self.game_master:self.game_master.close()

    def poll(self,announce=False):
        now=time.monotonic()
        if now-self.last_poll<5:
            return
        self.last_poll=now
        # Failed/partial reads must not leave stale chat eligible for a greeting.
        self.latest=None
        from match_ratings import refresh
        refresh(self.c.journal.path)
        raw=self.c.command('probe',target='social')['probe']
        self.latest=raw
        observation=normalize_social(raw);self.store.capture(observation)
        self.c.record('lobby_social',**observation)
        roster=raw['roster']
        local=next((p for p in observation['players'] if p['native_member_id']==roster['localMemberIdRaw']),None)
        if local:
            self.store.confirm_echoes(observation,local['display_name'])
        if announce:
            self.greet_current()
        return observation

    def greet_current(self):
        if not self.latest:
            return
        raw=self.latest;now=time.monotonic();roster=raw['roster']
        observation=normalize_social(raw)
        if (self.c.record_only or now<self.next_greeting or now-self.last_send<5
                or roster['hostMemberIdRaw']!=roster['localMemberIdRaw'] or raw.get('input_busy')):
            return observation
        present={(observation['lobby_id'],p['steam_id']) for p in observation['players']}
        self.greeting_due={key:due for key,due in self.greeting_due.items() if key in present}
        for player in observation['players']:
            if player['native_member_id']==roster['localMemberIdRaw']:
                continue
            lobby=observation['lobby_id'];steam=player['steam_id'];key=(lobby,steam)
            games=recorded_games(self.c.journal.path,steam)
            if not self.store.renew_after_game_rejoin(lobby,steam,games):continue
            if key not in self.greeting_due:
                delay=random.uniform(1,3);self.greeting_due[key]=now+delay
                print('[CHAT] greeting queued '+json.dumps({'player':chat_name(player['display_name']),'delay_s':round(delay,1)},ensure_ascii=True),flush=True)
            if now<self.greeting_due[key]:continue
            text=greeting(player,self.rating_lookup(steam),
                          games=games)
            lobby=observation['lobby_id'];steam=player['steam_id']
            if not self.store.claim(lobby,steam,text):
                continue
            self.last_send=now;self.next_greeting=now+random.uniform(5,12)
            self.greeting_due.pop(key,None)
            print('[CHAT] greeting send '+json.dumps(text,ensure_ascii=True),flush=True)
            try:
                self.c.command('chat-greeting',lobbyId=lobby,steamId=steam,text=text)
            except Exception as error:
                result=getattr(error,'command_result',None)
                not_sent=isinstance(result,dict) and result.get('mutationStarted') is False
                self.store.finish(lobby,steam,'not_sent' if not_sent else 'unconfirmed',str(error))
                raise
            self.store.finish(lobby,steam,'submitted')
            break
        return observation
