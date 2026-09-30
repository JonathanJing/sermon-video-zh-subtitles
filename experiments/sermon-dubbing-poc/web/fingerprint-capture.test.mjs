import test from 'node:test';
import assert from 'node:assert/strict';
import {captureFingerprintAttempt as captureFingerprintAudio, captureFingerprintAudio as captureWithRecovery} from './fingerprint-capture.mjs';
const flush=()=>new Promise(r=>setImmediate(r));
function make({muted=false,state='running',latePermission=false,resumePending=false, recovery=false,onTiming=()=>{},clock=()=>12000,microphoneBudgetMs}={}) {
 const stats={stops:0,closes:0,connects:0,preparing:0,recording:0,requests:0},jobs=[];let ctx,node,grant;
 class Track extends EventTarget {constructor(){super();this.muted=muted;this.readyState='live';}stop(){stats.stops++;this.readyState='ended';}}
 const track=new Track(),stream={getTracks:()=>[track],getAudioTracks:()=>[track]};
 class Context extends EventTarget {constructor(){super();ctx=this;this.state=state;this.currentTime=20;this.audioWorklet={addModule:async()=>{}};this.destination={};}resume(){return resumePending?new Promise(()=>{}):Promise.resolve();}close(){stats.closes++;this.state='closed';return Promise.resolve();}createMediaStreamSource(){return {connect(){stats.connects++;},disconnect(){}};}createGain(){return {gain:{},connect(){},disconnect(){}};}}
 class Node {constructor(){node=this;this.port={close(){},onmessage:null};}connect(){}disconnect(){}}
 const env={isSecureContext:true,navigator:{mediaDevices:{getUserMedia:()=>{stats.requests++;return latePermission?new Promise(r=>grant=r):Promise.resolve(stream);}}},AudioContext:Context,AudioWorkletNode:Node,Worker:class{},crypto:{subtle:{}},performance:{now:clock},setTimeout(fn,ms){const job={fn,ms,cancelled:false};jobs.push(job);return job;},clearTimeout(job){if(job)job.cancelled=true;}};
 const abort=new AbortController();const p=(recovery?captureWithRecovery:captureFingerprintAudio)({signal:abort.signal,env,onTiming,microphoneBudgetMs,onPreparing(){stats.preparing++;},onRecording(){stats.recording++;}});p.catch(()=>{});
 return {p,abort,track,stats,jobs,env,grant:()=>grant(stream),get context(){return ctx;},get node(){return node;},started(){node.port.onmessage({data:{started:true,startContextTime:10}});},complete(){node.port.onmessage({data:{samples:new Float32Array(480000),sampleRate:48000,endContextTime:20}});}};
}
test('startup mute waits before connecting PCM; unmute starts a fresh full capture',async()=>{
 const h=make({muted:true});try {await flush();assert.equal(h.stats.recording,0);assert.equal(h.stats.connects,0,'muted route must not feed zero PCM into recorder');h.track.muted=false;h.track.dispatchEvent(new Event('unmute'));await flush();assert.equal(h.stats.connects,1);assert.equal(h.stats.recording,0);h.started();h.complete();const r=await h.p;assert.equal(r.durationSeconds,10);assert.equal(h.stats.recording,1);assert.equal(h.stats.stops,1);}finally{h.abort.abort();}
});
test('startup interrupted context waits and does not announce recording',async()=>{
 const h=make({state:'interrupted'});try {await flush();assert.equal(h.stats.connects,0);assert.equal(h.stats.recording,0);h.context.state='running';h.context.dispatchEvent(new Event('statechange'));await flush();assert.equal(h.stats.connects,1);h.started();h.complete();await h.p;}finally{h.abort.abort();}
});
test('normal graph setup announces preparing, first PCM alone announces recording',async()=>{
 const h=make();try {await flush();assert.equal(h.stats.preparing,1);assert.equal(h.stats.recording,0);h.started();assert.equal(h.stats.recording,1);assert.ok(h.jobs.find(j=>j.ms===5000).cancelled);h.complete();const r=await h.p;assert.equal(r.durationSeconds,10);assert.equal(r.endedAt,12000);assert.equal(h.stats.stops,1);assert.equal(h.stats.closes,1);}finally{h.abort.abort();}
});
test('5-second startup deadline covers unresolved resume and cleans resources',async()=>{
 const h=make({resumePending:true});await flush();assert.equal(h.stats.preparing,1);const timer=h.jobs.find(j=>j.ms===5000);assert.ok(timer);timer.fn();await assert.rejects(h.p,/capture_start_timeout/);assert.equal(h.stats.recording,0);assert.equal(h.stats.stops,1);assert.equal(h.stats.closes,1);
});
test('never-unmuted or never-running route reaches the same 5-second deadline',async()=>{
 for(const options of [{muted:true},{state:'interrupted'}]){const h=make(options);await flush();const timer=h.jobs.find(j=>j.ms===5000);assert.ok(timer);assert.equal(h.jobs.filter(j=>j.ms===5000).length,1);timer.fn();await assert.rejects(h.p,/capture_start_timeout/);assert.equal(h.stats.connects,0);assert.equal(h.stats.recording,0);assert.equal(h.stats.stops,1);assert.equal(h.stats.closes,1);}
});
test('three cancelled permission attempts clean late streams independently',async()=>{
 const attempts=[make({latePermission:true}),make({latePermission:true}),make({latePermission:true})];for(const h of attempts){h.abort.abort();await assert.rejects(h.p,{name:'AbortError'});}for(const h of attempts.toReversed()){h.grant();await flush();assert.equal(h.stats.stops,1);assert.equal(h.stats.closes,1);assert.equal(h.stats.recording,0);}
});
test('after started, mute and context interruption fail instead of pausing the PCM',async()=>{
 for(const kind of ['mute','context']){const h=make();await flush();h.started();if(kind==='mute'){h.track.muted=true;h.track.dispatchEvent(new Event('mute'));}else{h.context.state='interrupted';h.context.dispatchEvent(new Event('statechange'));}await assert.rejects(h.p,/interrupted/);assert.equal(h.stats.stops,1);assert.equal(h.stats.closes,1);}
});

test('transient failure cleans the attempt before bounded retry and returns only new PCM',async()=>{
 const h=make({recovery:true});await flush();const oldNode=h.node;h.started();oldNode.port.onmessage({data:{error:'capture_interrupted',captureDetail:'frame_gap'}});await flush();assert.equal(h.stats.stops,1);assert.equal(h.stats.closes,1);assert.equal(oldNode.port.onmessage,null);
 h.track.readyState='live';h.jobs.find(j=>j.ms===600&&!j.cancelled).fn();await flush();assert.notEqual(h.node,oldNode);h.started();h.complete();const r=await h.p;assert.equal(r.samples.length,480000);assert.equal(h.stats.stops,2);assert.equal(h.stats.closes,2);
});
test('cancelling recovery delay never opens another microphone',async()=>{
 const h=make({recovery:true});await flush();h.started();h.node.port.onmessage({data:{error:'capture_interrupted',captureDetail:'empty_input'}});await flush();h.abort.abort();await assert.rejects(h.p,{name:'AbortError'});assert.equal(h.stats.connects,1);assert.equal(h.stats.stops,1);assert.ok(h.jobs.find(j=>j.ms===600).cancelled);
});
test('permanent repeated interruptions stop after three complete attempts',async()=>{
 const h=make({recovery:true});await flush();for(let i=0;i<3;i++) {h.started();h.node.port.onmessage({data:{error:'capture_interrupted',captureDetail:'frame_gap'}});await flush();if(i<2){h.track.readyState='live';const timer=h.jobs.find(j=>j.ms===600&&!j.cancelled);assert.ok(timer);timer.fn();await flush();}}
 await assert.rejects(h.p,e=>e.message==='capture_interrupted'&&e.captureDetail==='frame_gap');assert.equal(h.stats.stops,3);assert.equal(h.stats.closes,3);assert.equal(h.jobs.filter(j=>j.ms===600).length,2);
});
test('malformed channel input is not retried',async()=>{
 const h=make({recovery:true});await flush();h.started();h.node.port.onmessage({data:{error:'capture_interrupted',captureDetail:'channel_shape'}});await assert.rejects(h.p,/capture_interrupted/);assert.equal(h.jobs.filter(j=>j.ms===600).length,0);
});

 test('diagnostic callback failure happens after cleanup and cannot reject a valid capture',async()=>{
 let observations=0;const h=make({onTiming(value){observations++;assert.equal(h.stats.stops,1);assert.equal(h.stats.closes,1);assert.equal(value.microphoneObservedMs,0);throw new Error('broken diagnostic consumer');}});
 await flush();h.started();h.complete();const result=await h.p;assert.equal(result.durationSeconds,10);assert.equal(observations,1);assert.equal(h.node.port.onmessage,null);
});
test('diagnostic timing on failed attempts does not change retry and cancellation cleanup',async()=>{
 const observations=[];const h=make({recovery:true,onTiming:value=>observations.push(value)});await flush();h.started();h.node.port.onmessage({data:{error:'capture_interrupted',captureDetail:'frame_gap'}});await flush();assert.equal(observations.length,1);assert.equal(h.stats.stops,1);h.abort.abort();await assert.rejects(h.p,{name:'AbortError'});assert.equal(h.stats.stops,1);
});

test('microphone budget: the deadline begins at permission grant and stops retained input',async()=>{
 let clock=0;const timing=[];const h=make({clock:()=>clock,onTiming:v=>timing.push(v)});
 try {await flush();const timer=h.jobs.find(j=>j.ms===15000);assert.ok(timer);h.started();clock=15000;timer.fn();await assert.rejects(h.p,/capture_budget_exhausted/);assert.equal(h.stats.stops,1);assert.equal(h.stats.closes,1);assert.equal(h.node.port.onmessage,null);assert.equal(timing[0].microphoneObservedMs,15000);assert.ok(timer.cancelled);}finally{h.abort.abort();}
});
test('microphone budget: six spent seconds cannot reopen for another full ten-second capture',async()=>{
 let clock=0;const h=make({recovery:true,clock:()=>clock});
 try {await flush();h.started();clock=6000;h.node.port.onmessage({data:{error:'capture_interrupted',captureDetail:'frame_gap'}});await flush();assert.equal(h.jobs.filter(j=>j.ms===600&&!j.cancelled).length,0);await assert.rejects(h.p,/capture_budget_exhausted/);assert.equal(h.stats.requests,1);assert.equal(h.stats.stops,1);}finally{h.abort.abort();}
});
test('microphone budget: a retry inherits remaining time and returns only its continuous PCM',async()=>{
 let clock=0;const timing=[];const h=make({recovery:true,clock:()=>clock,onTiming:v=>timing.push(v)});
 try {await flush();h.started();clock=3000;const old=h.node;old.port.onmessage({data:{error:'capture_interrupted',captureDetail:'frame_gap'}});await flush();assert.equal(h.stats.stops,1);h.track.readyState='live';h.jobs.find(j=>j.ms===600&&!j.cancelled).fn();await flush();assert.ok(h.jobs.some(j=>j.ms===12000&&!j.cancelled));assert.notEqual(h.node,old);h.started();clock=13000;h.complete();const value=await h.p;assert.equal(value.durationSeconds,10);assert.equal(value.samples.length,480000);assert.deepEqual(timing.map(v=>v.microphoneObservedMs),[3000,10000]);assert.equal(h.stats.requests,2);assert.equal(h.stats.stops,2);}finally{h.abort.abort();}
});
test('microphone budget: startup and late interruption spend the same allowance',async()=>{
 let clock=0;const h=make({recovery:true,clock:()=>clock});
 try {await flush();clock=4500;h.started();clock=13500;h.node.port.onmessage({data:{error:'capture_interrupted',captureDetail:'frame_gap'}});await flush();assert.equal(h.jobs.filter(j=>j.ms===600&&!j.cancelled).length,0);await assert.rejects(h.p,/capture_budget_exhausted/);assert.equal(h.stats.requests,1);assert.equal(h.stats.stops,1);}finally{h.abort.abort();}
});
test('microphone budget: a delayed completed buffer cannot beat an overdue main-thread timer',async()=>{
 let clock=0;const h=make({clock:()=>clock});
 try {await flush();h.started();clock=16000;h.complete();await assert.rejects(h.p,/capture_budget_exhausted/);assert.equal(h.stats.stops,1);assert.equal(h.stats.closes,1);}finally{h.abort.abort();}
});
test('microphone budget: diagnostic mutation or failure cannot replenish spent time',async()=>{
 let clock=0;const h=make({recovery:true,clock:()=>clock,onTiming:v=>{v.microphoneObservedMs=0;throw Error('broken consumer');}});
 try {await flush();h.started();clock=6000;h.node.port.onmessage({data:{error:'capture_interrupted',captureDetail:'frame_gap'}});await flush();assert.equal(h.jobs.filter(j=>j.ms===600&&!j.cancelled).length,0);await assert.rejects(h.p,/capture_budget_exhausted/);assert.equal(h.stats.requests,1);}finally{h.abort.abort();}
});
test('microphone budget: permission wait is separate and does not invent occupied input time',async()=>{
 let clock=0;const timing=[];const h=make({latePermission:true,clock:()=>clock,onTiming:v=>timing.push(v)});
 try {await flush();assert.equal(h.jobs.some(j=>j.ms===15000),false);clock=70000;h.grant();await flush();assert.ok(h.jobs.some(j=>j.ms===15000&&!j.cancelled));h.started();clock=80000;h.complete();await h.p;assert.equal(timing[0].permissionMs,70000);assert.equal(timing[0].microphoneObservedMs,10000);}finally{h.abort.abort();}
});
test('microphone budget: cancellation clears the active deadline and all input',async()=>{
 const h=make();try {await flush();const timer=h.jobs.find(j=>j.ms===15000);assert.ok(timer);h.started();h.abort.abort();await assert.rejects(h.p,{name:'AbortError'});assert.ok(timer.cancelled);assert.equal(h.stats.stops,1);assert.equal(h.node.port.onmessage,null);}finally{h.abort.abort();}
});
test('microphone budget: invalid or enlarged allowance cannot request the microphone',async()=>{
 for(const budget of [20000,Infinity,NaN,-1,9000]){const h=make({microphoneBudgetMs:budget});try {await flush();assert.equal(h.stats.requests,0);await assert.rejects(h.p,/capture_budget_exhausted/);}finally{h.abort.abort();}}
});
