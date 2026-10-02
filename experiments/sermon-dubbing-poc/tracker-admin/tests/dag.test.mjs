import test from 'node:test';
import assert from 'node:assert/strict';
import { sanitizeDag } from '../src/dag-contract.js';
import { dagRanks } from '../src/dag.js';
import { sanitizeSnapshot } from '../sanitize.mjs';
import { semanticHash } from '../publish.mjs';
const node = (id, dependsOn = []) => ({id,dependsOn,status:'completed',code:'asr',executorType:'production_model',modelCodes:['qwen3-asr'],timing:{status:'measured',elapsedSeconds:10},io:{}});
const fixture = () => ({schemaVersion:'sermon-public-tracker-dag-v1',scope:'accounting_run',executionAuthority:'none',acceptance:'not_evaluated',evidenceMode:'synthetic',generatedAt:'2026-10-02T14:00:00Z',nodes:[node('n1'),node('n2',['n1']),node('n3',['n1']),node('n4',['n2','n3'])],quality:{status:'projected'},eta:{status:'unknown',reasonCodes:['no_comparable_history']}});
test('closed public DAG removes raw logs, paths, identifiers, URLs and nonallowlisted models', () => {
  const input = fixture(); input.rawLog='secret'; input.nodes[0].modelCodes.push('private-model'); input.nodes[0].path='/private';input.nodes[0].url='https://private.example';input.eta.reasonCodes.push('private error');
  const safe = sanitizeDag(input); const text=JSON.stringify(safe);
  for (const value of ['secret','private-model','/private','https://private.example','private error']) assert.equal(text.includes(value),false,value);
  assert.deepEqual(safe.nodes[0].modelCodes,['qwen3-asr']);assert.deepEqual(safe.eta.reasonCodes,['no_comparable_history','other']);
});
test('DAG handles parallel branches by dependency levels, not serial list position', () => {
  assert.deepEqual(dagRanks(sanitizeDag(fixture()).nodes).map((rank)=>rank.map((n)=>n.id)),[['n1'],['n2','n3'],['n4']]);
});
test('malformed cycles/duplicates/oversized graphs fail closed and missing dependencies remain explicit', () => {
  const cyclic=fixture();cyclic.nodes[0].dependsOn=['n4']; assert.equal(sanitizeDag(cyclic),null);
  const dup=fixture();dup.nodes.push(node('n1'));assert.equal(sanitizeDag(dup),null);
  const big=fixture();big.nodes=Array.from({length:257},(_,i)=>node(`n${i+1}`));assert.equal(sanitizeDag(big),null);
  const missing=fixture();missing.nodes[0].dependsOn=['n99']; assert.equal(sanitizeDag(missing).nodes[0].unresolvedDependencyCount,1);
});
test('missing durations never become zero; invalid ETA range remains unknown', () => {
  const input=fixture();input.nodes[0].timing={elapsedSeconds:null};input.eta={status:'estimated',lowerSeconds:30,upperSeconds:10};
  const result=sanitizeDag(input);assert.equal(result.nodes[0].timing.elapsedSeconds,null);assert.equal(result.eta.status,'unknown');
});
test('v2 publisher retains the closed DAG while legacy snapshots do not invent one', () => {
  const base={schemaVersion:'sermon-public-tracker-snapshot-v2',pageId:'demo',target:'dev',readOnly:true,source:{},progress:{},locales:[],steps:[],dag:fixture()};
  assert.equal(sanitizeSnapshot(base).dag.evidenceMode,'synthetic');
  assert.equal(sanitizeSnapshot({...base,schemaVersion:'sermon-public-tracker-snapshot-v1'}).dag,null);
});
test('timestamp-only regeneration does not fabricate progress or write every 15 seconds', () => {
  const a={generatedAt:'2026-10-02T14:00:00Z',dag:fixture()}; a.dag.freshness={status:'stale',sourceObservedAt:'2026-10-01T00:00:00Z',ageSeconds:100};
  const b=structuredClone(a);b.generatedAt='2026-10-02T15:00:00Z';b.dag.generatedAt=b.generatedAt;b.dag.freshness.ageSeconds=200;
  assert.equal(semanticHash(a),semanticHash(b));b.dag.nodes[0].status='failed';assert.notEqual(semanticHash(a),semanticHash(b));
});
test('public synthetic, mixed or unknown evidence cannot claim real approval or production ETA', () => {
  for (const mode of ['synthetic','mixed','unknown']) {
    const input=fixture();input.evidenceMode=mode;input.progress={complete:true,gateCompletionPercent:100,counts:{realHumanApproved:1,admitted:1,done:1,total:1},nodes:[{...node('p1'),evidenceMode:'real',evidence:{realHumanApproved:true,admitted:true}}]};input.eta={status:'complete',lowerSeconds:0,upperSeconds:0};
    const safe=sanitizeDag(input);assert.equal(safe.progress.complete,false);assert.equal(safe.progress.gateCompletionPercent,null);assert.equal(safe.progress.counts.done,0);assert.equal(safe.progress.nodes[0].evidence.realHumanApproved,false);assert.equal(safe.eta.status,'unknown');assert.equal(safe.eta.lowerSeconds,null);
  }
});
test('planned heartbeat remains explicit and actual observed node count survives display bounds', () => {
  const input=fixture();input.summary={observedNodeCount:300};input.quality.omittedNodeCount=296;input.progress={nodes:[{...node('p1'),status:'running',heartbeatStatus:'stale'}]};
  const safe=sanitizeDag(input);assert.equal(safe.progress.nodes[0].heartbeatStatus,'stale');assert.equal(safe.summary.observedNodeCount,300);assert.equal(safe.quality.omittedNodeCount,296);
});
test('reported complete phase never hides canonical incomplete gates or unknown prior attempts', async () => {
  const {nodeLabel} = await import('../src/dag.js');
  const input=fixture();input.evidenceMode='real';input.progress={nodes:[{...node('p1'),kind:'planned',status:'complete',evidenceMode:'real',complete:false,unknownOutcome:true}]};
  const n=sanitizeDag(input).progress.nodes[0];assert.equal(n.complete,false);assert.equal(n.unknownOutcome,true);assert.match(nodeLabel(n),/未解决/);
  assert.match(nodeLabel({...n,unknownOutcome:false}),/门禁未齐/);
  assert.match(nodeLabel({...n,status:'running',unknownOutcome:false,heartbeatStatus:'stale'}),/在线未知/);
});
test('timestamps cannot carry comments or arbitrary payloads and malformed optional log shape is safe', () => {
  const input=fixture();input.generatedAt='(secret) 2 Oct 2026 14:00:00Z';input.freshness={sourceObservedAt:input.generatedAt};input.logs={contractVersions:{}};
  const safe=sanitizeDag(input);assert.equal(safe.generatedAt,null);assert.equal(safe.freshness.sourceObservedAt,null);assert.deepEqual(safe.logs.contractVersions,[]);assert.equal(JSON.stringify(safe).includes('secret'),false);
});
test('numeric and complete ETA require a coherent nonempty bound plan, including every node mode', () => {
  for (const progress of [null,{nodes:[],status:'partial',complete:false}]) {
    const input=fixture();input.evidenceMode='real';input.progress=progress;input.eta={status:'complete',lowerSeconds:0,upperSeconds:0};assert.equal(sanitizeDag(input).eta.status,'unknown');
    input.eta={status:'estimated',lowerSeconds:5,upperSeconds:10};assert.equal(sanitizeDag(input).eta.status,'unknown');
  }
  const input=fixture();input.evidenceMode='real';input.progress={nodes:[{...node('p1'),evidenceMode:'synthetic',complete:true}],status:'consistent',complete:true,denominator:'1',counts:{total:1,done:1,realHumanApproved:1}};input.eta={status:'complete',lowerSeconds:0,upperSeconds:0};const safe=sanitizeDag(input);assert.equal(safe.progress.complete,false);assert.equal(safe.progress.counts.realHumanApproved,0);assert.equal(safe.eta.status,'unknown');
});
test('contradictory complete flags do not overrule missing required evidence', () => {
  const input=fixture();input.evidenceMode='real';input.progress={nodes:[{...node('p1'),status:'complete',evidenceMode:'real',complete:true,requiredEvidence:['executionSucceeded'],evidence:{executionSucceeded:false}}],status:'consistent',complete:true,gateCompletionPercent:100,denominator:'1',counts:{total:1,done:1}};input.eta={status:'complete',lowerSeconds:0,upperSeconds:0};
  const safe=sanitizeDag(input);assert.equal(safe.progress.complete,false);assert.equal(safe.progress.nodes[0].complete,false);assert.equal(safe.progress.gateCompletionPercent,null);assert.equal(safe.eta.status,'unknown');
});
