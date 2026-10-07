import test from 'node:test';
import assert from 'node:assert/strict';
import { snapshotFreshness, reconcileSnapshots, legacyEtaState } from '../src/snapshot-state.js';
const snapshot = (time, extra = {}) => ({ schemaVersion: 'sermon-public-tracker-snapshot-v2', pageId: 'run', target:'dev',readOnly:true,steps:[],locales:[],sharedLayer1:{},source:{},progress:{},generatedAt: time, ...extra });
const now = Date.parse('2026-10-02T14:00:00Z');
test('freshness separates old snapshots, missing times and future clock skew from liveness', () => {
  assert.deepEqual(snapshotFreshness('2026-10-02T13:59:00Z', now), { status: 'recent', ageSeconds: 60 });
  assert.equal(snapshotFreshness('2026-10-01T14:00:00Z', now).status, 'stale');
  for (const value of [null, '', '2026-10-02T14:00:00', 'broken']) assert.equal(snapshotFreshness(value, now).status, 'unknown');
  assert.equal(snapshotFreshness('2026-10-02T15:00:00Z', now).status, 'clock_skew');
});
test('reconnect cannot replace a newer snapshot with stale, untimed or conflicting state', () => {
  const current = snapshot('2026-10-02T14:00:00Z', {progress:{complete:1}});
  for (const stale of [snapshot('2026-10-02T13:00:00Z'), snapshot(null), snapshot(current.generatedAt)]) {
    const result = reconcileSnapshots([current], [stale]);
    assert.equal(result.runs[0], current); assert.equal(result.rejected, 1);
  }
  const next = snapshot('2026-10-02T14:01:00Z', {progress:{complete:0}});
  assert.equal(reconcileSnapshots([current], [next]).runs[0].progress.complete, 0); // restart/invalidation is legitimate
  assert.equal(reconcileSnapshots([current], [structuredClone(current)]).rejected, 0);
});
test('malformed and duplicate snapshots are bounded and do not blank last verified data', () => {
  const current = snapshot('2026-10-02T14:00:00Z');
  assert.deepEqual(reconcileSnapshots([current], [null]).runs, [current]);
  assert.equal(reconcileSnapshots([], [current, current]).runs.length, 1);
  assert.deepEqual(reconcileSnapshots([current], []).runs, []);
});
test('completed checkpoint ledger never invents a completion timestamp from a serial ETA', () => {
  const report = { complete:46, total:46, earliestContinuousEta:'2026-10-02T14:00:00Z' };
  assert.equal(legacyEtaState(report, 'stale'), 'complete');
  assert.equal(legacyEtaState({...report, complete:1}, 'stale'), 'stale');
  assert.equal(legacyEtaState({...report, complete:1}), 'serial_reference');
  assert.equal(legacyEtaState({complete:0,total:0}), 'unknown');
});
test('one malformed document does not erase another page in a multi-page reconnect', () => {
  const a=snapshot('2026-10-02T14:00:00Z',{pageId:'a'}), b=snapshot('2026-10-02T14:00:00Z',{pageId:'b'});
  assert.deepEqual(reconcileSnapshots([a,b],[a,null]).runs.map((r)=>r.pageId),['a','b']);
});
test('malformed render shape cannot replace a good snapshot with a newer timestamp', () => {
  const current=snapshot('2026-10-02T14:00:00Z');
  for (const bad of [{steps:null},{locales:null},{sharedLayer1:null},{steps:[null]},{locales:[null]}]) {
    const next=snapshot('2026-10-02T15:00:00Z',bad);assert.equal(reconcileSnapshots([current],[next]).runs[0],current);
  }
});
test('nested optional malformed fields are normalized before rendering a new snapshot', () => {
  const next=snapshot('2026-10-02T14:00:00Z',{progress:{blockedStepIds:{}},dag:{schemaVersion:'invalid'}});
  const result=reconcileSnapshots([], [next]);assert.deepEqual(result.runs[0].progress.blockedStepIds,[]);assert.equal(result.runs[0].dag,null);
});
test('incomplete or empty offline cache cannot erase last server-known pages during reconnect', () => {
  const a=snapshot('2026-10-02T14:00:00Z',{pageId:'a'}),b=snapshot('2026-10-02T14:00:00Z',{pageId:'b'});
  assert.deepEqual(reconcileSnapshots([a,b],[],{fromCache:true}).runs,[a,b]);
  assert.deepEqual(reconcileSnapshots([a,b],[a],{fromCache:true}).runs.map((n)=>n.pageId),['a','b']);
  assert.deepEqual(reconcileSnapshots([a,b],[],{fromCache:false}).runs,[]);
});
