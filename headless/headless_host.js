'use strict';
// Retail AS2 3.262.1, x86. All engine calls execute after the main-loop
// non-quant message dispatch returns. No input, focus, or crash-skipping hooks.
const module = Process.getModuleByName('mowas_2.exe');
const va = address => module.base.add(address - 0x400000);
if (Process.arch !== 'ia32') throw Error('Expected the x86 game');
for (const [address, expected] of [
    [0x7105a0,'558bec8b45088941'], [0xafb460,'558bec83ec5c5356'],
    [0xbb3030,'566a10e8b8b495ff'], [0xbb1c50,'558bec5156578bf1'],
    [0xb881f0,'558bec83ec5c568b'], [0xb773a0,'558bec81ecf80100'],
    [0xa89200,'558bec83ec18e825'], [0xae5910,'558bec81ecf40000'],
    [0xa1dfc0,'558bec8b81840000'], [0xa1df80,'558bec83ec148b45'],
    [0xa31910,'558bec568bf18b86'], [0xb7aef0,'558bec83ec60578b'],
    [0xb5e100,'558bec83ec34538b'], [0xb3e500,'558bec83ec08568b'], [0xb764c0,'558bec8b550881ec'],
    [0xb37ae0,'558bec81ec780200'], [0xb806b0,'558bec83ec3c5356'],
    [0xa0bfb0,'558bec81ecd80000'], [0xb38690,'558bec83ec485356']
]) {
    const actual = Array.from(new Uint8Array(va(address).readByteArray(8)))
        .map(byte => byte.toString(16).padStart(2,'0')).join('');
    if (actual !== expected) throw Error('Unsupported or already hooked engine code at '+va(address));
}
const read = address => {
    try { return address.isNull() ? ptr(0) : address.readPointer(); }
    catch (_) { return ptr(0); }
};
const rva = pointer => pointer.isNull() ? 0 : pointer.sub(module.base).add(0x400000).toUInt32();
let nativeMutationStarted=false;
let readOnly=false;
const call = (address, result, args, abi='thiscall') => {
    const fn=new NativeFunction(va(address),result,args,{abi,exceptions:'propagate'});
    return (...values)=>{if(address!==0xb7fe30) nativeMutationStarted=true; return fn(...values);};
};
function stringAt(address) {
    try {
        const size = address.add(16).readU32(), capacity = address.add(20).readU32();
        if (size > 1024 || size > capacity) return null;
        return (capacity > 15 ? read(address) : address).readUtf8String(size);
    } catch (_) { return null; }
}
let ticks = 0, loopThread = 0, pending = null, running = false;
let quitRequest = null;
function state() {
    const core = read(va(0xfeab08)), session = read(va(0xfeab44));
    const pipeline = read(va(0xfeb3f0)), page = read(va(0xfeaac0));
    const stage = pipeline.isNull() ? ptr(0) : read(pipeline.sub(4));
    const stageVtable = rva(read(stage)), pageVtable = rva(read(page));
    const service = pageVtable === 0xe2b2cc ? read(page.add(0x724)) : ptr(0);
    const card = !service.isNull() ? read(service.add(0x184)) : ptr(0);
    return {pid:Process.id,base:module.base.toString(),ticks,loopThread,
        core:core.toString(),coreVtable:rva(read(core)),session:session.toString(),
        sessionVtable:rva(read(session)),pipeline:pipeline.toString(),
        stage:stage.toString(),stageVtable,page:page.toString(),pageVtable,
        pageName:page.isNull() ? null : stringAt(page.add(0x2c)),
        service:service.toString(),serviceVtable:rva(read(service)),
        card:card.toString(),cardVtable:rva(read(card)),
        map:card.isNull() ? null : stringAt(card.add(0x64))};
}
function requireStage(expected) {
    if (state().stageVtable !== expected) throw Error('Unexpected stage: '+JSON.stringify(state()));
}
function lobbyPage() {
    const s = state();
    if (s.pageVtable !== 0xe2b2cc || s.serviceVtable !== 0xde0fd0 || s.card === '0x0')
        throw Error('Lobby page, service, and session card must be initialized');
    return ptr(s.page);
}
function findService(kind) {
    const begin = va(0xfead5c).readPointer(), end = va(0xfead60).readPointer();
    const bytes = end.sub(begin).toInt32();
    if (bytes < 0 || bytes % 4 || bytes > 128*4 || (bytes && begin.isNull()))
        throw Error('Invalid service registry');
    const matches = [];
    for (let offset = 0; offset < bytes; offset += 4) {
        const object = begin.add(offset).readPointer();
        if (!object.isNull() && object.add(8).readU32() === kind && object.add(0xd).readU8() === 0)
            matches.push(object);
    }
    if (matches.length !== 1) throw Error('Expected one active service of kind '+kind);
    return matches[0];
}
function lobbyProbe(fromRegistry=false) {
    if (!fromRegistry) lobbyPage();
    const s = state(), service = fromRegistry ? findService(8) : ptr(s.service);
    if (rva(read(service)) !== 0xde0fd0) throw Error('Unsupported session service');
    const card = service.add(0x184).readPointer();
    if (card.isNull() || rva(read(card)) !== 0xe274dc) throw Error('Missing or unsupported session card');
    const begin = card.add(0x4f4).readPointer(), end = card.add(0x4f8).readPointer();
    const bytes = end.sub(begin).toInt32();
    if (bytes < 0 || bytes % 4 || bytes > 64 * 4 || (bytes && begin.isNull()))
        throw Error('Invalid or unsupported roster vector');
    const rows = [];
    for (let offset = 0; offset < bytes; offset += 4) {
        const row = begin.add(offset).readPointer();
        if (row.isNull()) throw Error('Null roster entry');
        const strings = [];
        for (let at = 0; at <= 0x148; at += 4) {
            const value = stringAt(row.add(at));
            if (value) strings.push({offset:at,value});
        }
        rows.push({address:row.toString(), typeRaw:row.add(4).readU32(),
            displayName:stringAt(row.add(0xc)), aiDifficultyRaw:row.add(4).readU32() === 2 ? stringAt(row.add(0x11c)) : null,
            armyRaw:stringAt(row.add(0xd8)), teamRaw:stringAt(row.add(0x50)),
            memberIdRaw:row.add(8).readU32(), readyRaw:row.add(0x160).readU8(),
            identityWordsRaw:[row.add(0x134).readU32(),row.add(0x138).readU32()],
            gamesPlayedRaw:[1,4].includes(row.add(4).readU32()) ? row.add(0x148).readU32() : null,
            strings, rawHex:Array.from(new Uint8Array(row.readByteArray(0x164)))
                .map(byte => byte.toString(16).padStart(2,'0')).join('')});
    }
    const slotBegin = card.add(0x500).readPointer(), slotEnd = card.add(0x504).readPointer();
    const slotBytes = slotEnd.sub(slotBegin).toInt32();
    if (slotBytes < 0 || slotBytes % 4 || slotBytes > 64*4) throw Error('Invalid slot vector');
    const slots = [];
    for (let at=0; at<slotBytes; at+=4) {
        const slot = slotBegin.add(at).readPointer();
        slots.push({address:slot.toString(), slotIdRaw:slot.add(4).readU32(),
            teamRaw:stringAt(slot.add(0x38)), teamSlotIndexRaw:slot.add(8).readU32(), stateRaw:slot.add(0x50).readU32(),
            memberIdRaw:slot.add(0x54).readU32(),
            rawHex:Array.from(new Uint8Array(slot.readByteArray(0x5c))).map(b=>b.toString(16).padStart(2,'0')).join('')});
    }
    const lobbyObject=service.add(0x1a4).readPointer();
    const lobbyIdAt=lobbyObject.isNull()?service.add(0x19c):lobbyObject.add(8);
    return {source:'engine_session_card', layoutStatus:'under_investigation', slots,
        steamLobbyId:lobbyIdAt.readU64().toString(), gameStartTimeRaw:stringAt(card.add(0x544)),
        settings:{maxPlayers:card.add(0xd0).readU32(),maxSpectators:card.add(0xd4).readU32(),
            armySelectionMode:card.add(0x160).readU32(),teamArmies:teamArmies(card),victoryPoints:card.add(0x1e8).readS32(),victoryPointsMin:card.add(0x1e0).readS32(),
            victoryPointsMax:card.add(0x1e4).readS32(),totalManpower:card.add(0x1f8).readFloat(),
            preparationTime:card.add(0x1f4).readS32(),enableSpectators:card.add(0x22c).readU8(),
            source:'effective_engine_session_card',manpowerScope:'unverified'},
        service:service.toString(),card:card.toString(),cardVtable:rva(read(card)),
        map:stringAt(card.add(0x64)),mapSelectionPlayersRaw:va(0xf3c680).readU32(),
        hostMemberIdRaw:card.add(0xcc).readU32(),
        localMemberIdRaw:service.add(0x20).readU32(), rows, snapshot:s};
}
let browserMetadata=null;
function browserLobbyName(options) {
    if(options.lobbyName==null) {
        if(options.lobbyColor!=null) throw Error('Lobby color requires a name');
        return null;
    }
    const name=options.lobbyName,color=options.lobbyColor;
    if(typeof name!=='string' || !name.trim() || name.length>64 || /[<>\x00-\x1f\x7f]/.test(name))
        throw Error('Invalid lobby name');
    if(color!=null && (typeof color!=='string' || !/^[0-9a-fA-F]{6}$/.test(color)))
        throw Error('Invalid lobby color');
    return color==null ? name : '<c('+color.toLowerCase()+')>'+name;
}
function browserContext() {
    if(readOnly) throw Error('Record-only mode forbids browser publication');
    lobbyPage();
    const roster=lobbyProbe();
    if(roster.localMemberIdRaw!==roster.hostMemberIdRaw || roster.steamLobbyId==='0')
        throw Error('Local lobby host required');
    return {roster};
}
function publishBrowserName(options={}) {
    const hostName=browserLobbyName(options);
    const {roster}=browserContext();
    if(hostName==null) return {lobbyId:roster.steamLobbyId,nameOverride:null};
    if(!browserMetadata) {
        const steam=Process.getModuleByName('steam_api.dll');
        const mm=new NativeFunction(steam.getExportByName('SteamMatchmaking'),'pointer',[],'mscdecl')();
        if(mm.isNull()) throw Error('Steam matchmaking unavailable');
        const vtable=mm.readPointer();
        const get=new NativeFunction(vtable.add(19*4).readPointer(),'pointer',['pointer','uint64','pointer'],'thiscall');
        const setter=vtable.add(20*4).readPointer();
        const set=new NativeFunction(setter,'bool',['pointer','uint64','pointer','pointer'],'thiscall');
        // x86 thiscall keeps self in ECX; the uint64 lobby occupies two stack words.
        const hook=Interceptor.attach(setter,{onEnter(args) {
            try {
                const key=args[2].readUtf8String();
                if(readOnly || key!=='hostname') return;
                const context=browserContext();
                const id=(BigInt(args[1].toUInt32())<<32n)|BigInt(args[0].toUInt32());
                if(id.toString()!==context.roster.steamLobbyId) return;
                const replacement=browserMetadata.hostName;
                if(replacement==null) return;
                this.countText=Memory.allocUtf8String(replacement);
                args[3]=this.countText;
            } catch(error) { send({event:'browser_name_skipped',error:String(error)}); }
        }});
        browserMetadata={mm,get,set,hook,hostName};
    }
    browserMetadata.hostName=hostName;
    const {mm,get,set}=browserMetadata,id=uint64(roster.steamLobbyId);
    const nameKey=Memory.allocUtf8String('hostname'),previousName=get(mm,id,nameKey).readUtf8String();
    if(hostName!=null && previousName!==hostName) {
        nativeMutationStarted=true;
        if(!set(mm,id,nameKey,Memory.allocUtf8String(hostName))) throw Error('Steam rejected lobby name');
    }
    const advertisedName=get(mm,id,nameKey).readUtf8String();
    if(hostName!=null && advertisedName!==hostName) throw Error('Lobby name readback differs');
    return {lobbyId:roster.steamLobbyId,advertisedName,previousName,nameOverride:hostName};
}
function lobbySocialContext(probeOptions={}) {
    lobbyPage();
    // The chat panel is a direct child of the lobby page. Do not walk unrelated
    // profile/friends subtrees, which can grow beyond the general UI scan bounds.
    const page=ptr(state().page),first=read(page.add(0x90)),last=read(page.add(0x94));
    const size=last.sub(first).toInt32(),roots=[];
    if(size<0 || size%4 || size>512*4 || (size && first.isNull())) throw Error('Invalid lobby page children');
    for(let at=0;at<size;at+=4) {
        if(probeOptions.deadline!=null && Date.now()>probeOptions.deadline) throw Error('UI probe time budget exceeded; retry on next poll');
        const child=read(first.add(at));
        if(child.isNull() || !read(child.add(0x9c)).equals(page)) throw Error('UI child ownership mismatch');
        if(rva(read(child))===0xe0b1d4 && stringAt(child.add(0x2c))==='mp_steamsessionchat') roots.push({address:child.toString()});
    }
    if(roots.length!==1) throw Error('Expected one lobby chat panel');
    const root=ptr(roots[0].address), begin=read(root.add(0xf4)), end=read(root.add(0xf8));
    const bytes=end.sub(begin).toInt32(),channels=[];
    if(bytes<0 || bytes%8 || bytes>8*8) throw Error('Invalid chat channel vector');
    for(let at=0;at<bytes;at+=8){const channel=read(begin.add(at));if(rva(read(channel))===0xe0be90)channels.push(channel);}
    if(channels.length!==1) throw Error('Expected one Steam lobby chat channel');
    return {root,channel:channels[0]};
}
function socialProbe() {
    const options={includeRaw:false,deadline:Date.now()+100};
    const step=name=>send({event:'social_probe_step',step:name,ticks,thread:loopThread});
    step('roster');
    const roster=lobbyProbe();
    step('locate_chat');
    const ctx=lobbySocialContext(options);
    step('members');
    const members=statisticsProbe(read(ctx.channel.add(0xd0)),true,false,options).nodes;
    step('messages');
    const messages=statisticsProbe(read(ctx.channel.add(0xd4)),true,false,options).nodes;
    step('input_and_hints');
    return {source:'native_steam_lobby_chat',roster,channel:ctx.channel.toString(),
        input_busy:stringAt(read(ctx.root.add(0xec)).add(0x44))!=='',
        members:members.map(n=>({...n,hint:stringAt(ptr(n.address).add(0x6c))})),messages};
}
function sendLobbyChat(options,announcement=false,reply=false) {
    if(announcement)throw Error('Automatic announcements are disabled');
    const roster=lobbyProbe();
    if(reply && options.approval!==undefined && rosterApproval(roster)!==options.approval)throw Error('Vote announcement context changed');
    if(roster.steamLobbyId!==options.lobbyId) throw Error('Chat lobby changed');
    if(reply && (roster.gameStartTimeRaw!==options.expectedEpoch ||
        JSON.stringify(roster.settings)!==JSON.stringify(options.expectedSettings) ||
        !va(0xfe17d4).readPointer().isNull())) throw Error('Game-master reply context changed');
    if(roster.localMemberIdRaw!==roster.hostMemberIdRaw) throw Error('Announcements require local lobby host');
    if(announcement && rosterApproval(roster)!==options.approval) throw Error('Readiness changed before announcement');
    if(!announcement && !roster.rows.some(r=>[1,4].includes(r.typeRaw) && String((BigInt(r.identityWordsRaw[1])<<32n)|BigInt(r.identityWordsRaw[0]))===options.steamId))
        throw Error('Greeting recipient left the lobby');
    const text=options.text;
    const maxChars=reply?128:256;
    if(typeof text!=='string' || !text.length || text.length>maxChars || /[\x00-\x1f<>]/.test(text) || text.startsWith('/')) throw Error('Invalid lobby greeting');
    const ctx=lobbySocialContext(),edit=read(ctx.root.add(0xec));
    if(rva(read(edit))!==0xe0df10 || stringAt(edit.add(0x44))!=='') throw Error('Chat input is busy');
    // The native setter copies this std::string; Frida retains both buffers until return.
    const utf8=Memory.allocUtf8String(text);
    const size=unescape(encodeURIComponent(text)).length, str=Memory.alloc(24);
    str.writeByteArray(new Uint8Array(24));
    if(size<=15) str.writeUtf8String(text);else str.writePointer(utf8);
    str.add(16).writeU32(size);str.add(20).writeU32(Math.max(15,size));
    const setter=rva(read(read(edit).add(0x54)));
    if(setter!==0xa2a800) throw Error('Unsupported chat text setter');
    call(setter,'void',['pointer','pointer'])(edit,str);
    const event=Memory.alloc(16);event.writeByteArray(new Uint8Array(16));event.add(4).writeU32(0xe);
    call(0xa0bfb0,'void',['pointer','pointer'])(ctx.channel,event);
    return {submitted:true,lobbyId:roster.steamLobbyId,text};
}
function servicesProbe() {
    // Read-only equivalent of B48040's service registry iteration.
    const begin = va(0xfead5c).readPointer(), end = va(0xfead60).readPointer();
    const bytes = end.sub(begin).toInt32();
    if (bytes < 0 || bytes % 4 || bytes > 128 * 4 || (bytes && begin.isNull()))
        throw Error('Invalid service registry');
    const services = [];
    for (let offset = 0; offset < bytes; offset += 4) {
        const object = begin.add(offset).readPointer();
        if (object.isNull()) continue;
        const vtable = object.readPointer();
        services.push({address:object.toString(),vtable:rva(vtable),
            kind:object.add(8).readU32(),inactive:object.add(0xd).readU8(),
            methods:[0x50,0x5c].map(at => ({offset:at,address:rva(read(vtable.add(at)))})),
            words:Array.from({length:128}, (_,i) => object.add(i*4).readU32())});
    }
    return {source:'engine_service_registry',services};
}
function requireSoloRoster() {
    const roster = lobbyProbe(true);
    if (roster.rows.length !== 1 || ![1,4].includes(roster.rows[0].typeRaw) ||
        roster.rows[0].memberIdRaw !== roster.localMemberIdRaw ||
        roster.hostMemberIdRaw !== roster.localMemberIdRaw)
        throw Error('Solo host-only roster required; refusing to interrupt another player');
    return roster;
}
function teamArmies(card) {
    const begin=card.add(0x50c).readPointer(),end=card.add(0x510).readPointer();
    const size=end.sub(begin).toInt32();
    if(size<0||size%4||size>32*4)throw Error('Invalid team vector');
    const result={};
    for(let i=0;i<size;i+=4){
        const team=begin.add(i).readPointer(),name=stringAt(team.add(0x30));
        if(['a','b'].includes(name)){
            if(result[name]!==undefined)throw Error('Duplicate team');
            result[name]=stringAt(team.add(0x2d0));
        }
    }
    return result;
}
function rosterApproval(roster) {
    return JSON.stringify({card:roster.card,service:roster.service,map:roster.map,settings:roster.settings,
        host:roster.hostMemberIdRaw,local:roster.localMemberIdRaw,
        slots:roster.slots.map(s=>[s.slotIdRaw,s.teamRaw,s.stateRaw,s.memberIdRaw]),
        members:roster.rows.map(r=>[r.memberIdRaw,r.typeRaw,r.identityWordsRaw,r.readyRaw,r.aiDifficultyRaw,r.displayName,r.armyRaw,r.teamRaw])});
}
function friendsReady(roster, minimum, aiTest=false, expectedArmies=null, earlyVotes=null, armySelection=null) {
    const early=Array.isArray(earlyVotes);
    if(early && aiTest)return false;
    const fixed=expectedArmies && Object.keys(expectedArmies).length>0;
    const mode=armySelection==null ? (fixed?1:3) : ({players:2,teams:1,alliances:3})[armySelection];
    if(mode===undefined || ((mode===1)!==Boolean(fixed)))return false;
    if(fixed && !['a','b'].every(t=>expectedArmies[t] && roster.settings.teamArmies?.[t]===expectedArmies[t]))return false;
    if(!Number.isInteger(minimum) || minimum<2 || minimum>32 || minimum%2) return false;
    if(roster.settings.maxPlayers!==minimum ||
        !['a','b'].every(t=>roster.slots.filter(s=>s.teamRaw===t).length===minimum/2)) return false;
    if(roster.localMemberIdRaw!==roster.hostMemberIdRaw || roster.settings.armySelectionMode!==mode || roster.settings.enableSpectators!==1) return false;
    const host=roster.rows.filter(r=>r.memberIdRaw===roster.localMemberIdRaw);
    if(host.length!==1 || host[0].typeRaw!==4 || host[0].teamRaw!=='spectator') return false;
    const players=roster.rows.filter(r=>r.typeRaw!==4);
    if((early ? players.length<2 || players.length>minimum : players.length!==minimum) || players.some(r=>!(aiTest==='mixed' ? [1,2] : aiTest ? [2] : [1]).includes(r.typeRaw) || ((!aiTest || r.typeRaw===1) && r.readyRaw!==1))) return false;
    if(new Set(roster.rows.map(r=>r.memberIdRaw)).size!==roster.rows.length) return false;
    if(roster.rows.some(r=>r.typeRaw===4 && (r.teamRaw!=='spectator' || roster.slots.some(s=>s.memberIdRaw===r.memberIdRaw)))) return false;
    const counts=['a','b'].map(t=>roster.slots.filter(s=>s.teamRaw===t && players.some(r=>r.memberIdRaw===s.memberIdRaw)).length);
    if(!early && counts[0]!==counts[1]) return false;
    if(early) {
        const ids=players.map(r=>String((BigInt(r.identityWordsRaw[1])<<32n)|BigInt(r.identityWordsRaw[0])));
        if(new Set(ids).size!==ids.length || new Set(earlyVotes).size!==ids.length || earlyVotes.length!==ids.length || !ids.every(id=>earlyVotes.includes(id)))return false;
    }
    return players.every(r=>roster.slots.filter(s=>s.memberIdRaw===r.memberIdRaw && ['a','b'].includes(s.teamRaw)).length===1 && (fixed || r.armyRaw)) &&
        ['a','b'].every(t=>roster.slots.some(s=>s.teamRaw===t && players.some(r=>r.memberIdRaw===s.memberIdRaw)));
}
function settingsProbe() {
    const page=lobbyPage(), panel=page.add(0x148).readPointer(), model=panel.add(0xd8).readPointer();
    const first=model.add(0x14).readPointer(), last=model.add(0x18).readPointer(), bytes=last.sub(first).toInt32();
    if (bytes<0 || bytes%0x140 || bytes>256*0x140) throw Error('Unsupported settings model');
    const entries=[];
    for(let at=0;at<bytes;at+=0x140) {
        const entry=first.add(at), begin=entry.add(0xe8).readPointer(), end=entry.add(0xec).readPointer();
        const size=end.sub(begin).toInt32(), path=[];
        if(size<0 || size%0x1c || size>32*0x1c) throw Error('Invalid settings path');
        for(let j=0;j<size;j+=0x1c) path.push(stringAt(begin.add(j)));
        const strings=[];
        for(let j=0;j<0x120;j+=4) { const text=stringAt(entry.add(j)); if(text) strings.push({offset:j,text}); }
        entries.push({address:entry.toString(),path,strings,words:Array.from({length:80},(_,i)=>entry.add(i*4).readU32())});
    }
    return {source:'native_settings_property_model',entries};
}
// @include modules/live_game_data/bridge.js
function requireSoloGame() {
    requireStage(0xe2fe30);
    const roster = requireSoloRoster(), game = findService(9);
    if (rva(read(game)) !== 0xdde5b8 || !read(game.add(0x10)).equals(ptr(roster.service)))
        throw Error('Unsupported game service or session ownership');
    return roster;
}
function requireControlledGame(options) {
    if(!options.controlled) return requireSoloGame();
    requireStage(0xe2fe30);
    const roster=lobbyProbe(true), approved=options.controlled,game=findService(9);
    const identities=roster.rows.map(r=>[r.memberIdRaw,r.typeRaw,r.identityWordsRaw,
        roster.slots.filter(s=>s.memberIdRaw===r.memberIdRaw).map(s=>[s.slotIdRaw,s.teamRaw]),r.aiDifficultyRaw]).sort((a,b)=>a[0]-b[0]);
    const friends=options.friendsCompleted===true;
    const manager=read(va(0xfed0c4));
    if(friends && (manager.isNull() || manager.add(0xc).readU32()!==3 ||
        !roster.rows.some(r=>r.memberIdRaw===roster.localMemberIdRaw && r.typeRaw===4 && r.teamRaw==='spectator')))
        throw Error('Spectator host and natural terminal state required');
    if(roster.gameStartTimeRaw!==approved.epoch || roster.steamLobbyId!==approved.lobby || roster.card!==approved.card ||
        JSON.stringify(identities)!==JSON.stringify(approved.identities) ||
        (!friends && (roster.rows.filter(r=>r.typeRaw===1).length!==1 || roster.rows.some(r=>r.typeRaw!==2 &&
            (r.typeRaw!==1 || r.memberIdRaw!==roster.localMemberIdRaw)))) || roster.hostMemberIdRaw!==roster.localMemberIdRaw ||
        rva(read(game))!==0xdde5b8 || !read(game.add(0x10)).equals(ptr(roster.service)))
        throw Error('Controlled AI match identity/roster changed; leave refused');
    return roster;
}
function completionSignature(nodes, root) {
    const indices=new Map(),signature=[];
    for(const node of nodes) {
        if(node.address!==root && !indices.has(node.parent)) continue;
        let name=node.name || '';
        if(name.toLowerCase()===node.address.toLowerCase().replace(/^0x/,'')) name='';
        signature.push([indices.has(node.parent)?indices.get(node.parent):-1,node.vtable,name,node.text || '']);
        indices.set(node.address,signature.length-1);
    }
    if(!signature.length) throw Error('Completion root missing');
    return signature;
}
function statisticsProbe(address, activePage=false, summaryOnly=false, options={}) {
    const root = ptr(address);
    if (!activePage && (rva(read(root)) !== 0xe1f69c || stringAt(root.add(0x2c)) !== 'mp_statistics'))
        throw Error('Statistics object is stale or unsupported');
    const nodes = [], seen = new Set(), omittedLists = [];
    function visit(object, parent, depth) {
        if(options.deadline!=null && Date.now()>options.deadline)
            throw Error('UI probe time budget exceeded; retry on next poll');
        if (depth > 20 || nodes.length >= 8192)
            throw Error('Statistics tree exceeds probe bounds: depth='+depth+' nodes='+nodes.length);
        if (seen.has(object.toString())) throw Error('Statistics tree contains repeated object');
        seen.add(object.toString());
        // A participant table has at most 32 players plus two teams. Identify it
        // without traversing unit-detail rows (which grow with match activity).
        if (summaryOnly && rva(read(object)) === 0xd8e30c) {
            const first=read(object.add(0x100)), last=read(object.add(0x104));
            const length=last.sub(first).toInt32();
            let participantTable=false;
            if (length>0 && length%4===0 && length<=128*4 && !first.isNull()) {
                const names=[];
                for(let at=0;at<length;at+=4) {
                    const row=read(first.add(at));
                    names.push(rva(read(row))===0xd82e0c ? stringAt(row.add(0x2c)) : null);
                }
                participantTable=names.includes('ta') && names.includes('tb') &&
                    names.every(name=>name==='ta' || name==='tb' || /^(p\d+|\d{17})$/.test(name || ''));
            }
            if(!participantTable) {
                omittedLists.push({address:object.toString(),reason:'not_participant_summary'});
                return;
            }
        }
        const begin = object.add(0x90).readPointer(), end = object.add(0x94).readPointer();
        const bytes = end.sub(begin).toInt32();
        if (bytes < 0 || bytes % 4 || bytes > 512*4) throw Error('Invalid UI children');
        nodes.push({address:object.toString(),parent,name:stringAt(object.add(0x2c)),
            vtable:rva(read(object)),text:stringAt(object.add(0x44)),
            ...(options.includeRaw===false ? {} : {rawHeaderHex:Array.from(new Uint8Array(object.readByteArray(0xa0)))
                .map(byte => byte.toString(16).padStart(2,'0')).join('')})});
        if(options.pruneName && nodes[nodes.length-1].name===options.pruneName) return;
        for (let at = 0; at < bytes; at += 4) {
            const child = begin.add(at).readPointer();
            if (child.isNull() || !read(child.add(0x9c)).equals(object)) throw Error('UI child ownership mismatch');
            visit(child,object.toString(),depth+1);
        }
        // The fixed-team lobby uses eMultiSelectListbox, a native eListbox
        // subtype with the same row vector. Restrict it to the supported lobby
        // page; do not broaden statistics/detail traversal to arbitrary types.
        const lobbyMultiSelect = activePage && rva(read(root)) === 0xe2b2cc &&
            rva(read(object)) === 0xd8e478;
        if (rva(read(object)) === 0xd8e30c || lobbyMultiSelect) {
            const first = object.add(0x100).readPointer(), last = object.add(0x104).readPointer();
            const length = last.sub(first).toInt32();
            if (length < 0 || length % 4 || length > (lobbyMultiSelect ? 128 : 8192)*4) {
                if (activePage && !lobbyMultiSelect) return; // Some inactive lobby lists are not initialized.
                throw Error('Invalid statistics list');
            }
            for (let at = 0; at < length; at += 4) {
                const row = first.add(at).readPointer();
                // Native list refresh may leave row.parent null: membership in
                // this bounded vector still establishes ownership. A different
                // non-null parent is never accepted.
                if (lobbyMultiSelect && (row.isNull() ||
                        (!read(row.add(0x9c)).isNull() && !read(row.add(0x9c)).equals(object)) ||
                        rva(read(row)) !== 0xd82e0c)) throw Error('Invalid owned lobby slot row');
                if (rva(read(row)) !== 0xd82e0c) {
                    if (activePage) {
                        const name = stringAt(row.add(0x2c));
                        if (name && /^\d+:[a-z]+$/.test(name) && !seen.has(row.toString())) visit(row,object.toString(),depth+1);
                        continue;
                    }
                    throw Error('Unsupported statistics row');
                }
                if (!seen.has(row.toString())) visit(row,object.toString(),depth+1);
            }
        }
    }
    visit(root,null,0);
    const backing=[];
    if(!activePage) {
        const panels=nodes.filter(n=>n.vtable===0xe1ef14 && n.name==='result_tab');
        if(panels.length===1) {
            const panel=ptr(panels[0].address), first=panel.add(0xd4).readPointer(),last=panel.add(0xd8).readPointer();
            const bytes=last.sub(first).toInt32();
            if(bytes<0 || bytes%0x138 || bytes>128*0x138) throw Error('Unsupported final statistics vector');
            for(let at=0;at<bytes;at+=0x138) {
                const row=first.add(at);
                backing.push({address:row.toString(),typeRaw:row.add(0x44).readU8(),teamRaw:stringAt(row.add(0x2c)),
                    displayName:stringAt(row.add(0xcc)),nativeIdRaw:row.add(0xe4).readU32(),
                    aiFlagRaw:row.add(0xe8).readU8(),steamWordsRaw:[row.add(0x130).readU32(),row.add(0x134).readU32()],
                    victoryPointsRaw:row.add(0x48).readS32(),
                    rawHex:Array.from(new Uint8Array(row.readByteArray(0x138))).map(b=>b.toString(16).padStart(2,'0')).join('')});
            }
        }
    }
    return {source:'native_statistics_ui_tree',semantics:'raw_candidates',nodes,backing,
        captureScope:summaryOnly?'player_team_summary':'full_ui',omittedLists};
}
function execute(action, options) {
    if(readOnly && action!=='probe') throw Error('Record-only mode forbids native mutations');
    if(action==='publish-browser-name') return {browser:publishBrowserName(options)};
    if (action === 'probe') {
        if (options.target === 'reload-cache') {
            if(!read(va(0xfe17d4)).isNull())throw Error('Inspect launch option before loading a world');
            for(const [address,expected] of [[0x713e40,'558bec8b5508568b'],[0x714260,'568bf1837e300075'],[0x444b30,'568bf18b462c578d']]) {
                const actual=Array.from(new Uint8Array(va(address).readByteArray(8))).map(b=>b.toString(16).padStart(2,'0')).join('');
                if(actual!==expected)throw Error('Unexpected registry routine at '+va(address));
            }
            const key=Memory.alloc(52),name=Memory.allocUtf8String('cmdline/no_reload_caching');
            call(0x713e40,'pointer',['pointer','pointer'])(key,name);
            try { return {probe:{noReloadCachingPresent:!!call(0x714260,'uint8',['pointer'])(key)}}; }
            finally { call(0x444b30,'void',['pointer'])(key); }
        }
        if (options.target === 'social') return {probe:socialProbe()};
        if (options.target === 'live') return {probe:liveProbe()};
        if (options.target === 'settings') return {probe:settingsProbe()};
        if (options.target === 'approval') {const roster=lobbyProbe(); return {probe:{roster,approval:rosterApproval(roster)}};}
        if (options.target === 'controls') return {probe:statisticsProbe(state().page,true,options.summaryOnly===true)};
        if (options.target === 'statistics') {
            const root=ptr(options.address);
            if ((root.add(0x20).readU32() & 6) !== 6) throw Error('Visible statistics dialog required');
            return {probe:statisticsProbe(root,false,options.details!==true)};
        }
        if (options.target === 'services') return {probe:servicesProbe()};
        if (options.target === 'roster') return {probe:lobbyProbe(true)};
        if (options.target && options.target !== 'lobby') throw Error('Unknown probe target');
        return {probe:lobbyProbe()};
    } else if (action === 'chat-greeting' || action === 'chat-reply') {
        return sendLobbyChat(options,false,action==='chat-reply');
    } else if (action === 'chat-announcement') {
        return sendLobbyChat(options,true);
    } else if (action === 'configure-friends') {
        const page=lobbyPage(), roster=requireSoloRoster(), setup=page.add(0x14c);
        if(rosterApproval(roster)!==options.approval) throw Error('Stale friends configuration');
        if(!setup.add(0x574).readPointer().equals(ptr(roster.card))) throw Error('Setup ownership mismatch');
        if(!read(va(0xfe17d4)).isNull())throw Error('World must be unloaded');
        if(options.teamArmies){
            for(const [address,expected] of [[0xb37ae0,'558bec81ec78020000535657'],[0x643b20,'558bec538bd95657c6432400'],[0x643be0,'558bec56578b7d088bf13bf7'],[0x643ba0,'8b4140568d712883f810720c']]){
                const actual=Array.from(new Uint8Array(va(address).readByteArray(12))).map(b=>b.toString(16).padStart(2,'0')).join('');
                if(actual!==expected)throw Error('Unsupported team nation routine');
            }
            const allowed=['ger','rus','usa','eng','jap','axis_minor','ger_ss','rus_guard'];
            if(!['a','b'].every(t=>allowed.includes(options.teamArmies[t])))throw Error('Unsupported team nation');
            const teams=teamArmies(setup);
            if(!['a','b'].every(t=>teams[t]!==undefined))throw Error('Both setup teams required');
        }
        const mode=options.armySelection==null ? (options.teamArmies?1:3) : ({players:2,teams:1,alliances:3})[options.armySelection];
        if(mode===undefined || ((mode===1)!==Boolean(options.teamArmies)))throw Error('Invalid army selection/team nations');
        // Verify the installed enum before mutating setup. Zero has no label and
        // crashes the lobby when its UI constructs a string from the null label.
        const expectedLabel=({1:'team',2:'player',3:'alliance'})[mode];
        let nativeLabel=null;
        for(let i=0;i<5;i++) {
            const entry=va(0xe27b18).add(i*8),label=entry.readPointer();
            if(label.isNull())break;
            if(entry.add(4).readU32()===mode){nativeLabel=label.readUtf8String();break;}
        }
        if(nativeLabel!==expectedLabel)throw Error('Unsupported native army selection enum');
        // Native mode setter: Players=2, Teams=1, Alliances=3. Team army is the native
        // argument at team+0x2a4, edited by the Teams-mode settings property.
        // Spectator checkbox edits the setup byte; B5E100 publishes it and rebuilds slots.
        call(0xb37ae0,'void',['pointer','int'])(setup,mode);
        if(options.teamArmies){
            teamArmies(setup); // Revalidate vector after native mode rebuild.
            const begin=setup.add(0x50c).readPointer(),end=setup.add(0x510).readPointer();
            for(let at=begin;at.compare(end)<0;at=at.add(4)){
                const team=at.readPointer(),name=stringAt(team.add(0x30));
                if(!['a','b'].includes(name))continue;
                const text=Memory.alloc(24),argument=Memory.alloc(0x44),army=options.teamArmies[name];
                text.writeUtf8String(army);text.add(16).writeU32(army.length);text.add(20).writeU32(15);
                call(0x643b20,'pointer',['pointer','pointer'])(argument,text);
                try{call(0x643be0,'pointer',['pointer','pointer'])(team.add(0x2a4),argument);}
                finally{call(0x643ba0,'void',['pointer'])(argument);}
            }
        }
        setup.add(0x22c).writeU8(1);
        for(const [field,flags] of [['main/armySelectionMode;members/;teams/;alliances/',2],['settings/enableSpectators;slots/',1]]) {
            const string=Memory.alloc(24), data=Memory.allocUtf8String(field);
            string.writePointer(data); string.add(16).writeU32(field.length); string.add(20).writeU32(field.length);
            call(0xb5e100,'void',['pointer','pointer','pointer','int'])(ptr(roster.service),setup,string,flags);
        }
        return {before:roster};
    } else if (action === 'configure-capacity') {
        const page=lobbyPage(),roster=requireSoloRoster(),setup=page.add(0x14c),n=options.players;
        if(rosterApproval(roster)!==options.approval || !Number.isInteger(n) || n<2 || n>32 || n%2)
            throw Error('Fresh approval and even playing capacity 2..32 required');
        if(options.expectedMap && roster.map!==options.expectedMap) throw Error('Select the expected map before capacity configuration');
        if(roster.rows[0].typeRaw!==4 || roster.rows[0].teamRaw!=='spectator' || roster.slots.some(s=>s.memberIdRaw!==0))
            throw Error('Empty playing slots and spectator host required for capacity configuration');
        if(!setup.add(0x574).readPointer().equals(ptr(roster.card))) throw Error('Setup ownership mismatch');
        const definition=setup.add(0x158).readPointer();
        if(definition.isNull() || n<definition.add(0x9c).readU32() || n>definition.add(0xa0).readU32())
            throw Error('Requested player count is not supported by the selected map');
        // Same session-card slot builder used by map selection (B339B0).
        // Edit the owned setup copy, rebuild slots, then publish through the engine.
        nativeMutationStarted=true;
        setup.add(0xd0).writeU32(n);
        call(0xb38690,'void',['pointer','int'])(setup,0);
        call(0xb37ae0,'void',['pointer','int'])(setup,roster.settings.armySelectionMode);
        const field='main/maxPlayers;slots/;teams/;alliances/';
        const string=Memory.alloc(24),data=Memory.allocUtf8String(field);
        string.writePointer(data);string.add(16).writeU32(field.length);string.add(20).writeU32(field.length);
        call(0xb5e100,'void',['pointer','pointer','pointer','int'])(ptr(roster.service),setup,string,2);
        // B881F0 stores this same selector preference before building the card.
        va(0xf3c680).writeU32(n);
        return {before:roster,requestedPlayers:n};
    } else if (action === 'spectate-host') {
        const page=lobbyPage(), roster=requireSoloRoster();
        if(rosterApproval(roster)!==options.approval || roster.settings.enableSpectators!==1)
            throw Error('Fresh enabled spectator lobby required');
        if(roster.rows[0].teamRaw==='spectator') return {alreadySpectator:true};
        const nodes=statisticsProbe(page,true).nodes;
        if(!nodes.some(n=>n.name==='spectator:spectator')) throw Error('Native spectator section unavailable');
        // Same self-assignment request as clicking the spectator section (B773A0/119).
        call(0xb806b0,'void',['pointer','int','pointer'])(page,-1,va(0xfebfb0));
        return {before:roster};
    } else if (action === 'assign-ai') {
        const page=lobbyPage(), roster=lobbyProbe();
        if (rosterApproval(roster) !== options.approval) throw Error('Stale approved lobby roster');
        if (roster.hostMemberIdRaw !== roster.localMemberIdRaw ||
            roster.rows.some(r=>r.typeRaw !== 2 && (![1,4].includes(r.typeRaw) || r.memberIdRaw !== roster.localMemberIdRaw)))
            throw Error('Controlled local host and AI roster required');
        const slot=roster.slots.filter(s=>s.slotIdRaw === options.slot);
        if (slot.length !== 1 || slot[0].stateRaw !== 0 || slot[0].memberIdRaw !== 0 || !['a','b'].includes(slot[0].teamRaw))
            throw Error('Current open playing slot required');
        if (!page.add(0x379).readU8()) throw Error('Current lobby does not enable native AI');
        const codes={easy:0x121,normal:0x122,hard:0x123,heroic:0x124};
        if (!codes[options.difficulty]) throw Error('Unsupported AI difficulty');
        const name=options.slot+':'+slot[0].teamRaw;
        const nodes=statisticsProbe(page,true).nodes.filter(n=>n.name===name && n.vtable===0xd82e0c);
        if (nodes.length !== 1) throw Error('Expected one owned native slot widget');
        const entry=Memory.alloc(4), vector=Memory.alloc(12);
        entry.writePointer(ptr(nodes[0].address));
        vector.writePointer(entry); vector.add(4).writePointer(entry.add(4)); vector.add(8).writePointer(entry.add(4));
        call(0xb7aef0,'void',['pointer','pointer','uint'])(page,vector,codes[options.difficulty]);
        return {before:roster,requestedSlot:options.slot,requestedDifficulty:options.difficulty};
    } else if (action === 'set-bot-army') {
        const page=lobbyPage(), roster=lobbyProbe();
        if(rosterApproval(roster)!==options.approval) throw Error('Stale approved lobby roster');
        if(roster.hostMemberIdRaw!==roster.localMemberIdRaw || roster.rows.some(r=>r.typeRaw!==2 &&
            r.memberIdRaw!==roster.localMemberIdRaw)) throw Error('Local bot lobby required');
        if(!read(va(0xfe17d4)).isNull()) throw Error('World must be unloaded before faction selection');
        if(!page.add(0x724).readPointer().equals(ptr(roster.service))) throw Error('Session service ownership mismatch');
        const members=roster.rows.filter(r=>r.memberIdRaw===options.memberId && r.typeRaw===2);
        if(members.length!==1 || !['a','b'].includes(members[0].teamRaw)) throw Error('One playing AI member required');
        if(!['ger','rus','usa','eng','jap','axis_minor','ger_ss','rus_guard'].includes(options.army))
            throw Error('Unsupported fixed faction');
        for(const [address,expected] of [[0xb5e280,'558bec83ec2456578bf98d4d'],
                [0x643b20,'558bec538bd95657c6432400'],[0x643ba0,'8b4140568d712883f810720c']]) {
            const actual=Array.from(new Uint8Array(va(address).readByteArray(12))).map(b=>b.toString(16).padStart(2,'0')).join('');
            if(actual!==expected) throw Error('Unsupported faction request routine');
        }
        if(members[0].armyRaw===options.army) return {alreadySelected:true};
        // Same temporary argument and service request as lobby event 0x128.
        const text=Memory.alloc(24),argument=Memory.alloc(0x44);
        text.writeUtf8String(options.army);text.add(16).writeU32(options.army.length);text.add(20).writeU32(15);
        call(0x643b20,'pointer',['pointer','pointer'])(argument,text);
        try {
            call(0xb5e280,'void',['pointer','uint','pointer'])(ptr(roster.service),options.memberId,argument);
        } finally {
            call(0x643ba0,'void',['pointer'])(argument);
        }
        return {before:roster,requestedMember:options.memberId,requestedArmy:options.army};
    } else if (action === 'cleanup-resources') {
        lobbyPage();
        const roster=lobbyProbe();
        if(roster.hostMemberIdRaw!==roster.localMemberIdRaw || roster.rows.some(r=>r.typeRaw!==2 &&
            r.memberIdRaw!==roster.localMemberIdRaw)) throw Error('Local bot lobby required for resource cleanup');
        if(!read(va(0xfe17d4)).isNull()) throw Error('World must be unloaded before resource cleanup');
        const signature=Array.from(new Uint8Array(va(0x9ba180).readByteArray(12))).map(b=>b.toString(16).padStart(2,'0')).join('');
        if(signature!=='558bec83ec34833dd417fe00') throw Error('Unsupported resource cleanup routine');
        const before=va(0xfbb054).readU32();
        call(0x9ba180,'void',[],'mscdecl')();
        return {resourceCleanup:{beforeResources:before,afterResources:va(0xfbb054).readU32(),
            operation:'native unloaded-world cache cleanup and unreferenced resource pruning'}};
    } else if (action === 'reset-audio-cache') {
        lobbyPage();
        const roster=lobbyProbe();
        if(roster.hostMemberIdRaw!==roster.localMemberIdRaw || roster.rows.some(r=>r.typeRaw!==2 &&
            r.memberIdRaw!==roster.localMemberIdRaw)) throw Error('Local bot lobby required for audio reset');
        if(!va(0xfe17d4).readPointer().isNull()) throw Error('World must be unloaded before audio reset');
        if(va(0xf31f88).readU32()!==0) throw Error('Audio device is disabled; reset experiment unavailable');
        for(const [address,expected] of [[0x5c3b70,'b99c1ef300e836ebffffb908'],
            [0x5c26b0,'8b41083b410c744356578b79'],[0x5c6590,'558bec81ec30010000833d88'],
            [0x5c2700,'8b41083b410c741b56578b79'],[0x5c7b70,'538bd956578b43243b432874']]) {
            const actual=Array.from(new Uint8Array(va(address).readByteArray(12))).map(b=>b.toString(16).padStart(2,'0')).join('');
            if(actual!==expected) throw Error('Unsupported audio reset routine');
        }
        function audioState() {
            const start=va(0xfb142c).readPointer(),end=va(0xfb1430).readPointer();
            const bytes=end.sub(start).toUInt32();
            if(end.compare(start)<0 || bytes%8 || bytes>8000000) throw Error('Invalid audio cache vector');
            return {sampleEntries:bytes/8,keyEntries:va(0xfb1428).readU32(),
                disabled:va(0xf31f88).readU32()!==0,resources:va(0xfbb054).readU32()};
        }
        const before=audioState();
        // Native settings-apply wrapper closes streams, resets the device/cache,
        // then reopens streams at saved positions. Never call a raw destructor.
        call(0x5c3b70,'void',[],'mscdecl')();
        const after=audioState();
        if(after.disabled) throw Error('Audio reset disabled the device; preserve game for inspection');
        return {audioReset:{before,after,operation:'native audio settings reset in unloaded bot lobby'}};
    } else if (action === 'optimize-heap') {
        lobbyPage();
        const roster=lobbyProbe();
        if(roster.hostMemberIdRaw!==roster.localMemberIdRaw || roster.rows.some(r=>r.typeRaw!==2 &&
            r.memberIdRaw!==roster.localMemberIdRaw)) throw Error('Local bot lobby required for heap experiment');
        const info=Memory.alloc(8);
        info.writeU32(1);info.add(4).writeU32(0);
        const optimize=new SystemFunction(Process.getModuleByName('kernel32.dll').getExportByName('HeapSetInformation'),
            'int',['pointer','int','pointer','uint'],'stdcall');
        nativeMutationStarted=true;
        const result=optimize(ptr(0),3,info,8);
        return {heapOptimization:{success:result.value!==0,lastError:result.value?0:result.lastError,
            operation:'HeapOptimizeResources',scope:'unused LFH caches; no arbitrary frees'}};
    } else if (action === 'configure-ai') {
        const page=lobbyPage(), roster=lobbyProbe(), setup=page.add(0x14c);
        if (rosterApproval(roster)!==options.approval) throw Error('Stale approved lobby settings/roster');
        if (roster.hostMemberIdRaw!==roster.localMemberIdRaw || roster.rows.some(r=>r.typeRaw!==2 &&
            (![1,4].includes(r.typeRaw) || r.memberIdRaw!==roster.localMemberIdRaw))) throw Error('Controlled local roster required');
        if (![75,200].includes(options.victoryPoints) || options.totalManpower!==10000) throw Error('Unsupported AI test profile');
        if (roster.settings.victoryPointsMin>options.victoryPoints || roster.settings.victoryPointsMax<options.victoryPoints)
            throw Error('Exact requested VP unavailable');
        if (!setup.add(0x574).readPointer().equals(ptr(roster.card))) throw Error('Setup card ownership mismatch');
        // The VP control inlines this range-checked assignment in B40A80.
        // Resource editing calls B3E500. Commit exact fields via the native session
        // update handler B5E100, as the lobby does after processing edits.
        call(0xb3e500,'void',['pointer','int'])(setup,10000);
        if (setup.add(0x1f8).readFloat()!==10000) throw Error('Native resource handler cannot represent exact 10000 MP');
        setup.add(0x1e8).writeS32(options.victoryPoints);
        for(const field of ['settings/scoreFinal','settings/resourceAmount']) {
            const string=Memory.alloc(24), data=Memory.allocUtf8String(field);
            string.writePointer(data); string.add(16).writeU32(field.length); string.add(20).writeU32(field.length);
            call(0xb5e100,'void',['pointer','pointer','pointer','int'])(ptr(roster.service),setup,string,0);
        }
        return {before:roster,requested:{victoryPoints:options.victoryPoints,totalManpower:10000}};
    } else if (action === 'exit-completed') {
        const roster=requireControlledGame(options),manager=read(va(0xfed0c4));
        if(manager.isNull() || manager.add(0xc).readU32()!==3) throw Error('Native terminal state required');
        const nodes=statisticsProbe(state().page,true,true).nodes,roots=nodes.filter(n=>n.name==='mp_result' && n.vtable===0xe2f8a4);
        if(roots.length!==1 || roots[0].address!==options.address) throw Error('Saved completion overlay changed');
        if(JSON.stringify(completionSignature(nodes,roots[0].address))!==JSON.stringify(options.signature))
            throw Error('Completion structure or values changed after save');
        call(0xa1df80,'void',['pointer','uint','uint'])(ptr(roots[0].address),5,0);
        return {roster};
    } else if (action === 'dismiss-results') {
        requireStage(0xe2fee8);
        if(options.epoch) {
            const roster=lobbyProbe();
            if(roster.gameStartTimeRaw!==options.epoch || roster.steamLobbyId!==options.lobby)
                throw Error('Saved results generation/lobby changed');
        }
        const root = ptr(options.address);
        if (rva(read(root)) !== 0xe1f69c || stringAt(root.add(0x2c)) !== 'mp_statistics' ||
            (root.add(0x20).readU32() & 6) !== 6) throw Error('Visible statistics dialog required');
        call(0xa1df80,'void',['pointer','uint','uint'])(root,6,0);
        return {}; // The handler may free root; observe UI again instead of dereferencing it.
    } else if (action === 'results') {
        requireStage(0xe2fee8);
        const root = ptr(options.address);
        if (rva(read(root)) !== 0xe1f69c || stringAt(root.add(0x2c)) !== 'mp_statistics' ||
            (root.add(0x20).readU32() & 6) !== 6) throw Error('Visible statistics dialog required');
        const tabs = read(root.add(0x138)), header = read(tabs.add(0xd0));
        if (rva(read(tabs)) !== 0xe10f44 || rva(read(header)) !== 0xe0f490)
            throw Error('Unsupported statistics tab control');
        const first = header.add(0x90).readPointer(), last = header.add(0x94).readPointer();
        const size = last.sub(first).toInt32();
        if (size < 0 || size % 4 || size > 16*4) throw Error('Invalid statistics tabs');
        const matches = [];
        for (let at = 0; at < size; at += 4) {
            const tab = first.add(at).readPointer();
            if (stringAt(tab.add(0x2c)) === 'result_tab' && rva(read(tab)) === 0xe0f6f8)
                matches.push(at/4);
        }
        if (matches.length !== 1) throw Error('Expected one Game Result tab');
        if (header.add(0xd0).readS32() !== matches[0])
            call(0xa31910,'void',['pointer','int'])(header,matches[0]);
        if (header.add(0xd0).readS32() !== matches[0]) throw Error('Game Result tab did not activate');
        return {probe:statisticsProbe(root,false,options.details!==true),selectedTab:matches[0]};
    } else if (action === 'ai-joinability') {
        if (readOnly) throw Error('Record-only mode forbids lobby isolation');
        lobbyPage();
        const roster = lobbyProbe(), humans = roster.rows.filter(row => row.typeRaw !== 2);
        if (humans.length !== 1 || humans[0].typeRaw !== 1 ||
            humans[0].memberIdRaw !== roster.localMemberIdRaw ||
            roster.localMemberIdRaw !== roster.hostMemberIdRaw || !['open', 'closed'].includes(options.joinability))
            throw Error('Local human host and bots only required for AI joinability');
        const steam = Process.getModuleByName('steam_api.dll');
        const matchmaking = new NativeFunction(steam.getExportByName('SteamMatchmaking'), 'pointer', [], 'mscdecl')();
        if (matchmaking.isNull() || roster.steamLobbyId === '0') throw Error('Steam lobby unavailable');
        // SteamMatchMaking009 slot 34, independently identified by the loaded
        // proxy's SetLobbyJoinable label and 12-byte x86 callee stack cleanup.
        const setter = matchmaking.readPointer().add(34 * 4).readPointer();
        const set = new NativeFunction(setter, 'bool', ['pointer', 'uint64', 'bool'], 'thiscall');
        nativeMutationStarted = true;
        const joinable = options.joinability === 'open';
        if (!set(matchmaking, uint64(roster.steamLobbyId), joinable ? 1 : 0)) throw Error('Steam rejected lobby joinability');
        return {lobbyId:roster.steamLobbyId, joinable, accepted:true,
            scope:'Steam admission only; existing native roster and gameplay are unchanged'};
    } else if (action === 'menu') {
        const roster = requireControlledGame(options);
        if (state().pageVtable !== 0xe2ae58) throw Error('Loaded gameplay HUD required');
        call(0xa89200,'void',[],'mscdecl')();
        return {roster};
    } else if (action === 'request-quit') {
        const roster = requireControlledGame(options), s = state();
        if (s.pageVtable !== 0xe216cc || s.pageName !== 'game_menu' || quitRequest)
            throw Error('Active game menu and no pending quit required');
        quitRequest = {menu:ptr(s.page),card:roster.card,identity:roster.rows[0].identityWordsRaw.join(':'),dialog:null};
        const message = Memory.alloc(32);
        message.add(4).writeU32(0x117);
        call(0xae5910,'void',['pointer','pointer'])(quitRequest.menu,message);
        return {roster}; // Controller inspects the actual dialog binding before Yes.
    } else if (action === 'confirm-quit') {
        const roster = requireControlledGame(options), s = state();
        const request = {dialog:ptr(options.dialog),menu:ptr(options.menu),card:options.card,identity:options.identity};
        if (s.page !== request.menu.toString() || rva(read(request.dialog)) !== 0xd9f9f4 ||
            stringAt(request.dialog.add(0x2c)) !== 'POPUP' ||
            s.pageVtable !== 0xe216cc || roster.card !== request.card ||
            roster.rows[0].identityWordsRaw.join(':') !== request.identity)
            throw Error('Stale or missing solo quit confirmation');
        const begin = request.dialog.add(0x84).readPointer(), end = request.dialog.add(0x88).readPointer();
        const size = end.sub(begin).toInt32();
        if (size < 0 || size % 20 || size > 128*20) throw Error('Invalid confirmation bindings');
        let binding = false;
        for (let at = 0; at < size; at += 20) {
            const entry = begin.add(at);
            if (entry.readU32() === 7 && entry.add(4).readU32() === 0x118 &&
                entry.add(12).readPointer().equals(request.menu)) binding = true;
        }
        if (!binding) throw Error('Close confirmation binding no longer exists');
        quitRequest = null; // Never replay Yes after a timeout or exception.
        call(0xa1df80,'void',['pointer','uint','uint'])(request.dialog,7,0);
        return {trigger:'host_requested_quit',roster};
    } else if (action === 'internet') {
        const s = state();
        if (s.core !== '0x0' || s.pageVtable !== 0xe212f8) throw Error('Expected a clean main menu');
        call(0xafb460,'void',[],'mscdecl')();
    } else if (action === 'setup') {
        const current=state();
        const browser=current.stageVtable===0xe2fd94 && current.pageVtable===0xe2a3d0 && current.pageName==='mp_lobbyinet';
        if(current.stageVtable!==0xe2fcc4 && !browser) throw Error('Internet screen or lobby browser required');
        if(!read(va(0xfe17d4)).isNull()) throw Error('World must be unloaded before hosting');
        const stage = call(0xbb3030,'pointer',[],'mscdecl')();
        if (stage.isNull()) throw Error('Stage allocation failed');
        call(0xbb1c50,'void',['pointer'])(stage);
    } else if (action === 'create') {
        requireStage(0xe2fd60);
        const widget = ptr(options.widget), page = read(va(0xfeaac0));
        if (rva(read(widget)) !== 0xe2bea8 || !read(widget.add(0x9c)).equals(page))
            throw Error('Create widget does not belong to active page');
        if (read(widget.add(0xd0)).isNull()) throw Error('Create widget has no session card');
        // The full routine copies selected map/rules/password into the card
        // before dispatching Create. Calling B6F410 directly skips that work.
        call(0xb881f0,'void',['pointer'])(widget);
    } else if (['ready','gate','start'].includes(action)) {
        const page = lobbyPage();
        const startingRoster = action === 'start' ? (options.solo ? requireSoloRoster() : lobbyProbe()) : null;
        if(action==='start' && options.friends) {
            if(Array.isArray(options.earlyVotes) && startingRoster.gameStartTimeRaw!==options.expectedEpoch)throw Error('Early-start match generation changed');
            if(rosterApproval(startingRoster)!==options.approval || !friendsReady(startingRoster,options.minimum,options.aiTest==='mixed' ? 'mixed' : options.aiTest===true,options.teamArmies,options.earlyVotes,options.armySelection))
                throw Error('Friends readiness/profile changed before Start');
        }
        if (action==='start' && options.ai) {
            if (rosterApproval(startingRoster)!==options.approval) throw Error('Stale approved Start');
            const r=startingRoster, humans=r.rows.filter(m=>m.typeRaw!==2);
            const bots=r.rows.filter(m=>m.typeRaw===2);
            const teamOf=m=>r.slots.find(s=>s.memberIdRaw===m.memberIdRaw)?.teamRaw;
            const soloHeroic=humans.length===1 && bots.length===3 &&
                ['a','b'].includes(teamOf(humans[0])) && bots.every(m=>m.aiDifficultyRaw==='heroic' &&
                    teamOf(m)===(teamOf(humans[0])==='a'?'b':'a'));
            if(humans.length!==1 || humans[0].typeRaw!==1 || humans[0].memberIdRaw!==r.localMemberIdRaw ||
                r.hostMemberIdRaw!==r.localMemberIdRaw || !humans[0].readyRaw ||
                (!soloHeroic && !['a','b'].every(team=>r.slots.some(s=>s.teamRaw===team && r.rows.some(m=>m.typeRaw===2 && m.memberIdRaw===s.memberIdRaw)))) ||
                new Set(r.rows.map(m=>m.memberIdRaw)).size!==r.rows.length ||
                r.rows.some(m=>r.slots.filter(s=>s.memberIdRaw===m.memberIdRaw).length!==1 || !['a','b'].includes(teamOf(m))) ||
                ![75,200].includes(options.victoryPoints ?? 75) ||
                r.settings.victoryPoints!==(options.victoryPoints ?? 75) || r.settings.totalManpower!==10000)
                throw Error('Approved opposing AI profile is no longer satisfied');
        }
        if (action === 'gate') return {startAllowed:!!call(0xb7fe30,'char',['pointer'])(page)};
        if (action === 'ready') {
            const roster = lobbyProbe();
            const local = roster.rows.filter(row => row.memberIdRaw === roster.localMemberIdRaw);
            if (local.length !== 1 || ![0,1].includes(local[0].readyRaw))
                throw Error('Cannot establish local readiness');
            if (local[0].readyRaw === 1) return {alreadyReady:true};
        }
        if (action === 'start' && !call(0xb7fe30,'char',['pointer'])(page))
            throw Error('The engine Start gate is closed');
        const message = Memory.alloc(32);
        message.add(4).writeU32(action === 'ready' ? 0x10a : 0x10c);
        call(0xb773a0,'void',['pointer','pointer'])(page,message);
        if (startingRoster) return {startingRoster};
    } else throw Error('Unknown command: '+action);
    return {};
}
// Hook a returning function, not an instruction inside the never-returning
// main loop: the latter prevents Frida from unloading its script cleanly.
Interceptor.attach(va(0x7105a0), {
    onEnter() { this.mainTick = this.returnAddress.equals(va(0x663314)); },
    onLeave() {
        if (!this.mainTick) return;
        ticks++; loopThread = Process.getCurrentThreadId();
        if (!pending || running) return;
        const job = pending; pending = null;
        if (Date.now() > job.deadline) { job.resolve({ok:false,error:'Command expired before execution'}); return; }
        running = true;
        nativeMutationStarted=false;
        send({event:'command_begin',action:job.action,target:job.options.target,thread:loopThread});
        try {
            const result = execute(job.action,job.options);
            job.resolve({ok:true,...result,state:state()});
            send({event:'command_return',action:job.action,state:state()});
        } catch (error) {
            send({event:'command_error',action:job.action,target:job.options.target,error:String(error),stack:error.stack,mutationStarted:nativeMutationStarted});
            job.resolve({ok:false,error:String(error),mutationStarted:nativeMutationStarted,state:state()});
        } finally { running = false; }
    }
});
for (const [name,address] of Object.entries({stage_activate:0xbb1c50,game_stage_create:0xbb3330,game_stage_enter:0xbb5d70})) {
    Interceptor.attach(va(address), {
        onEnter() { send({event:name,thread:Process.getCurrentThreadId(),object:this.context.ecx.toString()}); },
        onLeave() { if (name === 'game_stage_enter') send({event:'game_stage_enter_return',state:state()}); }
    });
}
Interceptor.attach(va(0xb764c0),{
    onEnter(args) {
        if(args[0].readU32()===0x491) {
            completionEvent={source:'native_multiplayer_GameOver_message',code:0x491,observedAt:Date.now()};
            send({event:'native_game_over',...completionEvent,state:state()});
        }
    }
});
// Passive Steam LobbyChatUpdate callback. Registration at 0x66ffe0 pushes
// callback ID 506 and binds 0x670740. The handler tests flags at +0x18
// against 0x1e, and reads changed Steam ID at +8. Older proxy notes mislabel IDs.
// A Steam 'left' event is NOT proof of intentional in-game abandonment.
try {
    const address=0x670740;
    const signature=Array.from(new Uint8Array(va(address).readByteArray(8))).map(b=>b.toString(16).padStart(2,'0')).join('');
    if(signature!=='558bec8b450883ec') throw Error('Membership callback signature mismatch');
    const flagsCheck=Array.from(new Uint8Array(va(0x67076f).readByteArray(4))).map(b=>b.toString(16).padStart(2,'0')).join('');
    if(flagsCheck!=='f640181e') throw Error('Membership flags layout mismatch');
    Interceptor.attach(va(address),{
        onEnter(args) {
            try {
                const p=args[0],s=state(),manager=read(va(0xfed0c4));
                send({event:'native_lobby_membership',source:'native_0x670740_Steam_callback_506',
                    observed_at_ms:Date.now(),lobby_id:p.readU64().toString(),
                    steam_id:p.add(8).readU64().toString(),actor_steam_id:p.add(16).readU64().toString(),
                    flags:p.add(24).readU32(),page_vtable:s.pageVtable,
                    manager_state:manager.isNull()?null:manager.add(0xc).readU32(),
                    raw_hex:Array.from(new Uint8Array(p.readByteArray(28))).map(b=>b.toString(16).padStart(2,'0')).join('')});
            } catch(error) { send({event:'membership_capture_error',error:String(error)}); }
        }
    });
    send({event:'membership_capture_ready',address:'0x670740',callback_id:506});
} catch(error) { send({event:'membership_capture_unavailable',error:String(error)}); }
rpc.exports = {
    state,
    readonly() { readOnly=true; return true; },
    command(action,options={},timeoutMs=15000) {
        if (pending || running) throw Error('Another command is in progress');
        return new Promise(resolve => { pending={action,options,resolve,deadline:Date.now()+timeoutMs}; });
    }
};
