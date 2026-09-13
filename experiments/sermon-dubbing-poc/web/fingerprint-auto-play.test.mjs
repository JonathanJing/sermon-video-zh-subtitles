import test from 'node:test';
import assert from 'node:assert/strict';
import {createFingerprintController,playAlignmentAudio} from './fingerprint-ui.mjs';
const flush=()=>new Promise(r=>setImmediate(r));
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function setup(options={}){
 const sha='a'.repeat(64);let time=10000,position=0,paused=0;const seeks=[],plays=[],states=[],jobs=[];
 const context={week:{id:'week',sourceStartSeconds:1793,audioFingerprint:{schemaVersion:'sermon-audio-fingerprint-binding-v1',algorithmVersion:'spectral-landmarks-v1',pageId:'week',sourceSha256:sha,trackSha256:sha,indexSha256:sha,indexUrl:'/fingerprints/test.json',sourceStartSeconds:1793,sourceEndSeconds:4033,captureSeconds:10}},track:{id:'sync',sha256:sha,durationSeconds:2240},generation:1,ready:true};
 const h={seeks,plays,states,jobs,context,clock:value=>time=value,position:value=>position=value,paused:()=>paused};
 h.controller=createFingerprintController({context:()=>context,now:()=>time,position:()=>position,pause:()=>paused++,seek:(value,flags)=>{seeks.push({value,...flags});position=value;return true;},play:args=>{plays.push(args);return options.play?.(args,h);},onState:s=>states.push(s),supported:()=>true,capture:async()=>({samples:new Float32Array(8),sampleRate:8000,durationSeconds:10,endedAt:10000}),match:async()=>({result:{matched:true,queryStartSeconds:100,confidence:1}}),timers:{setTimeout(fn,ms){const j={fn,ms};jobs.push(j);return j;},clearTimeout(j){if(j)j.cancelled=true;}},...options.controller});return h;
}
test('reliable result starts automatically, own play event is allowed, success clears anchor',async()=>{
 const d=deferred(),h=setup({play:()=>d.promise});await h.controller.start();assert.equal(h.plays.length,1);assert.equal(h.controller.getState().phase,'play_starting');assert.equal(h.seeks[0].value,110);h.controller.playbackStarted();assert.equal(h.controller.getState().phase,'play_starting');assert.equal(h.controller.apply(),false);d.resolve();await flush();assert.equal(h.controller.getState().phase,'applied');assert.equal(h.controller.apply(),false);const pauses=h.paused();h.controller.invalidate();assert.equal(h.paused(),pauses);
});
test('blocked autoplay retains anchor; click recalculates now and preserves original undo point',async()=>{
 let attempts=0;const h=setup({play:()=>++attempts===1?Promise.reject(new DOMException('blocked','NotAllowedError')):Promise.resolve()});await h.controller.start();await flush();assert.equal(h.controller.getState().phase,'play_blocked');h.clock(16500);assert.equal(h.controller.apply(),true);assert.equal(h.plays.length,2,'play must be in click, before awaiting');assert.equal(h.seeks.at(-1).value,116.5);assert.equal(h.seeks.at(-1).correction,true);await flush();assert.equal(h.controller.getState().phase,'applied');
});
test('slow native playback gets one latest-position correction without a tracking loop',async()=>{
 const d=deferred(),h=setup({play:()=>d.promise});await h.controller.start();h.clock(14000);h.position(110.1);d.resolve();await flush();assert.deepEqual(h.seeks,[{value:110,correction:false},{value:114,correction:true}]);h.clock(18000);await flush();assert.equal(h.seeks.length,2);assert.equal(h.controller.getState().phase,'applied');
});
test('metadata wait preserves the same anchor for manual retry',async()=>{
 const h=setup();h.context.ready=false;await h.controller.start();assert.equal(h.controller.getState().phase,'play_failed');assert.equal(h.seeks.length,0);h.context.ready=true;h.clock(12000);h.controller.apply();await flush();assert.equal(h.seeks[0].value,112);assert.equal(h.controller.getState().phase,'applied');
});
test('TTL stops pending playback and rejects a late completion',async()=>{
 const d=deferred(),h=setup({play:()=>d.promise});await h.controller.start();h.clock(25000);h.jobs.find(j=>j.ms===15000).fn();assert.ok(h.plays[0].signal.aborted);assert.equal(h.controller.getState().phase,'expired');d.resolve();await flush();assert.equal(h.controller.getState().phase,'expired');assert.equal(h.controller.apply(),false);
});
test('cancelled A completion cannot change or stop B',async()=>{
 const a=deferred(),b=deferred();let count=0;const h=setup({play:()=>++count===1?a.promise:b.promise});await h.controller.start();h.controller.cancel();await h.controller.start();const pauses=h.paused();a.reject(new Error('late'));await flush();assert.equal(h.paused(),pauses);assert.equal(h.controller.getState().phase,'play_starting');b.resolve();await flush();assert.equal(h.controller.getState().phase,'applied');
});
test('low confidence never automatically seeks or plays',async()=>{
 const h=setup({controller:{match:async()=>({result:{matched:false,diagnostics:{reason:'low_confidence'}}})}});await h.controller.start();assert.equal(h.seeks.length,0);assert.equal(h.plays.length,0);assert.equal(h.controller.getState().phase,'no_match');
});
class Audio extends EventTarget {constructor(){super();this.paused=true;this.pauses=0;this.pending=deferred();}play(){this.paused=false;this.dispatchEvent(new Event('play'));return this.pending.promise;}pause(){this.paused=true;this.pauses++;}}
test('native helper waits for play promise, not the early play event',async()=>{const audio=new Audio(),abort=new AbortController();let complete=false;const p=playAlignmentAudio(audio,{signal:abort.signal}).then(()=>complete=true);await flush();assert.equal(complete,false);audio.pending.resolve();await p;assert.equal(complete,true);assert.equal(audio.pauses,0);});
test('native cancel settles once; late reject cannot pause a newer manual play',async()=>{const audio=new Audio(),abort=new AbortController();const p=playAlignmentAudio(audio,{signal:abort.signal});abort.abort();await assert.rejects(p,{name:'AbortError'});const pauses=audio.pauses;audio.paused=false;audio.pending.reject(new Error('late'));await flush();assert.equal(audio.pauses,pauses);assert.equal(audio.paused,false);});
test('native timeout releases pending playback and cleans the timer',async()=>{const audio=new Audio();let timeout,cleared=false;const p=playAlignmentAudio(audio,{signal:new AbortController().signal,timers:{setTimeout(fn,ms){assert.equal(ms,8000);timeout=fn;return 1;},clearTimeout(){cleared=true;}}});timeout();await assert.rejects(p,/audio_play_timeout/);assert.equal(audio.paused,true);assert.equal(cleared,true);audio.pending.resolve();await flush();assert.equal(audio.pauses,1);});
test('native denied or malformed rejection cannot report success',async()=>{for(const error of [new DOMException('denied','NotAllowedError'),undefined]){const audio=new Audio();const p=playAlignmentAudio(audio,{signal:new AbortController().signal});audio.pending.reject(error);await assert.rejects(p);assert.equal(audio.paused,true);}});
