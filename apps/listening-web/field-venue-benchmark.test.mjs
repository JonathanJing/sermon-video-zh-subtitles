import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fingerprint} from './fingerprint-core.mjs';
import {assertBenchmarkPlan, assertCompatibleIndex, assertIndependentTruth, assertPositiveRecordingSpan, assertVariantParity, failingGates, fingerprintVariant, nearestRank, scoreNegatives, scorePositive} from '../../scripts/field_venue_fingerprint_benchmark.mjs';

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

test('negative scoring counts every index comparison and reports no match for unrelated postings', () => {
  const index = {schemaVersion: 'sermon-landmark-index-v1', algorithmVersion: 'spectral-landmarks-v1', sampleRate: 8000, hopSize: 256, durationSeconds: 60, postings: {0: [0]}};
  const r = scoreNegatives([speechLike(20)], [['target', index], ['other', index]], null, 5);
  assert.equal(r.windows, 6); assert.equal(r.matches, 0); assert.equal(r.maxTargetFraction, 0);
});

test('benchmark rejects incompatible indexes before counting comparisons', () => {
  const index = {schemaVersion: 'sermon-landmark-index-v1', algorithmVersion: 'spectral-landmarks-v1', sampleRate: 8000, hopSize: 256, durationSeconds: 60, postings: {123: [1, 20]}};
  assert.doesNotThrow(() => assertCompatibleIndex(index));
  for (const broken of [{...index, sampleRate: 16000}, {...index, postings: {}}, {...index, postings: {bad: [1]}}, {...index, postings: {123: ['bad']}}]) {
    assert.throws(() => scoreNegatives([speechLike(10)], [['target', broken]], null, 1), /incompatible_index/);
  }
});

test('negative-window step must advance and be finite', () => {
  const index = {schemaVersion: 'sermon-landmark-index-v1', algorithmVersion: 'spectral-landmarks-v1', sampleRate: 8000, hopSize: 256, durationSeconds: 60, postings: {0: [0]}};
  for (const step of [0, -1, Infinity, NaN]) assert.throws(() => scoreNegatives([], [['target', index]], null, step), /invalid_neg_step/);
  const cli = new URL('../../scripts/field_venue_fingerprint_benchmark.mjs', import.meta.url);
  const r = spawnSync(process.execPath, [cli.pathname, 'missing.json', '--out', 'unused', '--neg-step', '0'], {encoding: 'utf8'});
  assert.equal(r.status, 1);
  assert.match(r.stderr, /invalid_neg_step/);
});

test('reference correctness uses the expected offset, not merely an accepted match', () => {
  const x = speechLike(20), features = fingerprint(x, 8000), postings = {};
  for (const [hash, frame] of features.landmarks) (postings[hash] ??= []).push(frame + 156);
  const index = {schemaVersion: 'sermon-landmark-index-v1', algorithmVersion: 'spectral-landmarks-v1', sampleRate: 8000, hopSize: 256, durationSeconds: 60, postings};
  const result = scorePositive(x, index, 0, null, {ref: {indexStartSeconds: 0, samples: x}});
  assert.ok(result.windows[10].rows.some(row => row.reference.matched && !row.reference.correct));
  assert.equal(result.windows[10].referenceCorrect, 0);
  assert.ok(result.windows[10].referenceWrong > 0);
  assert.ok(result.windows[10].wrong > 0);
  assert.ok(result.absErrorMs.max >= 4900);
});

test('benchmark plan rejects empty comparisons and mismatched published source identity', () => {
  const sourceUrl = 'https://example.org/sermon', sourceUrlHash = createHash('sha256').update(sourceUrl).digest('hex');
  const source = {sourceId: 'sermon-1', sourceUrl, sourceUrlHash, serviceDate: '2026-10-11', mediaSha256: 'a'.repeat(64), durationSeconds: 100,
    window: {startSeconds: 20, endSeconds: 80, approvalReceiptSha256: 'b'.repeat(64)}};
  const pageId = '2026-10-11-page-1';
  const manifest = {sourceIdentity: source, reference: {sha256: source.mediaSha256}, index: {pageId, targetLocale: 'zh-Hans'}, recordings: [{channels: ['mix'], truthIndexStartSeconds: 0}],
    negatives: {referenceRanges: [[0, 10]], otherIndexes: [{id: 'other'}]}};
  const index = {pageId, sourceSha256: source.mediaSha256, sourceStartSeconds: 20, sourceEndSeconds: 80, durationSeconds: 60};
  const release = {pageId, targetLocale: 'zh-Hans', sourceIdentity: {sourceId: source.sourceId, sourceUrlHash, mediaSha256: source.mediaSha256, durationSeconds: source.durationSeconds, window: source.window}};
  assert.doesNotThrow(() => assertBenchmarkPlan(manifest, index, release));
  assert.throws(() => assertBenchmarkPlan({...manifest, recordings: []}, index, release), /empty_benchmark_plan/);
  assert.throws(() => assertBenchmarkPlan({...manifest, negatives: {...manifest.negatives, referenceRanges: [[0, 9]]}}, index, release), /empty_benchmark_plan/);
  assert.throws(() => assertBenchmarkPlan({...manifest, negatives: {...manifest.negatives, referenceRanges: [[15, 25]]}}, index, release), /invalid_negative_range/);
  assert.throws(() => assertBenchmarkPlan({...manifest, negatives: {...manifest.negatives, referenceRanges: [[95, 105]]}}, index, release), /invalid_negative_range/);
  assert.throws(() => assertBenchmarkPlan({...manifest, recordings: [{channels: ['mono'], truthIndexStartSeconds: 0}]}, index, release), /unsupported_channel/);
  assert.throws(() => assertBenchmarkPlan(manifest, {...index, sourceStartSeconds: 11}, release), /source_identity_mismatch/);
  assert.throws(() => assertBenchmarkPlan({...manifest, sourceIdentity: {...source, serviceDate: undefined}}, index, release), /source_identity_mismatch/);
  assert.throws(() => assertBenchmarkPlan({...manifest, sourceIdentity: {...source, serviceDate: '2026-10-12'}}, index, release), /source_identity_mismatch/);
  assert.throws(() => assertBenchmarkPlan(manifest, index, {...release, pageId: '2026-10-12-page-1'}), /source_identity_mismatch/);
  assert.throws(() => assertBenchmarkPlan({...manifest, sourceIdentity: {...source, sourceUrl: 'https://example.org/other'}}, index, release), /source_identity_mismatch/);
  assert.throws(() => assertBenchmarkPlan(manifest, index, {...release, sourceIdentity: {...release.sourceIdentity, sourceId: 'other'}}), /source_identity_mismatch/);
});

test('positive recordings must stay inside the indexed source span', () => {
  assert.doesNotThrow(() => assertPositiveRecordingSpan(0, 60, 60));
  assert.throws(() => assertPositiveRecordingSpan(-1, 20, 60), /outside index/);
  assert.throws(() => assertPositiveRecordingSpan(50, 15, 60), /outside index/);
});

test('report quantiles use nearest rank on even counts', () => {
  assert.equal(nearestRank([4, 1, 3, 2], .5), 2);
  assert.equal(nearestRank([4, 1, 3, 2], .95), 4);
  assert.equal(nearestRank([], .5), null);
});

test('independent truth binds the source and recording before scoring', () => {
  const manifest = {reference: {sha256: 'a'.repeat(64)}, recordings: [{id: 'phone', sha256: 'b'.repeat(64), truthIndexStartSeconds: 12.3}]};
  const index = {sourceStartSeconds: 100};
  const truth = {schemaVersion: 'field-venue-independent-truth-v1', methodVersion: 'band-energy-global-v1+waveform-local-v1', sourceSha256: manifest.reference.sha256,
    recordings: [{id: 'phone', recordingSha256: 'b'.repeat(64), sourceStartSecondsAbsolute: 112.3, indexStartSeconds: 12.3,
      segmentStartMinSeconds: 112.29, segmentStartMaxSeconds: 112.31, bestScore: .9, runnerUpScore: .2}]};
  assert.doesNotThrow(() => assertIndependentTruth(manifest, index, truth));
  assert.throws(() => assertIndependentTruth({...manifest, recordings: [{...manifest.recordings[0], truthIndexStartSeconds: 13}]}, index, truth), /independent_truth_mismatch/);
  assert.throws(() => assertIndependentTruth(manifest, index, {...truth, sourceSha256: 'c'.repeat(64)}), /independent_truth_mismatch/);
  assert.throws(() => assertIndependentTruth(manifest, index, {...truth, recordings: [{...truth.recordings[0], segmentStartMinSeconds: 114.29, segmentStartMaxSeconds: 114.31}]}), /independent_truth_mismatch/);
});

test('variant selection rejects inherited property names', () => {
  const cli = new URL('../../scripts/field_venue_fingerprint_benchmark.mjs', import.meta.url);
  const r = spawnSync(process.execPath, [cli.pathname, 'missing.json', '--out', 'unused', '--variants', '__proto__'], {encoding: 'utf8'});
  assert.equal(r.status, 1);
  assert.match(r.stderr, /unknown variant __proto__/);
});

test('filesystem errors do not reveal private paths', () => {
  const cli = new URL('../../scripts/field_venue_fingerprint_benchmark.mjs', import.meta.url);
  const work = mkdtempSync(join(tmpdir(), 'field-benchmark-'));
  try {
    const privateManifest = join(work, 'private-user-recordings', 'manifest.json');
    const r = spawnSync(process.execPath, [cli.pathname, privateManifest, '--out', join(work, 'run')], {encoding: 'utf8'});
    assert.equal(r.status, 1);
    assert.equal(r.stderr.trim(), 'filesystem_error');
    assert.ok(!r.stderr.includes(privateManifest));
  } finally {
    rmSync(work, {recursive: true, force: true});
  }
});

test('independent truth requires a private output file', () => {
  const entrypoints = [
    new URL('../../scripts/field_venue_independent_truth.py', import.meta.url),
    new URL('../../experiments/field-fingerprint-benchmark/field_venue_independent_truth.py', import.meta.url),
  ];
  const results = entrypoints.map(cli => spawnSync('python3', [cli.pathname, 'manifest.json', '--data-root', '.'], {
    encoding: 'utf8', cwd: tmpdir(),
  }));
  for (const r of results) {
    assert.equal(r.status, 2);
    assert.match(r.stderr, /required: --out/);
    assert.equal(r.stdout, '');
  }
  assert.equal(results[0].stderr, results[1].stderr);
});

test('legacy independent truth imports resolve the adjacent implementation', () => {
  const repo = new URL('../../', import.meta.url).pathname;
  const implementation = new URL('../../experiments/field-fingerprint-benchmark/field_venue_independent_truth.py', import.meta.url).pathname;
  const script = `
import hashlib, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
with tempfile.TemporaryDirectory() as temporary:
    os.chdir(temporary)
    Path('field_venue_independent_truth.py').write_text('raise AssertionError("ambient shadow loaded")')
    from scripts import field_venue_independent_truth as legacy
    from scripts.field_venue_independent_truth import METHOD_VERSION, checked_file, decode
    assert METHOD_VERSION == 'band-energy-global-v1+waveform-local-v1'
    assert legacy.checked_file is checked_file and legacy.decode is decode
    assert Path(checked_file.__code__.co_filename).resolve() == Path(sys.argv[2]).resolve()
    marker = object()
    legacy.np = marker
    assert legacy.np is marker and legacy.global_peak.__globals__['np'] is marker
    legacy.decode = marker
    assert legacy.decode is marker and legacy.waveform_peak.__globals__['decode'] is marker
    legacy.decode = decode
    payload = Path('synthetic.bin')
    payload.write_bytes(b'synthetic-only')
    assert checked_file(Path(temporary).resolve(), {'path': payload.name, 'sha256': hashlib.sha256(payload.read_bytes()).hexdigest()}) == payload.resolve()
`;
  const result = spawnSync('python3', ['-c', script, repo, implementation], {encoding: 'utf8', cwd: tmpdir()});
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, '');
});
