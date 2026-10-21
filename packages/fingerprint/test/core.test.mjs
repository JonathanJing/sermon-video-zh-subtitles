import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {CONFIG, QUERY_PROFILES, fingerprint, fingerprintProfile, matchFingerprint} from '../src/fingerprint-core.mjs';

// Same shape of synthetic signal as the iOS golden generator: three
// frequency-modulated partials, rich enough for the matcher's anchor gates.
function signal(rate, variant = 0) {
  return Float32Array.from({length: rate * 10}, (_, i) => {
    const t = i / rate;
    return .18 * Math.sin(2 * Math.PI * ((300 + variant * 370) * t + 45 * t * t + 90 * Math.sin(1.7 * t)))
      + .12 * Math.sin(2 * Math.PI * ((1100 + variant * 230) * t - 29 * t * t + 65 * Math.sin(2.3 * t)))
      + .08 * Math.sin(2 * Math.PI * ((2100 - variant * 410) * t + 13 * t * t + 40 * Math.sin(.9 * t)));
  });
}

function indexOf(landmarks, shiftHops) {
  const postings = {};
  for (const [hash, time] of landmarks) (postings[hash] ??= []).push(time + shiftHops);
  for (const values of Object.values(postings)) values.sort((a, b) => a - b);
  return {schemaVersion: 'sermon-landmark-index-v1', algorithmVersion: CONFIG.algorithmVersion,
    sampleRate: CONFIG.sampleRate, hopSize: CONFIG.hopSize, durationSeconds: 90, postings};
}

test('frozen configuration and query profiles', () => {
  assert.equal(CONFIG.algorithmVersion, 'spectral-landmarks-v1');
  assert.deepEqual([CONFIG.sampleRate, CONFIG.fftSize, CONFIG.hopSize], [8000, 1024, 256]);
  assert.deepEqual([...QUERY_PROFILES], ['cmn-v1']);
  assert.ok(Object.isFrozen(CONFIG));
});

test('fingerprint is deterministic, matches itself at the shifted offset and rejects an unrelated signal', () => {
  const samples = signal(8000);
  const first = fingerprint(samples, 8000);
  const second = fingerprint(samples, 8000);
  assert.deepEqual(first.landmarks, second.landmarks);
  assert.ok(first.landmarks.length >= 80);
  const shiftHops = 625;  // 20 s at 8000 Hz / 256 hop
  const match = matchFingerprint(first, indexOf(first.landmarks, shiftHops));
  assert.equal(match.matched, true, JSON.stringify(match.diagnostics));
  assert.ok(Math.abs(match.queryStartSeconds - shiftHops * CONFIG.hopSize / CONFIG.sampleRate) < 0.1, String(match.queryStartSeconds));
  const unrelated = fingerprint(signal(8000, 1), 8000);
  assert.equal(matchFingerprint(first, indexOf(unrelated.landmarks, shiftHops)).matched, false);
  const profile = fingerprintProfile(samples, 8000, 'cmn-v1');
  assert.equal(profile.algorithmVersion, CONFIG.algorithmVersion);
});

test('the CLI imports the package copy of the algorithm, not an app copy', () => {
  const cli = readFileSync(new URL('../bin/build_fingerprint_index.mjs', import.meta.url), 'utf8');
  assert.match(cli, /from '\.\.\/src\/fingerprint-core\.mjs'/);
  assert.doesNotMatch(cli, /sermon-dubbing-poc|apps\//);
});
