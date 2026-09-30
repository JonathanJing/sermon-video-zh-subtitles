const listen=async controller=>{await controller.start();if(controller.getState().phase==='ready_to_record')return controller.start();};
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { captureQuality, summarizeMatch, diagnosticSummary } from './fingerprint-diagnostics.mjs';
import { createFingerprintController } from './fingerprint-ui.mjs';
import { fingerprint, matchFingerprint } from './fingerprint-core.mjs';

const sha = 'a'.repeat(64);
const metadata = { schemaVersion:'sermon-audio-fingerprint-binding-v1',algorithmVersion:'spectral-landmarks-v1',pageId:'week',sourceSha256:sha,trackSha256:sha,indexSha256:sha,indexUrl:'/fingerprints/abc.json',captureSeconds:10,sourceStartSeconds:100,sourceEndSeconds:300 };
const context = () => ({week:{id:'week',sourceStartSeconds:100,audioFingerprint:metadata},track:{id:'track',sha256:sha,durationSeconds:200},ready:true});

test('quality bands are coarse and do not confuse clipping, volume and correctness', () => {
  assert.deepEqual(captureQuality(new Float32Array(100), 0), {level:'silent',clipping:'none'});
  const samples = new Float32Array(100); samples[0] = 1;
  assert.deepEqual(captureQuality(samples, .005), {level:'low',clipping:'1_to_5_percent'});
  samples.fill(-1);
  assert.deepEqual(captureQuality(samples, .1), {level:'high',clipping:'over_5_percent'});
  samples[0] = NaN;
  assert.deepEqual(captureQuality(samples, 1), {level:'unknown',clipping:'unknown'});
});

test('final whitelist strips raw features, private labels, paths, message and unknown values', () => {
  const secret = 'private-device-and-room-name';
  const d = diagnosticSummary({phase:secret,errorCode:secret,deviceId:secret,route:secret,content:{sourceSha256:sha,pageId:secret,url:secret},attempts:Infinity,
    timings:{totalMs:1234,permissionMs:-1,matchMs:secret,PCM:secret},
    match:{reason:secret,level:secret,clipping:secret,landmarks:83,peaks:18,votes:NaN,features:[secret],message:secret},PCM:secret});
  assert.ok(!JSON.stringify(d).includes(secret));
  assert.equal(d.timings.totalMs,1200); assert.equal(d.timings.permissionMs,null);
  assert.equal(d.match.reason,'unknown'); assert.equal(d.match.votes,null);
  assert.deepEqual(d.content,{sourceSha256:sha}); assert.equal(d.route,'unknown');
  assert.equal(d.audibleOutputMs,null); assert.equal(d.captionAlignmentMs,null);
  assert.ok(!('confidence' in d.match));
});

test('silent real DSP exposes only aggregate quality and no landmarks', () => {
  const samples = new Float32Array(80000), query = fingerprint(samples,8000);
  const result = matchFingerprint(query,{schemaVersion:'sermon-landmark-index-v1',algorithmVersion:'spectral-landmarks-v1',sampleRate:8000,hopSize:256,postings:{},durationSeconds:200});
  const summary = summarizeMatch(query,result,captureQuality(samples,query.rms));
  assert.equal(summary.reason,'silence'); assert.equal(summary.level,'silent');
  assert.equal(typeof summary.landmarks,'number'); assert.ok(!JSON.stringify(summary).includes('queryStart'));
});

test('retries accumulate observed microphone time; operation elapsed is not summed phases', async () => {
  let clock = 0, seeks = 0;
  const controller = createFingerprintController({prepare:async()=>({close(){}}),context,now:()=>clock,supported:()=>true,pause(){},seek(){seeks++;},play(){},timers:{setTimeout(){},clearTimeout(){}},
    capture:async({onTiming})=>{
      onTiming({permissionMs:200,startupMs:100,captureMs:300,microphoneObservedMs:400});
      onTiming({permissionMs:100,startupMs:200,captureMs:10000,microphoneObservedMs:10200});
      clock=12000; return {samples:new Float32Array(80000),sampleRate:8000,durationSeconds:10,endedAt:clock};
    },match:async()=>{clock=12500;return {result:{matched:false,diagnostics:{reason:'ambiguous'}},summary:{reason:'ambiguous',landmarks:500},timings:{indexMs:300,featureMs:100,matchMs:100}};}});
  await listen(controller); const d = controller.getDiagnostics();
  assert.equal(d.attempts,2); assert.equal(d.timings.microphoneObservedMs,10600);
  assert.equal(d.timings.captureMs,10300); assert.equal(d.timings.totalMs,12500);
  assert.equal(d.timings.workerMs,500); assert.equal(d.match.reason,'ambiguous'); assert.equal(seeks,0);
  d.match.reason='private'; assert.equal(controller.getDiagnostics().match.reason,'ambiguous');
});

test('unknown matcher reasons never enter controller state or alter no-seek behavior', async () => {
  const events=[];
  const controller=createFingerprintController({prepare:async()=>({close(){}}),context,now:()=>10000,supported:()=>true,pause(){},seek(){assert.fail('seek');},play(){assert.fail('play');},onState:e=>events.push(e),timers:{setTimeout(){},clearTimeout(){}},capture:async()=>({durationSeconds:10,endedAt:10000}),match:async()=>({result:{matched:false,diagnostics:{reason:'private-device-label'}}})});
  await listen(controller); assert.equal(controller.getState().reason,'unknown');
  assert.ok(!JSON.stringify(events).includes('private-device-label'));
});

test('late timing callback from cancelled attempt cannot contaminate new session', async () => {
  let firstTiming, finish, attempts=0;
  const controller=createFingerprintController({prepare:async()=>({close(){}}),context,now:()=>10000,supported:()=>true,pause(){},seek(){},play(){},timers:{setTimeout(){},clearTimeout(){}},capture:async({onTiming})=>{
    if (++attempts===1) {firstTiming=onTiming;return new Promise(r=>finish=r);}
    onTiming({microphoneObservedMs:10000}); return {durationSeconds:10,endedAt:10000};
  },match:async()=>({result:{matched:false}})});
  const old=listen(controller);await new Promise(r=>setImmediate(r));await listen(controller);firstTiming({microphoneObservedMs:5000});finish({durationSeconds:10,endedAt:10000});await old;
  assert.equal(controller.getDiagnostics().attempts,1);assert.equal(controller.getDiagnostics().timings.microphoneObservedMs,10000);
});

test('worker clears PCM on index failure and returns fixed code instead of raw exception', async () => {
  const code=fs.readFileSync(new URL('./fingerprint-worker.mjs',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');
  const replies=[];const samples=new Float32Array([.5,.5]);
  const scope={self:{location:{href:'https://example.test/fingerprint-worker.mjs',origin:'https://example.test'},postMessage:v=>replies.push(v)},performance:{now:()=>0},URL,Float32Array,fetch:async()=>{throw new Error('private-network-details');}};
  vm.runInNewContext(code,scope);await scope.self.onmessage({data:{samples,sampleRate:8000,metadata,requestId:1}});
  assert.deepEqual([...samples],[0,0]);assert.equal(replies[0].error,'match_failed');assert.ok(!JSON.stringify(replies).includes('private'));
});
