"""Bounded, asynchronous lobby replies via the user's signed-in Codex CLI."""
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from contextlib import closing
from dataclasses import dataclass
import json
import os
import platform
from pathlib import Path
import re
import random
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    model: str = 'gpt-6-astra'
    reasoning: str = 'low'
    mode: str = 'ambient'
    cooldown: float = 20
    timeout: float = 45
    context_messages: int = 12
    max_chars: int = 120
    dry_run: bool = False
    verbose: bool = True


def player_context(roster,players):
    result=[]
    for player in players:
        matches=[m for m in roster.get('rows',[]) if m['memberIdRaw']==player['native_member_id']]
        member=matches[0] if len(matches)==1 else {}
        team=member.get('teamRaw')
        role=('spectator' if member.get('typeRaw')==4 and team=='spectator' else
              'player' if member.get('typeRaw') in (1,2) and team in ('a','b') else None)
        result.append({'name':player['display_name'],'is_host':player['native_member_id']==roster['hostMemberIdRaw'],
                       'role':role,'team':team,
                       'ready':bool(member['readyRaw']) if 'readyRaw' in member else None})
    return result


def clean_environment():
    env=os.environ.copy()
    for name in ('OPENAI_API_KEY','CODEX_API_KEY','OPENAI_BASE_URL','OPENAI_API_BASE','CODEX_ACCESS_TOKEN'):
        env.pop(name,None)
    return env


def executable():
    override=os.environ.get('MOW_CODEX_EXE')
    if override:
        candidate=Path(override).expanduser()
        if not candidate.is_absolute() or not candidate.is_file():
            raise RuntimeError('MOW_CODEX_EXE must be an absolute path to the Codex executable')
        return str(candidate)
    path=shutil.which('codex')
    if path:return path
    # VS Code adds its bundled CLI to extension terminals only. Ordinary
    # PowerShell can still use the same executable and saved ChatGPT login.
    if os.name=='nt':
        arch='windows-aarch64' if platform.machine().lower() in ('arm64','aarch64') else 'windows-x86_64'
        candidates=[]
        for editor in ('.vscode','.vscode-insiders'):
            for directory in (Path.home()/editor/'extensions').glob('openai.chatgpt-*'):
                binary=directory/'bin'/arch/'codex.exe'
                version=re.match(r'openai\.chatgpt-(\d+)\.(\d+)\.(\d+)',directory.name)
                if binary.is_file() and version:
                    candidates.append((tuple(map(int,version.groups())),str(binary)))
        if candidates:return max(candidates)[1]
    raise RuntimeError('Codex CLI not found on PATH or in the VS Code extension. Set MOW_CODEX_EXE to its full executable path.')


def check_login():
    result=subprocess.run([executable(),'login','status'],capture_output=True,text=True,
                          timeout=10,env=clean_environment(),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode or 'Logged in using ChatGPT' not in result.stdout+result.stderr:
        raise RuntimeError('Game master requires Codex ChatGPT sign-in; run codex login. No API-key fallback.')


def validate_reply(value,limit):
    if not isinstance(value,dict) or set(value)!={'reply','text'} or type(value['reply']) is not bool or not isinstance(value['text'],str):
        raise ValueError('Invalid game-master output schema')
    text=value['text'].strip()
    if not value['reply']:return None
    if not text or len(text)>limit or re.search(r'[<>\x00-\x1f\x7f]',text) or text.startswith('/') or re.search(r'https?://|www\.',text,re.I):
        raise ValueError('Unsafe or oversized game-master reply')
    return text


def command(settings,directory):
    args=[executable(),'exec','--ignore-user-config','--ignore-rules','--ephemeral',
          '--skip-git-repo-check','--sandbox','read-only','--color','never',
          '--model',settings.model,'--output-schema',str(directory/'schema.json'),
          '--output-last-message',str(directory/'reply.json'),'-C',str(directory)]
    config={'forced_login_method':'chatgpt','approval_policy':'never','web_search':'disabled',
            'project_doc_max_bytes':0,'model_reasoning_effort':settings.reasoning,
            'model_instructions_file':str(ROOT/'game_master_prompt.md')}
    for key,value in config.items():args+=['-c',key+'='+json.dumps(value)]
    for feature in ('shell_tool','unified_exec','apps','multi_agent','image_generation','view_image',
                    'hooks','skill_search','skill_mcp_dependency_install'):
        args+=['--disable',feature]
    args.append('-')
    return args


class CodexBackend:
    def __init__(self,settings):
        self.settings=settings;self.lock=threading.Lock();self.process=None;self.closed=False

    def generate(self,context):
        with tempfile.TemporaryDirectory(prefix='mow-game-master-') as tmp:
            directory=Path(tmp)
            schema={'type':'object','properties':{'reply':{'type':'boolean'},'text':{'type':'string'}},
                    'required':['reply','text'],'additionalProperties':False}
            (directory/'schema.json').write_text(json.dumps(schema))
            with self.lock:
                if self.closed:raise RuntimeError('Game master stopped')
                self.process=subprocess.Popen(command(self.settings,directory),cwd=directory,
                    stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                    text=True,encoding='utf-8',env=clean_environment(),
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                process=self.process
            try:
                process.communicate(json.dumps(context,ensure_ascii=True),timeout=self.settings.timeout)
                if process.returncode:raise RuntimeError(f'Codex generation failed (exit {process.returncode}); check model access/login/limits')
                result=directory/'reply.json'
                if not result.exists() or result.stat().st_size>8192:raise ValueError('Missing or oversized Codex response')
                return validate_reply(json.loads(result.read_text(encoding='utf-8')),self.settings.max_chars)
            finally:
                if process.poll() is None:process.kill();process.wait(timeout=5)
                with self.lock:self.process=None

    def close(self):
        with self.lock:
            self.closed=True
            if self.process and self.process.poll() is None:self.process.kill()


class GameMaster:
    def __init__(self,controller,settings,backend=None):
        self.c=controller;self.settings=settings;self.backend=backend or CodexBackend(settings)
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='mow-gm')
        self.future=None;self.pending=None;self.lobby=None;self.seen=set();self.next_request=0
        self.inbox=deque();self.scope=None
        self.trace('started',model=settings.model,reasoning=settings.reasoning,mode='ambient',dry_run=settings.dry_run)
        with closing(sqlite3.connect(self.c.journal.path)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS game_master_replies (lobby TEXT, message_key TEXT, status TEXT, text TEXT, updated REAL, PRIMARY KEY(lobby,message_key))')

    def trace(self,event,**fields):
        self.c.record('game_master_flow',stage=event,**fields)
        if self.settings.verbose:
            print('[GM '+time.strftime('%H:%M:%S')+'] '+event+' '+json.dumps(fields,ensure_ascii=True),flush=True)

    def record(self,key,status,text=None):
        self.trace(status,message=key[1][:10],**({'text':text} if text else {}))
        with closing(sqlite3.connect(self.c.journal.path)) as db,db:
            db.execute('UPDATE game_master_replies SET status=?,text=?,updated=? WHERE lobby=? AND message_key=?',
                       (status,text,time.time(),*key))

    def tick(self,social,enabled):
        from lobby_social import normalize_social
        raw=social.latest
        if not raw:return
        obs=normalize_social(raw);r=raw['roster'];now=time.monotonic();lobby=obs['lobby_id']
        keys={m['message_key'] for m in obs['messages']}
        if lobby!=self.lobby:
            self.lobby=lobby;self.seen=keys.copy() # Never reply to pre-attachment history.
        fresh=[m for m in obs['messages'] if m['message_key'] not in self.seen]
        self.seen.update(keys)
        if len(self.seen)>4096:self.seen=keys.copy()
        scope=(lobby,r.get('gameStartTimeRaw'),json.dumps(r['settings'],sort_keys=True))
        if scope!=self.scope or not enabled or self.c.record_only:
            self.inbox.clear();self.scope=scope
        local=next((p for p in obs['players'] if p['native_member_id']==r['localMemberIdRaw']),None)
        if enabled and not self.c.record_only and local and r['hostMemberIdRaw']==r['localMemberIdRaw']:
            for m in fresh:
                if m.get('kind')!='player' or m['sender_name']==local['display_name'] or m['text'].strip().lower()=='/start':continue
                people=[p for p in obs['players'] if p['display_name']==m['sender_name']]
                if len(people)==1:
                    self.inbox.append((dict(m),people[0]['steam_id']))
        if self.future and self.future.done():
            job=self.pending
            if 'ready_at' not in job:
                try:job['text']=self.future.result()
                except Exception as error:
                    self.future=self.pending=None
                    self.record(job['key'],'generation_failed');self.trace('error',detail=str(error));return
                delay=random.uniform(1,4) if job['text'] else 0
                job['ready_at']=now+delay
                self.trace('generated',elapsed_s=round(now-job['started'],2),text=job['text'],send_delay_s=round(delay,1))
            if now<job['ready_at']:return
            text=job['text'];self.future=self.pending=None
            valid=(enabled and lobby==job['key'][0] and now-job['started']<=self.settings.timeout+10
                   and r.get('gameStartTimeRaw')==job['epoch'] and r['settings']==job['settings'] and not raw.get('input_busy')
                   and now-social.last_send>=5 and r['localMemberIdRaw']==r['hostMemberIdRaw']
                   and any(p['steam_id']==job['steam'] for p in obs['players']))
            guard=getattr(self.c,'game_master_can_send',None)
            if valid and callable(guard):valid=bool(guard())
            if text and valid:
                if self.settings.dry_run:self.record(job['key'],'dry_run',text)
                else:
                    self.record(job['key'],'send_requested',text) # At-most-once, including uncertain native failures.
                    social.last_send=now
                    try:
                        self.c.command('chat-reply',lobbyId=lobby,steamId=job['steam'],text=text,
                                       expectedEpoch=job['epoch'],expectedSettings=job['settings'])
                        self.record(job['key'],'submitted',text)
                    except Exception as error:
                        self.record(job['key'],'unconfirmed',text);self.c.record('game_master_error',error=str(error))
            elif text:self.record(job['key'],'discarded_stale')
            else:self.record(job['key'],'silent')
        if self.future or not enabled or now<self.next_request or self.c.record_only or raw.get('input_busy'):
            if fresh:self.trace('deferred' if self.inbox else 'skipped',queued=len(self.inbox),reason='generating' if self.future else 'held' if not enabled else 'cooldown' if now<self.next_request else 'input busy or record-only')
            return
        if not local or r['hostMemberIdRaw']!=r['localMemberIdRaw']:return
        while self.inbox:
            m,steam=self.inbox.popleft()
            people=[p for p in obs['players'] if p['display_name']==m['sender_name']]
            if len(people)!=1 or people[0]['steam_id']!=steam:continue
            key=(lobby,m['message_key'])
            with closing(sqlite3.connect(self.c.journal.path)) as db,db:
                claimed=db.execute('INSERT OR IGNORE INTO game_master_replies VALUES (?,?,?,?,?)',(*key,'requested',None,time.time())).rowcount
            if not claimed:continue
            context={'max_chars':self.settings.max_chars,'host_name':local['display_name'],
                     'hosting_policy':{'required_players':r['settings'].get('maxPlayers'),
                                       'unanimous_early_start':True,'wait_for_full_lobby':False,'all_players_must_be_ready':True,
                                       'spectators_count_as_players':False},
                     'map':r.get('map'),'settings':r['settings'],
                     'players':player_context(r,obs['players']),
                     'recent_chat':[{'name':x['sender_name'],'text':x['text'][:400]} for x in obs['messages'][-self.settings.context_messages:]],
                     'respond_to':{'name':m['sender_name'],'text':m['text'][:400]}}
            self.pending={'key':key,'steam':people[0]['steam_id'],'epoch':r.get('gameStartTimeRaw'),
                          'settings':json.loads(json.dumps(r['settings'])),'started':now}
            self.trace('request',sender=m['sender_name'],text=m['text'][:400],model=self.settings.model,context_messages=len(context['recent_chat']))
            self.next_request=now+self.settings.cooldown+random.uniform(0,5)
            self.future=self.pool.submit(self.backend.generate,context)
            break

    def close(self):
        self.backend.close();self.pool.shutdown(wait=False,cancel_futures=True)
        self.trace('stopped')
