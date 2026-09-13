import test from 'node:test';
import assert from 'node:assert/strict';
import { createFingerprintController, fingerprintBinding, matchInWorker } from './fingerprint-ui.mjs';
import { captureFingerprintAudio } from './fingerprint-capture.mjs';
const sha = 'a'.repeat(64), trackSha = 'b'.repeat(64);
const metadata = { schemaVersion:'sermon-audio-fingerprint-binding-v1', algorithmVersion:'spectral-landmarks-v1', pageId:'week',sourceSha256:sha,trackSha256:trackSha,indexSha256:'c'.repeat(64),indexUrl:'/fingerprints/abc.json',captureSeconds:10,sourceStartSeconds:1793,sourceEndSeconds:4033 };
function harness(overrides = {}) {
  let current = { week:{id:'week',sourceStartSeconds:1793,audioFingerprint:{...metadata}},track:{id:'synced',sha256:trackSha,durationSeconds:2240},generation:1,ready:true };
  let clock=10000, seekCalls=[],playCalls=0,pauseCalls=0,states=[],jobs=[];
  const timers={setTimeout(fn,ms){const job={fn,ms};jobs.push(job);return job;},clearTimeout(job){if(job)job.cancelled=true;}};
  const controller=createFingerprintController({context:()=>current,pause:()=>pauseCalls++,seek:x=>{seekCalls.push(x);return true;},play:()=>{playCalls++;},autoApply:false,now:()=>clock,timers,supported:()=>true,onState:x=>states.push(x),capture:async()=>({samples:new Float32Array(80000),sampleRate:8000,durationSeconds:10,endedAt:10000}),match:async()=>({result:{matched:true,queryStartSeconds:100,confidence:.9},durationSeconds:10}),...overrides});
  return {controller,timers,jobs,states,seekCalls,setClock:x=>clock=x,setContext:x=>current=x,get context(){return current;},get playCalls(){return playCalls;},get pauseCalls(){return pauseCalls;}};
}
test('bind only exact source, track, window, page, metadata schema',()=>{
 const h=harness();assert.ok(fingerprintBinding(h.context));
 for(const mutation of [c=>delete c.week.audioFingerprint,c=>c.track.sha256=sha,c=>c.week.id='other',c=>c.week.sourceStartSeconds=0,c=>c.week.sourceEndSeconds=4000,c=>c.week.audioFingerprint.indexUrl='https://elsewhere/a.json',c=>c.week.audioFingerprint.captureSeconds=20]){let c=structuredClone(h.context);mutation(c);assert.equal(fingerprintBinding(c),null);}
});
test('start pauses but never seeks; apply adds PCM duration and monotonic latency once in gesture',async()=>{
 const h=harness();await h.controller.start();assert.equal(h.pauseCalls,1);assert.equal(h.playCalls,0);assert.equal(h.seekCalls.length,0);assert.equal(h.controller.getState().sourceTimeSeconds,1903);h.setClock(12500);assert.equal(h.controller.apply(),true);assert.deepEqual(h.seekCalls,[112.5]);assert.equal(h.playCalls,1);assert.equal(h.controller.apply(),false);
});
test('no match, ambiguity and silence never seek',async()=>{
 for(const reason of ['silence','ambiguous','low_confidence']){const h=harness({match:async()=>({result:{matched:false,diagnostics:{reason}}})});await h.controller.start();assert.equal(h.controller.getState().phase,'no_match');assert.equal(h.controller.apply(),false);assert.deepEqual(h.seekCalls,[]);}
});
test('expired result, changed generation or source reject apply',async()=>{
 for(const change of [h=>h.setClock(26000),h=>h.context.generation++,h=>h.context.track.sha256=sha]){const h=harness();await h.controller.start();change(h);assert.equal(h.controller.apply(),false);assert.deepEqual(h.seekCalls,[]);}
});
test('expire timer discards result',async()=>{const h=harness();await h.controller.start();h.jobs.find(x=>x.ms===15000).fn();assert.equal(h.controller.getState().phase,'expired');assert.equal(h.controller.apply(),false);});
test('late result after cancel or week switch is discarded',async()=>{
 for(const action of ['cancel','switch']){let resolve;const h=harness({match:()=>new Promise(r=>resolve=r)});const pending=h.controller.start();await Promise.resolve();action==='cancel'?h.controller.cancel():h.context.generation++;resolve({result:{matched:true,queryStartSeconds:100,confidence:1}});await pending;assert.equal(h.controller.apply(),false);assert.deepEqual(h.seekCalls,[]);}
});
test('concurrent restart never accepts stale first recording',async()=>{
 let resolves=[];const h=harness({capture:()=>new Promise(r=>resolves.push(r))});const a=h.controller.start(),b=h.controller.start();const recording={samples:new Float32Array(80000),sampleRate:8000,durationSeconds:10,endedAt:10000};resolves[1](recording);await b;resolves[0](recording);await a;assert.equal(h.controller.getState().phase,'matched');assert.equal(h.controller.apply(),true);assert.equal(h.seekCalls.length,1);
});
test('unsupported and denied permissions leave playback paused or untouched without seek',async()=>{
 const unsupported=harness({supported:()=>false});await unsupported.controller.start();assert.equal(unsupported.controller.getState().phase,'unsupported');assert.equal(unsupported.pauseCalls,0);
 const denied=harness({capture:async()=>{throw new DOMException('No','NotAllowedError');}});await denied.controller.start();assert.equal(denied.controller.getState().phase,'permission_denied');assert.equal(denied.pauseCalls,1);assert.equal(denied.playCalls,0);
});
test('capture timeout aborts and releases operation',async()=>{
 let signal;const h=harness({capture:({signal:s})=>{signal=s;return new Promise((_,reject)=>s.addEventListener('abort',()=>reject(new DOMException('stop','AbortError'))));}});const pending=h.controller.start();h.jobs.find(x=>x.ms===35000).fn();await pending;assert.ok(signal.aborted);assert.equal(h.controller.getState().phase,'timeout');
});
test('out-of-window match and wait past sermon end reject instead of clamp',async()=>{
 const h=harness({match:async()=>({result:{matched:true,queryStartSeconds:2228,confidence:.9}})});await h.controller.start();h.setClock(13000);assert.equal(h.controller.apply(),false);assert.deepEqual(h.seekCalls,[]);
});
test('manual operation invalidates candidate without auto resume',async()=>{const h=harness();await h.controller.start();h.controller.invalidate();assert.equal(h.controller.apply(),false);assert.equal(h.playCalls,0);});
test('worker terminates on cancellation and transmits PCM only to local worker',async()=>{
 let instance;class Worker {constructor(url,options){instance=this;this.url=url;this.options=options;}postMessage(data,transfer){this.data=data;this.transfer=transfer;}terminate(){this.stopped=true;}}
 const signal=new AbortController();const pcm=new Float32Array(80);const pending=matchInWorker({samples:pcm,sampleRate:8000},metadata,signal.signal,Worker);signal.abort();await assert.rejects(pending,{name:'AbortError'});assert.ok(instance.stopped);assert.equal(instance.options.type,'module');assert.equal(instance.transfer[0],pcm.buffer);
});
test('late microphone permission after cancellation stops tracks and closes context',async()=>{
 let resolve,stops=0,closes=0;
 class Context {state='running';resume(){return Promise.resolve();}close(){closes++;this.state='closed';return Promise.resolve();}}
 const env={isSecureContext:true,AudioContext:Context,AudioWorkletNode:function(){},Worker:function(){},crypto:{subtle:{}},navigator:{mediaDevices:{getUserMedia:()=>new Promise(r=>resolve=r)}}};
 const abort=new AbortController();const pending=captureFingerprintAudio({signal:abort.signal,env});abort.abort();await assert.rejects(pending,{name:'AbortError'});resolve({getTracks:()=>[{stop(){stops++;}}]});await Promise.resolve();assert.equal(stops,1);assert.equal(closes,1);
});
test('capture maps final PCM render time to monotonic time and releases every resource',async()=>{
 let node,stops=0,closes=0,disconnects=0,context;
 class Track extends EventTarget {stop(){stops++;}}
 const track=new Track();const stream={getTracks:()=>[track],getAudioTracks:()=>[track]};
 class Context extends EventTarget {state='running';currentTime=20.25;constructor(){super();context=this;this.audioWorklet={addModule:async()=>{}};this.destination={};}resume(){return Promise.resolve();}createMediaStreamSource(){return{connect(){},disconnect(){disconnects++;}};}createGain(){return{gain:{},connect(){},disconnect(){disconnects++;}};}close(){closes++;this.state='closed';return Promise.resolve();}}
 class Node {constructor(){node=this;this.port={close(){}};}connect(){queueMicrotask(()=>this.port.onmessage({data:{samples:new Float32Array(80000),sampleRate:8000,endContextTime:20}}));}disconnect(){disconnects++;}}
 const env={isSecureContext:true,AudioContext:Context,AudioWorkletNode:Node,Worker:function(){},crypto:{subtle:{}},navigator:{mediaDevices:{getUserMedia:async()=>stream}},performance:{now:()=>30000}};
 const recording=await captureFingerprintAudio({signal:new AbortController().signal,env});assert.equal(recording.endedAt,29750);assert.equal(recording.durationSeconds,10);assert.equal(stops,1);assert.equal(closes,1);assert.equal(disconnects,3);assert.equal(node.port.onmessage,null);
});
test('worklet rejects discontinuous frames and empty input instead of concatenating gaps',async()=>{
 const {readFile}=await import('node:fs/promises');const {default:vm}=await import('node:vm');const code=await readFile(new URL('./fingerprint-worklet.mjs',import.meta.url),'utf8');let Processor,messages=[];
 const scope={AudioWorkletProcessor:class{constructor(){this.port={postMessage:x=>messages.push(x)};}},Float32Array,sampleRate:8000,currentFrame:0,registerProcessor:(name,klass)=>Processor=klass};vm.createContext(scope);vm.runInContext(code,scope);
 const processor=new Processor({processorOptions:{seconds:10}});
 for(let i=0;i<11;i++){scope.currentFrame=i*128;assert.equal(processor.process([[new Float32Array(128)]]),true);}
 assert.ok(messages.some(m=>m.started));scope.currentFrame+=256;
 assert.equal(processor.process([[new Float32Array(128)]]),false);assert.equal(messages.at(-1).error,'capture_interrupted');assert.equal(messages.at(-1).captureDetail,'frame_gap');
 const other=new Processor({processorOptions:{seconds:10}});let active=true;
 for(let i=0;i<189&&active;i++){scope.currentFrame+=128;active=other.process([[]]);}
 assert.equal(active,false);assert.equal(messages.at(-1).error,'capture_start_timeout');
});
