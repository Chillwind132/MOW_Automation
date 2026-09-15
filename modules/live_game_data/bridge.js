let hudCache=null, completionEvent=null;
function liveProbe() {
    const s=state(), manager=read(va(0xfed0c4));
    const result={source:'native_live_observation',observedAt:Date.now(),state:s,
        manager:manager.toString(),managerVtable:rva(read(manager)),
        managerStateRaw:manager.isNull()?null:manager.add(0xc).readU32(),
        hud:[],outcome:null,completionEvent};
    if(s.pageVtable!==0xe2ae58) {hudCache=null; return result;}
    try {
        result.playerStatistics=battleStatisticsProbe(manager);
    } catch(error) {
        result.playerStatistics={status:'unavailable',source:'native_battle_counters',error:String(error)};
    }
    try {
        readLiveHud(s,result);
        result.hudStatus='observed';
    } catch(error) {
        // HUD widgets can be rebuilt while the same gameplay page survives.
        // Discard the entire sample and rediscover next poll; never reuse cells
        // whose ownership failed, or lose match/finish observation over UI churn.
        hudCache=null;
        result.hud=[];
        result.hudStatus='unavailable';
        result.hudError=String(error);
    }
    return result;
}
function battleStatisticsProbe(manager) {
    // Passive equivalents of BC28C0/BC2D20 and AD1BF0 (retail 3.262.1).
    // Never invoke their native builders: they allocate and update game state.
    if(rva(read(manager))!==0xe317f0) throw Error('Unsupported battle manager');
    const card=manager.add(0x58).readPointer(),epoch=stringAt(card.add(0x544));
    if(rva(read(card))!==0xe274dc || !epoch) throw Error('Missing battle generation');
    const owner=va(0xfe41d8).readPointer(),stats=owner.add(0x114).readPointer();
    if(rva(read(stats))!==0xe07e08) throw Error('Unsupported combat statistics');
    const deadline=Date.now()+25;
    function vector(address,stride,limit) {
        const first=address.readPointer(),last=address.add(4).readPointer(),end=address.add(8).readPointer();
        const size=last.sub(first).toInt32(),capacity=end.sub(first).toInt32();
        if(size<0 || size%stride || size>stride*limit || capacity<size || (size && first.isNull()))
            throw Error('Invalid battle statistics vector');
        return Array.from({length:size/stride},(_,i)=>first.add(i*stride));
    }
    const scores=vector(manager.add(0x8c),0x5c,64).map(row=>{
        const key=stringAt(row.add(0x44)),values=Array.from({length:6},(_,i)=>row.add(i*4).readFloat());
        if(key===null || values.some(v=>!Number.isFinite(v))) throw Error('Invalid battle score');
        return {key,values};
    });
    if(new Set(scores.map(s=>s.key)).size!==scores.length) throw Error('Duplicate battle score identity');
    function resources(slot) {
        const table=stats.add(0x58+slot*4).readPointer();
        if(table.isNull()) return null;
        if(rva(read(table))!==0xe07dec || table.add(4).readU8()!==slot) throw Error('Resource owner mismatch');
        const head=table.add(8).readPointer(),count=table.add(12).readU32();
        if(count>2048 || head.add(13).readU8()!==1) throw Error('Invalid resource tree');
        const entries=[],seen=new Set();
        function visit(node,parent) {
            if(node.equals(head)) return;
            if(Date.now()>deadline || seen.size>=count || seen.has(node.toString()) ||
                node.add(13).readU8()!==0 || !node.add(4).readPointer().equals(parent))
                throw Error('Invalid resource tree ownership/budget');
            seen.add(node.toString());
            visit(node.readPointer(),node);
            const value=node.add(16),category=stringAt(value.add(0x30)),amount=value.add(0x48).readFloat();
            if(category===null || !Number.isFinite(amount) || amount<0) throw Error('Invalid resource amount');
            entries.push({category,amount});
            visit(node.add(8).readPointer(),node);
        }
        visit(head.add(4).readPointer(),head);
        if(seen.size!==count || table.add(12).readU32()!==count) throw Error('Resource tree changed');
        const pair=[0,0];
        for(const entry of entries) {
            const index=entry.category==='special'?1:0;
            pair[index]=Math.trunc(Math.fround(pair[index]+entry.amount));
        }
        return {pair,entries};
    }
    const players=vector(manager.add(0x68),4,18).map(address=>{
        if(Date.now()>deadline) throw Error('Battle statistics time budget exceeded');
        const player=address.readPointer(),memberId=player.readU32(),slot=player.add(4).readU8();
        if(slot>=18) throw Error('Unsupported battle player slot');
        const counters=stats.add(0x10+slot*4).readPointer();
        let infantry=null,vehicles=null;
        if(!counters.isNull()) {
            if(rva(read(counters))!==0xe07db4 || counters.add(4).readU8()!==slot)
                throw Error('Combat counter owner mismatch');
            infantry=[counters.add(8).readU32(),counters.add(0x14).readU32()];
            vehicles=[counters.add(0x2c).readU32(),counters.add(0x38).readU32()];
        }
        const score=scores.find(s=>s.key===String(slot)),resource=resources(slot);
        return {nativeMemberId:memberId,gamePlayerSlot:slot,displayName:stringAt(player.add(8)),
            team:stringAt(player.add(0x4c)),steamWords:[player.add(0xec).readU32(),player.add(0xf0).readU32()],
            ai:player.add(0xf5).readU8()!==0,infantry,vehicles,
            score:score?Math.trunc(score.values[2]):null,resources:resource?resource.pair:null,
            resourceEntries:resource?resource.entries:null};
    });
    if(new Set(players.map(p=>p.nativeMemberId)).size!==players.length ||
        new Set(players.map(p=>p.gamePlayerSlot)).size!==players.length) throw Error('Duplicate battle player identity');
    if(!va(0xfed0c4).readPointer().equals(manager) || !owner.add(0x114).readPointer().equals(stats) ||
        stringAt(card.add(0x544))!==epoch) throw Error('Battle generation changed');
    return {status:'observed',source:'native_battle_counters',nativeGameStartTime:epoch,
        manager:manager.toString(),statistics:stats.toString(),players,scores,
        pairedCounterMeanings:['enemy_kills','losses'],resourcePairMeanings:['non_special','special']};
}
function readLiveHud(s,result) {
    if(!hudCache || hudCache.page!==s.page) {
        const nodes=statisticsProbe(s.page,true).nodes, byId=new Map(nodes.map(n=>[n.address,n]));
        const selected=nodes.filter(n=> {
            const text=(n.text||'').replace(/<[^>]*>/g,'').trim();
            return /^\d+:\d\d$/.test(text) || /^\d+ \/ \d+( MP| CP)?$/.test(text);
        });
        if(selected.length>24) throw Error('Ambiguous live HUD counters');
        hudCache={page:s.page,nodes:selected.map(n=>{
            const chain=[]; let current=n;
            while(current) {chain.push({address:current.address,vtable:current.vtable,parent:current.parent});current=byId.get(current.parent);}
            return {address:n.address,name:n.name,chain};
        })};
    }
    for(const node of hudCache.nodes) {
        for(const link of node.chain) {
            const object=ptr(link.address);
            if(rva(read(object))!==link.vtable || (link.parent && !read(object.add(0x9c)).equals(ptr(link.parent)))) {
                hudCache=null; throw Error('Live HUD ownership changed');
            }
        }
        result.hud.push({address:node.address,name:node.name,rawText:stringAt(ptr(node.address).add(0x44)),
            team:null,scope:'observed_HUD_cell_unmapped',source:'validated_HUD_ownership_chain'});
    }
}
