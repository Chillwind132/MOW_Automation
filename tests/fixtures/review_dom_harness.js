// Minimal DOM test double; executes the real page script against the real HTTP API.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2],'utf8'),origin=process.argv[3];
class Element {
 constructor(){this.value='';this.children=[];this.textContent='';this.events={};this.validity='';this.attributes={};}
 append(child){this.children.push(child)}
 replaceChildren(){this.children=[]}
 setAttribute(key,value){this.attributes[key]=value}
 addEventListener(name,fn){this.events[name]=fn}
 setCustomValidity(message){this.validity=message}
 reportValidity(){return !this.validity}
 showModal(){this.open=true}
 close(){this.open=false;this.events.close?.()}
}
const channels=[];
class Channel {
 constructor(){channels.push(this)}
 postMessage(data){for(const channel of channels)if(channel!==this)channel.onmessage?.({data})}
}
function openPage(){
const elements=new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element()]));
elements.get('data').textContent=html.match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/)[1];
elements.get('outcome').value='all';
const context={document:{getElementById:id=>elements.get(id),createElement:()=>new Element(),createElementNS:()=>new Element()},
 location:{protocol:'http:',reload(){}},AbortController,setTimeout,clearTimeout,BroadcastChannel:Channel,
 fetch:(path,options={})=>fetch(new URL(path,origin),{...options,headers:{...options.headers,Origin:origin}})};
vm.runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],context);
return elements;
}
const elements=openPage(),otherPage=openPage();
(async()=>{
 assert.ok(!elements.get('decisionSection').open);
 elements.get('list').children[0].children[1].onclick();
 assert.equal(elements.get('decisionSection').open,true);
 assert.equal(elements.get('decisionFields').disabled,false);
 assert.equal(elements.has('winnerRobz'),false);
 assert.equal(elements.get('winnerConfirm').disabled,true);
 await elements.get('winnerA').onclick();
 assert.equal(elements.get('winnerConfirm').disabled,true);
 elements.get('winnerReason').value='Team B conceded in the UI test.';
 elements.get('winnerReason').events.input();
 await elements.get('winnerB').onclick();
 assert.equal(elements.get('winnerB').attributes['aria-pressed'],'true');
 await elements.get('winnerA').onclick();
 assert.equal(elements.get('winnerB').attributes['aria-pressed'],'false');
 assert.equal(elements.get('winnerConfirm').disabled,false);
 const before=await (await fetch(origin+'/api/matches')).json();
 assert.equal(before.matches[0].winner,null,'Selection must not save before Confirm');
 await elements.get('winnerConfirm').onclick();
 assert.equal(elements.get('decisionSection').open,false);
 assert.equal(elements.get('manualReason').hidden,false);
 assert.equal(elements.get('manualReasonText').textContent,'Team B conceded in the UI test.');
 assert.equal(elements.get('list').children[0].children[0].children.at(-1).textContent,'Manual winner');
 assert.match(elements.get('title').textContent,/Team A wins/);
 assert.equal(elements.has('metadata'),false);
 const saved=await (await fetch(origin+'/api/matches')).json();
 assert.equal(saved.matches[0].metadata.operator_adjudication.reason,'Team B conceded in the UI test.');
 for(let i=0;i<100&&otherPage.get('manualReason').hidden;i++)await new Promise(resolve=>setTimeout(resolve,10));
 assert.equal(otherPage.get('manualReason').hidden,false);
 assert.match(otherPage.get('title').textContent,/Team A wins/);
 elements.get('playerRatingNav').onclick();
 assert.equal(elements.get('matchPanel').hidden,true);
 assert.equal(elements.get('ratingPanel').hidden,false);
 assert.equal(elements.get('players').hidden,true);
 assert.equal(elements.get('list').children.length,2);
 assert.equal(elements.get('ratingStats').children[2].children[1].textContent,'100%');
 assert.equal(elements.get('ratingHistory').children[0].children[2].textContent,'Win');
 assert.equal(elements.get('ratingTrend').children[0].attributes.role,'img');
 elements.get('list').children[1].onclick();
 assert.equal(elements.get('ratingStats').children[2].children[1].textContent,'0%');
 assert.equal(elements.get('ratingHistory').children[0].children[2].textContent,'Loss');
 elements.get('search').value='no-such-player';elements.get('search').events.input();
 assert.equal(elements.get('ratingContent').hidden,true);
 assert.equal(elements.get('list').textContent,'No players found.');
 elements.get('savedGamesNav').onclick();
 assert.equal(elements.get('search').value,'');
 assert.equal(elements.get('matchPanel').hidden,false);
 elements.get('playerRatingNav').onclick();
 assert.equal(elements.get('search').value,'no-such-player');
 elements.get('search').value='';elements.get('search').events.input();
 elements.get('ratingHistory').children[0].children[1].children[0].onclick();
 assert.equal(elements.get('matchPanel').hidden,false);
 assert.match(elements.get('title').textContent,/Team A wins/);
})().catch(error=>{console.error(error);process.exitCode=1});
