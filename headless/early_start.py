"""Unanimous lobby votes, scoped to observed roster/settings and fresh chat."""
import json
import time
from lobby_social import normalize_social


def early_voters(roster):
    return [str((r['identityWordsRaw'][1]<<32)|r['identityWordsRaw'][0])
            for r in roster['rows'] if r['typeRaw']==1]


def vote_scope(r):
    return json.dumps([r.get('steamLobbyId'),r.get('gameStartTimeRaw'),r.get('map'),r['settings'],
        r['hostMemberIdRaw'],r['localMemberIdRaw'],r['slots'],
        [[m.get(k) for k in ('memberIdRaw','identityWordsRaw','typeRaw','teamRaw','armyRaw','displayName')]
         +[m['readyRaw'] if m['typeRaw']!=4 else None] for m in r['rows']]],sort_keys=True)


class EarlyStart:
    def __init__(self):
        self.scope=None;self.votes=set();self.seen=set();self.lobby=None
        self.notice=None;self.offered=False;self.cancelled=False

    def reset(self, notify=True):
        self.cancelled=notify and (self.cancelled or self.scope is not None)
        self.scope=None;self.votes.clear();self.notice=None;self.offered=False

    def tick(self,social,approval,enabled,eligible,gate):
        c=social.c;r=approval['roster'];raw=social.latest
        if not enabled or c.record_only or not raw:
            self.reset();return False
        obs=normalize_social(raw);keys={m['message_key'] for m in obs['messages']}
        fresh=[m for m in obs['messages'] if m['message_key'] not in self.seen]
        if self.lobby!=obs['lobby_id']:
            self.reset();self.cancelled=False;self.lobby=obs['lobby_id'];self.seen=set();fresh=[]
        self.seen.update(keys)
        scope=vote_scope(r)
        if vote_scope(raw['roster'])!=scope:
            self.reset();return False
        if not eligible:
            self.reset()
            if self.cancelled:self.notice='Early start cancelled: players, readiness or settings changed. Ready both teams to vote again.'
        elif scope!=self.scope:
            changed=self.cancelled or self.scope is not None
            self.reset();self.scope=scope
            counts=[sum(m['typeRaw']==1 and m.get('teamRaw')==t for m in r['rows']) for t in ('a','b')]
            self.notice=('Votes reset. ' if changed else '')+f'All players ready for {counts[0]}v{counts[1]}. Each player: type /start to start early. Everyone must agree.'
            fresh=[]
        elif self.offered:
            for m in fresh:
                if m.get('kind')!='player' or m['text'].strip().lower()!='/start':continue
                people=[p for p in obs['players'] if p['display_name']==m['sender_name']]
                if len(people)!=1:
                    self.notice='Cannot identify that vote: display names must be unique. Each player needs their own /start.'
                    continue
                steam=people[0]['steam_id']
                if steam not in early_voters(r):
                    self.notice='Only players on Team A or B vote for early start; spectators do not count.'
                elif steam not in self.votes:
                    self.votes.add(steam)
                    self.notice=f'Early start: {len(self.votes)}/{len(early_voters(r))} votes. Remaining players: type /start.'
        unanimous=eligible and self.offered and self.votes==set(early_voters(r))
        if unanimous:
            final='Everyone agreed. Starting now.' if gate else 'Everyone agreed. Waiting for the game to allow Start.'
            if self.notice!=final and not getattr(self,'waiting_gate',False):self.notice=final
            if gate:self.notice=final
            self.waiting_gate=not gate
        else:self.waiting_gate=False
        if not self.notice:return False
        now=time.monotonic()
        if raw.get('input_busy') or now-social.last_send<5:return False
        guard=getattr(c,'game_master_can_send',None)
        if callable(guard) and not guard():self.reset();return False
        local=next((p for p in obs['players'] if p['native_member_id']==r['localMemberIdRaw']),None)
        if not local:return False
        text=self.notice;self.notice=None;social.last_send=now
        try:
            c.command('chat-reply',lobbyId=r['steamLobbyId'],steamId=local['steam_id'],text=text,
                      expectedEpoch=r.get('gameStartTimeRaw'),expectedSettings=r['settings'],approval=approval['approval'])
        except (RuntimeError,ValueError) as error:
            c.record('early_start_notice_failed',error=str(error))
            self.reset();return False
        c.record('early_start_notice',text=text,votes=sorted(self.votes))
        self.offered=eligible;self.cancelled=False
        return unanimous and gate
