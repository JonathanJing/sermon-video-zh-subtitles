import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createHash, webcrypto } from 'node:crypto';
import { CONFIG, fingerprint, matchFingerprint } from './fingerprint-core.mjs';
import { captureQuality, summarizeMatch } from './fingerprint-diagnostics.mjs';

const code = fs.readFileSync(new URL('./fingerprint-worker.mjs', import.meta.url), 'utf8').replace(/^import .*;\n/gm, '');
const base = {schemaVersion:'sermon-landmark-index-v1',algorithmVersion:CONFIG.algorithmVersion,pageId:'week',
  sourceSha256:'a'.repeat(64),trackSha256:'b'.repeat(64),sourceStartSeconds:20,sourceEndSeconds:220,
  durationSeconds:200,sampleRate:8000,hopSize:256,postings:{123:[1,20]}};
const encoded = index => new TextEncoder().encode(JSON.stringify(index));
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
function storage({unavailable=false,quota=false}={}) {
  const entries = new Map(), writes = [];
  return {entries,writes,async open(name) {
    assert.equal(name,'tongxing-verified-current-index-v1');
    if (unavailable) throw new Error('private-mode');
    return {async match(key) {return entries.get(key)?.clone();},
      async delete(key) {return entries.delete(key);},
      async put(key,response) {if(quota) throw new Error('quota'); entries.set(key,response.clone());writes.push(key);}};
  }};
}
function worker(cache, {index=base,offline=false,response,metadataChange=()=>{}}={}) {
  const bytes=encoded(index), replies=[];let requests=0;
  const metadata={schemaVersion:'sermon-audio-fingerprint-binding-v1',...index,indexSha256:digest(bytes),indexUrl:'/fingerprints/current.json',captureSeconds:10};
  delete metadata.postings; metadataChange(metadata);
  const scope={CONFIG,fingerprint,matchFingerprint,captureQuality,summarizeMatch,TextDecoder,Uint8Array,Float32Array,URL,
    Response,crypto:webcrypto,performance,caches:cache,
    self:{location:{href:'https://example.test/fingerprint-worker.mjs',origin:'https://example.test'},postMessage:value=>replies.push(value)},
    fetch:async()=>{requests++;if(offline)throw new Error('offline');return response||new Response(bytes);}};
  vm.runInNewContext(code,scope);
  return {metadata,get requests(){return requests;},async send(operation='prepare',extra={}) {
    await scope.self.onmessage({data:{operation,metadata,requestId:replies.length+1,...extra}});return replies.at(-1);
  }};
}

test('new worker fully admits cached public bytes while offline, without persisting captured PCM', async()=>{
  const cache=storage(), first=worker(cache);
  assert.equal((await first.send()).ready,true);assert.equal(first.requests,1);assert.equal(cache.entries.size,1);
  const second=worker(cache,{offline:true});assert.equal((await second.send()).ready,true);assert.equal(second.requests,0);
  const before=await [...cache.entries.values()][0].clone().text();
  const samples=new Float32Array(80000);const match=await second.send('match',{samples,sampleRate:8000});
  assert.equal(match.result.matched,false);assert.equal(second.requests,0);
  assert.equal(await [...cache.entries.values()][0].clone().text(),before);assert.equal(cache.writes.length,1);
  assert.deepEqual(JSON.parse(before),base);
});

test('corrupt cached bytes are discarded; network recovery is independently verified', async()=>{
  for (const offline of [true,false]) {
    const cache=storage();await worker(cache).send();const key=[...cache.entries.keys()][0];
    cache.entries.set(key,new Response('corrupt',{headers:{'X-Tongxing-Index-Sha256':digest(encoded(base))}}));
    const retry=worker(cache,{offline});const result=await retry.send();assert.equal(retry.requests,1);
    if(offline){assert.ok(result.error);assert.equal(cache.entries.size,0);}
    else{assert.equal(result.ready,true);assert.equal(cache.entries.size,1);}
  }
});

test('matching cache header does not bypass source, track, window or posting validation', async()=>{
  for (const mutate of [m=>m.sourceSha256='c'.repeat(64),m=>m.trackSha256='c'.repeat(64),m=>m.sourceStartSeconds=21]) {
    const cache=storage();await worker(cache).send();
    assert.equal((await worker(cache,{offline:true,metadataChange:mutate}).send()).error,'match_failed');
    assert.equal(cache.entries.size,0);
  }
  const invalid={...base,postings:{bad:[1]}};
  const cache=storage();const key='https://example.test/__tongxing_index_cache_v1/current';
  cache.entries.set(key,new Response(encoded(invalid),{headers:{'X-Tongxing-Index-Sha256':digest(encoded(invalid))}}));
  assert.equal((await worker(cache,{index:invalid}).send()).error,'index_binding');assert.equal(cache.entries.size,0);
});

test('a different index never reuses cached bytes and only replaces them after valid admission', async()=>{
  const cache=storage();await worker(cache).send();
  const other={...base,trackSha256:'c'.repeat(64)};
  assert.ok((await worker(cache,{index:other,offline:true}).send()).error);assert.equal(cache.entries.size,1);
  assert.equal((await worker(cache,{index:other}).send()).ready,true);assert.equal(cache.entries.size,1);
  assert.ok((await worker(cache,{offline:true}).send()).error);
  assert.equal((await worker(cache,{index:other,offline:true}).send()).ready,true);
});

test('storage unavailable or quota failure leaves valid current-session matching usable', async()=>{
  for(const cache of [undefined,storage({unavailable:true}),storage({quota:true})]) {
    const w=worker(cache);assert.equal((await w.send()).ready,true);
    assert.equal((await w.send('match',{samples:new Float32Array(80000),sampleRate:8000})).result.matched,false);
    assert.equal(w.requests,1);
  }
});

test('oversized declared or streamed download cancels before decoding and is never cached', async()=>{
  let cancelled=0,reads=0;
  const declared={ok:true,headers:new Headers({'content-length':String(32*1024*1024+1)}),body:{async cancel(){cancelled++;}},arrayBuffer(){assert.fail('read oversized response');}};
  const streamed={ok:true,body:{getReader(){return {async read(){reads++;return {done:false,value:new Uint8Array(reads===1?32*1024*1024:1)};},async cancel(){cancelled++;},releaseLock(){}};}}};
  for(const response of [declared,streamed]){
    const cache=storage();assert.equal((await worker(cache,{response}).send()).error,'index_binding');assert.equal(cache.entries.size,0);
  }
  assert.equal(cancelled,2);assert.equal(reads,2);
});

test('concurrent preparations retain at most one verified index, whichever write finishes last', async()=>{
  const cache=storage();const indexes=Array.from({length:8},(_,i)=>({...base,pageId:`page-${i}`}));
  const results=await Promise.all(indexes.map(index=>worker(cache,{index}).send()));
  assert.ok(results.every(result=>result.ready));assert.equal(cache.entries.size,1);
  const stored=JSON.parse(await [...cache.entries.values()][0].clone().text());
  assert.ok(indexes.some(index=>index.pageId===stored.pageId));
  assert.equal((await worker(cache,{index:stored,offline:true}).send()).ready,true);
});
