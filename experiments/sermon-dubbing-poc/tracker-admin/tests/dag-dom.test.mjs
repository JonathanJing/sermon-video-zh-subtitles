import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { JSDOM } from 'jsdom';
import { renderDag, refreshDagEstimate } from '../src/dag.js';
import { setUiLanguage } from '../src/i18n.js';
const fixture = JSON.parse(fs.readFileSync(new URL('../src/demo-dag.json',import.meta.url),'utf8'));
let run = 0;
function setup(dag=structuredClone(fixture)) {
  const dom=new JSDOM('<!doctype html><html><body><div id="dag-panel"></div></body></html>');
  globalThis.document=dom.window.document; setUiLanguage('zh');
  if (dag) dag.generatedAt = new Date().toISOString();
  const snapshot={pageId:`dom-demo-${++run}`,generatedAt:new Date().toISOString(),dag};renderDag(snapshot);return {dom,snapshot,host:document.getElementById('dag-panel')};
}
test('synthetic demo renders actual dependency branches and node selection without private links', () => {
  const {host}=setup();assert.match(host.textContent,/合成／模拟记录/);assert.match(host.textContent,/旧尝试结果未解决/);
  const observed=[...host.querySelectorAll('.dag-tabs button')].find((b)=>b.textContent.includes('已观测'));
  observed.click();assert.equal(host.querySelectorAll('.dag-node').length,4);assert.equal(host.querySelectorAll('.dag-rank').length,3);
  const last=host.querySelectorAll('.dag-node')[3];last.click();assert.match(document.activeElement.id,/dag-node-detail/);assert.match(host.querySelector('#dag-node-title').textContent,/n4/);
  host.querySelector('.dag-dependencies button').click();assert.match(host.querySelector('#dag-node-title').textContent,/n2|n3/);
  assert.equal(host.querySelectorAll('a[href]').length,0);
  assert.equal([...host.querySelectorAll('button')].every((b)=>b.type==='button'),true);
});
test('language rerender and repeated node/toggle clicks retain a valid accessible selection', () => {
  const {host,snapshot}=setup();setUiLanguage('en');renderDag(snapshot);assert.match(host.textContent,/Synthetic \/ mock/);
  for (let i=0;i<3;i++) { host.querySelectorAll('.dag-tabs button')[1].click();host.querySelector('.dag-node').click(); }
  assert.equal(host.querySelectorAll('.dag-node[aria-pressed="true"]').length,1);
  assert.equal(host.querySelector('#dag-node-detail').getAttribute('aria-labelledby'),'dag-node-title');
});
test('unavailable legacy graph preserves an explicit empty state and malformed graph fails closed', () => {
  const {host,snapshot}=setup(null);assert.match(host.textContent,/尚未接入执行 DAG/);assert.equal(host.querySelectorAll('button').length,0);
  snapshot.dag={...fixture,nodes:[{id:'n1',dependsOn:['n1']}]};renderDag(snapshot);assert.match(host.textContent,/尚未接入执行 DAG/);
});
test('running node with stale heartbeat is a warning, not active; nonrequired gates are explicit', () => {
  const dag=structuredClone(fixture);dag.evidenceMode='real';dag.progress.nodes[0]={...dag.progress.nodes[0],status:'running',unknownOutcome:false,heartbeatStatus:'stale',complete:false};
  const {host}=setup(dag);const running=host.querySelector('.dag-node');assert.match(running.textContent,/在线未知/);assert.equal(running.classList.contains('warn'),true);assert.equal(running.classList.contains('active'),false);
  assert.match(host.textContent,/非本节点必需门禁/);
});
test('aging a previously estimated snapshot withholds old DAG ETA without rerendering focused controls', () => {
  const dag=structuredClone(fixture);dag.evidenceMode='real';dag.progress.nodes.forEach((n)=>{n.evidenceMode='real';n.unknownOutcome=false;n.status='pending';});dag.eta={...dag.eta,status:'estimated',lowerSeconds:10,upperSeconds:30};
  const {host,snapshot}=setup(dag);assert.notEqual(host.querySelector('#dag-eta-value').textContent,'未知');const button=host.querySelector('.dag-tabs button');button.focus();
  snapshot.generatedAt='2026-01-01T00:00:00Z';refreshDagEstimate(snapshot);assert.equal(host.querySelector('#dag-eta-value').textContent,'未知');assert.equal(document.activeElement,button);
});
test('publisher silence ages fresh heartbeat display without erasing current keyboard focus', () => {
  const dag=structuredClone(fixture);dag.evidenceMode='real';dag.progress.nodes[0]={...dag.progress.nodes[0],status:'running',unknownOutcome:false,heartbeatStatus:'fresh',complete:false};
  const {host,snapshot}=setup(dag);const button=host.querySelector('.dag-node');button.focus();snapshot.generatedAt='2026-01-01T00:00:00Z';refreshDagEstimate(snapshot);
  assert.match(button.textContent,/快照已过期/);assert.equal(button.classList.contains('active'),false);assert.equal(document.activeElement,button);assert.match(host.querySelector('#dag-heartbeat').textContent,/当前未知/);
});
test('new snapshot retains expanded explanations and keyboard context without stale node identity', () => {
  const {host,snapshot}=setup();host.querySelector('.dag-estimate-detail').open=true;const node=host.querySelector('.dag-node');node.focus();
  renderDag({...snapshot,dag:structuredClone(snapshot.dag)});
  assert.equal(host.querySelector('.dag-estimate-detail').open,true);assert.equal(document.activeElement.getAttribute('aria-pressed'),'true');assert.equal(document.activeElement.closest('.dag-tabs')!==null,true);
});
test('a refreshed outer wrapper cannot revive an old nested DAG ETA or heartbeat', () => {
  const dag=structuredClone(fixture);dag.evidenceMode='real';dag.progress.nodes.forEach((n)=>{n.evidenceMode='real';n.unknownOutcome=false;n.status='pending';});dag.eta={...dag.eta,status:'estimated',lowerSeconds:10,upperSeconds:30};
  const {host,snapshot}=setup(dag);assert.notEqual(host.querySelector('#dag-eta-value').textContent,'未知');snapshot.dag.generatedAt='2026-01-01T00:00:00Z';refreshDagEstimate(snapshot);assert.equal(host.querySelector('#dag-eta-value').textContent,'未知');
});
