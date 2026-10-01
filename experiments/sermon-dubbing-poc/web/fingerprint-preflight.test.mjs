import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createHash, webcrypto } from 'node:crypto';
import { CONFIG, fingerprint, matchFingerprint } from './fingerprint-core.mjs';
import { captureQuality, summarizeMatch } from './fingerprint-diagnostics.mjs';
import { prepareInWorker } from './fingerprint-ui.mjs';
const sourceSha256='a'.repeat(64),trackSha256='b'.repeat(64);
const base={schemaVersion:'sermon-landmark-index-v1',algorithmVersion:CONFIG.algorithmVersion,pageId:'week',sourceSha256,trackSha256,sourceStartSeconds:20,sourceEndSeconds:220,durationSeconds:200,sampleRate:8000,hopSize:256,postings:{'123':[1,20]}};
const code=fs.readFileSync(new URL('./fingerprint-worker.mjs',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');
function worker(index=base,{status=true,hash,fetchError}={}){
 const bytes=new TextEncoder().encode(JSON.stringify(index));
 const metadata={schemaVersion:'sermon-audio-fingerprint-binding-v1',algorithmVersion:CONFIG.algorithmVersion,pageId:'week',sourceSha256,trackSha256,sourceStartSeconds:20,sourceEndSeconds:220,captureSeconds:10,indexUrl:'/fingerprints/week.json',indexSha256:hash||createHash('sha256').update(bytes).digest('hex')};
 let requests=0;const replies=[],calls=[];
 const scope={CONFIG,fingerprint,matchFingerprint,captureQuality,summarizeMatch,TextDecoder,Uint8Array,Float32Array,URL,crypto:webcrypto,performance,
  self:{location:{href:'https://example.test/fingerprint-worker.mjs',origin:'https://example.test'},postMessage:value=>replies.push(value)},
  fetch:async(url,options)=>{requests++;calls.push({url:String(url),options});if(fetchError)throw new Error(fetchError);return{ok:status,arrayBuffer:async()=>bytes.buffer};}};
 vm.runInNewContext(code,scope);
 return{metadata,replies,calls,get requests(){return requests;},async send(operation,extra={}){await scope.self.onmessage({data:{operation,metadata,requestId:replies.length+1,...extra}});return replies.at(-1);}};
}
test('real worker verifies SHA and index before PCM, reuses admitted bytes without another fetch',async()=>{
 const w=worker();assert.equal((await w.send('prepare')).ready,true);assert.equal(w.requests,1);
 assert.equal((await w.send('prepare')).ready,true);assert.equal(w.requests,1);
 const samples=new Float32Array(80000);const result=await w.send('match',{samples,sampleRate:8000});
 assert.equal(result.result.matched,false);assert.equal(result.summary.reason,'silence');assert.equal(w.requests,1);
 assert.equal(w.calls[0].options.credentials,'omit');assert.equal(w.calls[0].options.redirect,'error');assert.equal(w.calls[0].url,'https://example.test/fingerprints/week.json');
});
test('hash, source, window, algorithm and posting shape fail admission even with coherent SHA',async()=>{
 const mutations=[i=>i.schemaVersion='other',i=>i.sourceSha256='c'.repeat(64),i=>i.trackSha256='c'.repeat(64),i=>i.pageId='other',i=>i.sourceStartSeconds=0,i=>i.durationSeconds=201,i=>i.algorithmVersion='other',i=>i.sampleRate=16000,i=>i.hopSize=512,i=>i.postings=null,i=>i.postings=[],i=>i.postings={'secret':[1]},i=>i.postings={'4294967296':[1]},i=>i.postings={'123':[.5]},i=>i.postings={'123':[-1]},i=>i.postings={'123':[100000]},i=>i.window=[0,200]];
 for(const mutate of mutations){const index=structuredClone(base);mutate(index);assert.equal((await worker(index).send('prepare')).error,'index_binding');}
 assert.equal((await worker(base,{hash:'0'.repeat(64)}).send('prepare')).error,'index_binding');
 assert.equal((await worker(base,{status:false}).send('prepare')).error,'index_unavailable');
 const failed=await worker(base,{fetchError:'private-network-label'}).send('prepare');assert.equal(failed.error,'match_failed');assert.ok(!JSON.stringify(failed).includes('private'));
});
test('match requires current admitted identity and errors discard prepared state and PCM',async()=>{
 for(const mutate of [m=>m.sourceSha256='c'.repeat(64),m=>m.trackSha256='c'.repeat(64),m=>m.indexSha256='c'.repeat(64),m=>m.sourceStartSeconds=21,m=>m.captureSeconds=15,m=>m.indexUrl='/fingerprints/new.json']){
  const w=worker();await w.send('prepare');const changed={...w.metadata};mutate(changed);const samples=new Float32Array([.8,.2]);
  assert.equal((await w.send('match',{metadata:changed,samples,sampleRate:8000})).error,'index_binding');assert.deepEqual([...samples],[0,0]);
  assert.equal((await w.send('match',{samples:new Float32Array(80),sampleRate:8000})).error,'index_binding');assert.equal(w.requests,1);
 }
 const cold=worker();assert.equal((await cold.send('match')).error,'index_binding');assert.equal(cold.requests,0);
});
test('preflight transport sends no PCM until ready and uses same worker for matching',async()=>{
 let instance;class Worker{constructor(){instance=this;this.messages=[];this.stops=0;}postMessage(data,transfer){this.messages.push({data,transfer});}terminate(){this.stops++;}}
 const signal=new AbortController(),metadata=worker().metadata;const pending=prepareInWorker(metadata,signal.signal,Worker);
 assert.equal(instance.messages.length,1);assert.equal(instance.messages[0].data.operation,'prepare');assert.ok(!('samples'in instance.messages[0].data));assert.deepEqual(instance.messages[0].transfer,[]);
 instance.onmessage({data:{requestId:99,ready:true}});assert.equal(instance.stops,0);
 instance.onmessage({data:{requestId:1,ready:true,timings:{indexMs:4}}});const prepared=await pending;
 const samples=new Float32Array(80);const matching=prepared.match({samples,sampleRate:8000});assert.equal(instance.messages[1].data.operation,'match');assert.equal(instance.messages[1].transfer[0],samples.buffer);
 instance.onmessage({data:{requestId:2,result:{matched:false}}});assert.equal((await matching).result.matched,false);
 prepared.close();signal.abort();assert.equal(instance.stops,1);await assert.rejects(prepared.match({samples,sampleRate:8000}),{name:'AbortError'});
});
test('cancel or invalid readiness terminates preflight; late replies never revive it',async()=>{
 for(const failure of ['abort','error','not_ready']){
  let instance;class Worker{constructor(){instance=this;this.stops=0;}postMessage(){}terminate(){this.stops++;}}
  const signal=new AbortController();const pending=prepareInWorker(worker().metadata,signal.signal,Worker);
  if(failure==='abort')signal.abort();else instance.onmessage({data:{requestId:1,...(failure==='error'?{error:'index_binding'}:{ready:false})}});
  await assert.rejects(pending);instance.onmessage({data:{requestId:1,ready:true}});assert.equal(instance.stops,1);
 }
});
