import test from 'node:test';
import assert from 'node:assert/strict';
import {fingerprint} from './fingerprint-core.mjs';
import {assertVariantParity, failingGates, fingerprintVariant, scoreNegatives} from '../../../scripts/field_venue_fingerprint_benchmark.mjs';

function speechLike(seconds, seed = 7) {
  let s = seed; const rand = () => ((s = (s * 1103515245 + 12345) >>> 0) / 2 ** 32) - .5;
  const x = new Float32Array(seconds * 8000);
  for (let i = 0; i < x.length; i++) {
    const t = i / 8000, f = 300 + 900 * Math.abs(Math.sin(t * 1.7)) + 400 * Math.sin(t * 5.3);
    x[i] = .3 * Math.sin(2 * Math.PI * f * t) * (.5 + .5 * Math.sin(t * 9)) + .2 * Math.sin(2 * Math.PI * 2 * f * t + 1) + .02 * rand();
  }
  return x;
}

test('benchmark query copy equals fingerprint-core when no variant is selected', () => {
  const x = speechLike(10);
  assert.doesNotThrow(() => assertVariantParity(x));
  assert.deepEqual(fingerprintVariant(x).landmarks, fingerprint(x, 8000).landmarks);
});

test('room-noise variants change only query landmarks and stay deterministic', () => {
  const x = speechLike(10), hum = Float32Array.from(x, (v, i) => v + .2 * Math.sin(2 * Math.PI * 500 * i / 8000));
  const a = fingerprintVariant(hum, {cmn: true}), b = fingerprintVariant(hum, {cmn: true});
  assert.deepEqual(a.landmarks, b.landmarks);
  assert.notDeepEqual(a.landmarks, fingerprintVariant(hum).landmarks);
  assert.ok(fingerprintVariant(hum, {gatePct: .5}).landmarks.length <= fingerprintVariant(hum).landmarks.length);
});

test('gate labels mirror the published matcher thresholds', () => {
  const pass = {votes: 35, distinctAnchors: 12, coveredSeconds: 4.5, peakRatio: 1.8, matchFraction: .055, subwindowAnchors: [3, 3, 3]};
  assert.deepEqual(failingGates(pass), []);
  assert.deepEqual(failingGates({...pass, matchFraction: .054}), ['fraction']);
  assert.deepEqual(failingGates({...pass, votes: 34, subwindowAnchors: [3, 2, 3]}), ['votes', 'subwindow']);
  assert.deepEqual(failingGates({}), ['votes', 'anchors', 'span', 'ratio', 'fraction', 'subwindow']);
});

test('negative scoring counts every index comparison and reports no match for an empty index', () => {
  const index = {schemaVersion: 'sermon-landmark-index-v1', algorithmVersion: 'spectral-landmarks-v1', sampleRate: 8000, hopSize: 256, durationSeconds: 60, postings: {}};
  const r = scoreNegatives([speechLike(20)], [['target', index], ['other', index]], null, 5);
  assert.equal(r.windows, 6); assert.equal(r.matches, 0); assert.equal(r.maxTargetFraction, 0);
});
