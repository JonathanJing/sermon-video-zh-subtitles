#!/usr/bin/env node
/**
 * FIELD-09 venue benchmark: replay local room recordings through the production
 * published-fingerprint matcher and report per-window gates, checkpoint locks and
 * negative false matches. Recordings, PCM and landmarks stay local; the report holds
 * only counts, offsets and gate diagnostics.
 *
 * Usage (manifest paths resolve against --data-root, default the repository root):
 *   node scripts/field_venue_fingerprint_benchmark.mjs <manifest.json> --out <dir> [--data-root <checkout>] [--variants base,cmn] [--neg-step 5]
 *
 * Query variants other than `base` are FIELD-10 experiments: they change only
 * query-side peak picking, keep the index, hash layout and every matcher threshold,
 * and are never production evidence.
 */
import {createHash} from 'node:crypto';
import {readFileSync, writeFileSync, mkdirSync, existsSync, realpathSync, statSync} from 'node:fs';
import {dirname, resolve, sep} from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {fingerprint, matchFingerprint, CONFIG} from '../packages/fingerprint/src/fingerprint-core.mjs';

let ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SR = CONFIG.sampleRate, N = CONFIG.fftSize, H = CONFIG.hopSize;
export const WINDOW_SECONDS = [7, 10, 12, 15];
export const CHECKPOINTS = [7, 10, 12, 15];
export const VARIANTS = Object.freeze({
  base: null,
  cmn: {cmn: true},
  gate30: {gatePct: .3},
  cmn_gate30: {cmn: true, gatePct: .3},
  cmn_gate50: {cmn: true, gatePct: .5},
});
const CHANNELS = new Set(['mix', 'left', 'right']);

// Mirrors the accept gates in fingerprint-core matchFingerprint; used only to label rejections.
export function failingGates(d) {
  const out = [];
  if (!(d?.votes >= 35)) out.push('votes');
  if (!(d?.distinctAnchors >= 12)) out.push('anchors');
  if (!(d?.coveredSeconds >= 4.5)) out.push('span');
  if (!(d?.peakRatio >= 1.8)) out.push('ratio');
  if (!(d?.matchFraction >= .055)) out.push('fraction');
  if (!Array.isArray(d?.subwindowAnchors) || d.subwindowAnchors.some(n => n < 3)) out.push('subwindow');
  return out;
}

function fft(re, im) {
  for (let i = 1, j = 0; i < N; i++) { let b = N >> 1; for (; j & b; b >>= 1) j ^= b; j ^= b; if (i < j) { [re[i], re[j]] = [re[j], re[i]]; } }
  for (let size = 2; size <= N; size <<= 1) { const a = -2 * Math.PI / size, wr = Math.cos(a), wi = Math.sin(a);
    for (let base = 0; base < N; base += size) { let ur = 1, ui = 0; for (let j = 0; j < size / 2; j++) {
      const k = base + j, l = k + size / 2, tr = ur * re[l] - ui * im[l], ti = ur * im[l] + ui * re[l];
      re[l] = re[k] - tr; im[l] = im[k] - ti; re[k] += tr; im[k] += ti;
      const nr = ur * wr - ui * wi; ui = ur * wi + ui * wr; ur = nr;
    } }
  }
}
const hash = (f1, f2, dt) => (f1 << 14) | (f2 << 6) | dt;

/**
 * Query-side copy of spectral-landmarks-v1 at 8 kHz input. With no options it must
 * equal fingerprint-core exactly (checked at start-up). `cmn` subtracts each bin's
 * median log power over the query before peak picking (stationary room noise);
 * `gatePct` drops peaks in the quietest fraction of frames.
 */
export function fingerprintVariant(x, {cmn = false, gatePct = 0} = {}) {
  if (!(x instanceof Float32Array)) throw new TypeError('Expected 8 kHz Float32Array');
  const frames = Math.max(0, Math.floor((x.length - N) / H) + 1);
  let energy = 0; for (const v of x) energy += v * v;
  const rms = Math.sqrt(energy / Math.max(1, x.length)), re = new Float64Array(N), im = new Float64Array(N);
  const win = Float64Array.from({length: N}, (_, i) => .5 - .5 * Math.cos(2 * Math.PI * i / (N - 1)));
  const logs = [], frameEnergy = new Float64Array(frames);
  for (let t = 0; t < frames; t++) {
    for (let i = 0; i < N; i++) { re[i] = x[t * H + i] * win[i]; im[i] = 0; } fft(re, im);
    const log = new Float64Array(N / 2); let e = 0;
    for (let b = 24; b < 440; b++) { const p = re[b] * re[b] + im[b] * im[b]; log[b] = Math.log(1e-16 + p); e += p; }
    logs.push(log); frameEnergy[t] = Math.log(1e-16 + e);
  }
  if (cmn && frames) for (let b = 24; b < 440; b++) {
    const col = logs.map(r => r[b]).sort((p, q) => p - q), med = col[Math.floor(col.length / 2)];
    for (const r of logs) r[b] -= med;
  }
  let floor = -Infinity;
  if (gatePct > 0 && frames) { const s = [...frameEnergy].sort((p, q) => p - q); floor = s[Math.floor(s.length * gatePct)]; }
  const candidates = [];
  for (let t = 0; t < frames; t++) {
    const log = logs[t]; let avg = 0; for (let b = 24; b < 440; b++) avg += log[b]; avg /= 416;
    const peaks = [];
    if (frameEnergy[t] >= floor) for (let b = 27; b < 436; b++) if (log[b] > log[b - 1] && log[b] >= log[b + 1] && log[b] > avg + 1.2) {
      let local = 0; for (let k = -10; k <= 10; k++) local += log[Math.max(24, Math.min(439, b + k))];
      peaks.push({t, b, score: log[b] - .65 * local / 21 - .35 * avg});
    }
    peaks.sort((p, q) => q.score - p.score); candidates.push(peaks.slice(0, 5));
  }
  const bySecond = new Map();
  for (let t = 0; t < frames; t++) for (const p of candidates[t]) {
    let strongest = true;
    for (let d = -3; d <= 3 && strongest; d++) if (t + d >= 0 && t + d < frames) for (const q of candidates[t + d]) if (q !== p && Math.abs(q.b - p.b) <= 3 && q.score > p.score) { strongest = false; break; }
    if (strongest) { const s = Math.floor(t * H / SR); if (!bySecond.has(s)) bySecond.set(s, []); bySecond.get(s).push(p); }
  }
  const peaks = []; for (const g of bySecond.values()) { g.sort((p, q) => q.score - p.score); peaks.push(...g.slice(0, 14)); }
  peaks.sort((p, q) => p.t - q.t || p.b - q.b);
  const landmarks = [];
  for (let i = 0; i < peaks.length; i++) { const p = peaks[i]; let count = 0; for (let j = i + 1; j < peaks.length; j++) {
    const q = peaks[j], dt = q.t - p.t; if (dt < 5) continue; if (dt > 44) break;
    landmarks.push([hash(Math.round(p.b / 2), Math.round(q.b / 2), dt), p.t]); if (++count >= 8) break;
  } }
  return {schemaVersion: 'sermon-fingerprint-query-v1', algorithmVersion: CONFIG.algorithmVersion, sampleRate: SR, hopSize: H, durationSeconds: x.length / SR, rms, peakCount: peaks.length, landmarks};
}

export function assertVariantParity(x) {
  const a = fingerprint(x, SR), b = fingerprintVariant(x);
  if (JSON.stringify(a.landmarks) !== JSON.stringify(b.landmarks) || a.peakCount !== b.peakCount) throw new Error('variant_parity_failed: benchmark copy drifted from fingerprint-core');
}

const query = (variant, x) => variant ? fingerprintVariant(x, variant) : fingerprint(x, SR);
const sha256 = p => createHash('sha256').update(readFileSync(p)).digest('hex');
const hashText = s => createHash('sha256').update(s).digest('hex');
const isServiceDate = value => {
  const parsed = typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) ? Date.parse(`${value}T00:00:00Z`) : NaN;
  return Number.isFinite(parsed) && new Date(parsed).toISOString().slice(0, 10) === value;
};
const at = p => {
  if (typeof p !== 'string' || !p || p.startsWith('/') || p.includes('\\') || p.split('/').includes('..') || /^[a-z]+:/i.test(p)) {
    throw new Error('invalid_input_path');
  }
  const file = realpathSync(resolve(ROOT, p));
  if (!file.startsWith(realpathSync(ROOT) + sep) || !statSync(file).isFile()) throw new Error('invalid_input_path');
  return file;
};

function verifyInput(entry, label) {
  if (typeof entry?.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(entry.sha256)) throw new Error(`invalid_input_hash: ${label}`);
  const actual = sha256(at(entry.path));
  if (actual !== entry.sha256) throw new Error(`hash_mismatch: ${label}`);
}

function decode(path, {stream = 'a:0', channel = 'mix', startSeconds, durationSeconds} = {}) {
  if (!CHANNELS.has(channel)) throw new Error('unsupported_channel');
  const pan = channel === 'mix' ? ['-ac', '1'] : ['-af', `pan=mono|c0=c${channel === 'left' ? 0 : 1}`];
  const args = ['-v', 'error'];
  if (startSeconds != null) args.push('-ss', String(startSeconds));
  args.push('-i', at(path));
  if (durationSeconds != null) args.push('-t', String(durationSeconds));
  args.push('-map', `0:${stream}`, ...pan, '-ar', String(SR), '-f', 'f32le', 'pipe:1');
  const r = spawnSync('ffmpeg', args, {maxBuffer: 1 << 30});
  if (r.status !== 0) throw new Error('decode_failed');
  return new Float32Array(r.stdout.buffer.slice(r.stdout.byteOffset, r.stdout.byteOffset + r.stdout.length));
}

export const nearestRank = (a, p) => {
  const s = a.filter(Number.isFinite).sort((x, y) => x - y);
  return s.length ? s[Math.ceil(p * s.length) - 1] : null;
};
const median = a => nearestRank(a, .5);
const round = (v, d = 3) => v == null ? null : +v.toFixed(d);

export function assertCompatibleIndex(index, label = 'index') {
  if (index?.schemaVersion !== 'sermon-landmark-index-v1' || index.algorithmVersion !== CONFIG.algorithmVersion
    || index.sampleRate !== SR || index.hopSize !== H || !Number.isFinite(index.durationSeconds) || index.durationSeconds <= 0
    || !index.postings || typeof index.postings !== 'object' || Array.isArray(index.postings)
    || Object.keys(index.postings).length === 0) {
    throw new Error(`incompatible_index: ${label}`);
  }
  const lastFrame = Math.ceil(index.durationSeconds * SR / H);
  for (const [hash, positions] of Object.entries(index.postings)) {
    if (!/^\d+$/.test(hash) || !Number.isSafeInteger(Number(hash)) || Number(hash) > 0xffffffff
      || !Array.isArray(positions) || positions.some(pos => !Number.isInteger(pos) || pos < 0 || pos > lastFrame)) {
      throw new Error(`incompatible_index: ${label} postings`);
    }
  }
}

export function scorePositive(x, index, truth, variant, {tolerance = .5, ref = null} = {}) {
  assertCompatibleIndex(index, 'positive');
  const windows = {};
  for (const L of WINDOW_SECONDS) {
    const rows = [];
    for (let s = 0; s + L <= x.length / SR + 1e-6; s += 1) {
      const m = matchFingerprint(query(variant, x.slice(s * SR, (s + L) * SR)), index), d = m.diagnostics;
      const err = m.matched ? m.queryStartSeconds - (truth + s) : null;
      const row = {startSeconds: s, matched: m.matched, correct: m.matched && Math.abs(err) <= tolerance, errorMs: err == null ? null : Math.round(err * 1000),
        reason: d.reason, failingGates: m.matched ? [] : failingGates(d), votes: d.votes ?? null, distinctAnchors: d.distinctAnchors ?? null,
        matchFraction: round(d.matchFraction), peakRatio: round(d.peakRatio, 2), subwindowAnchors: d.subwindowAnchors ?? null};
      if (ref) {
        const r = ref.samples.slice(Math.round((truth + s - ref.indexStartSeconds) * SR), Math.round((truth + s - ref.indexStartSeconds + L) * SR));
        const mr = matchFingerprint(fingerprint(r, SR), index);
        const refError = mr.matched ? mr.queryStartSeconds - (truth + s) : null;
        row.reference = {matched: mr.matched, correct: mr.matched && Math.abs(refError) <= tolerance,
          errorMs: refError == null ? null : Math.round(refError * 1000), matchFraction: round(mr.diagnostics.matchFraction)};
      }
      rows.push(row);
    }
    const gateCounts = {};
    for (const r of rows) for (const g of r.failingGates) gateCounts[g] = (gateCounts[g] || 0) + 1;
    windows[L] = {total: rows.length, correct: rows.filter(r => r.correct).length, wrong: rows.filter(r => r.matched && !r.correct).length,
      medianMatchFraction: round(median(rows.map(r => r.matchFraction ?? 0))),
      observedMedianMatchFraction: round(median(rows.map(r => r.matchFraction))),
      observedMatchFractionWindows: rows.filter(r => r.matchFraction != null).length,
      referenceCorrect: ref ? rows.filter(r => r.reference.correct).length : null,
      referenceWrong: ref ? rows.filter(r => r.reference.matched && !r.reference.correct).length : null,
      referenceMedianMatchFraction: ref ? round(median(rows.map(r => r.reference.matchFraction ?? 0))) : null,
      referenceObservedMatchFractionWindows: ref ? rows.filter(r => r.reference.matchFraction != null).length : null,
      fractionOnlyRejections: rows.filter(r => r.failingGates.length === 1 && r.failingGates[0] === 'fraction').length,
      gateCounts, rows};
  }
  const strategy = [];
  for (let s = 0; s + CHECKPOINTS.at(-1) <= x.length / SR + 1e-6; s += 1) {
    let lockSeconds = null, wrong = false;
    for (const L of CHECKPOINTS) { const r = windows[L].rows.find(v => v.startSeconds === s); if (r.matched) { if (r.correct) lockSeconds = L; else wrong = true; break; } }
    strategy.push({startSeconds: s, lockSeconds, wrong});
  }
  const errors = Object.values(windows).flatMap(w => w.rows).filter(r => r.matched).map(r => Math.abs(r.errorMs)).sort((p, q) => p - q);
  return {windows, checkpoint: {sessions: strategy.length, locked: strategy.filter(v => v.lockSeconds).length, wrong: strategy.filter(v => v.wrong).length,
    medianLockSeconds: median(strategy.map(v => v.lockSeconds ?? NaN)), sessionsByStart: strategy},
    absErrorMs: errors.length ? {p50: nearestRank(errors, .5), p95: nearestRank(errors, .95), max: errors.at(-1)} : null};
}

export function assertBenchmarkPlan(manifest, index, release) {
  if (!Array.isArray(manifest.recordings) || !manifest.recordings.length
    || manifest.recordings.some(r => !Array.isArray(r.channels) || !r.channels.length)
    || !Array.isArray(manifest.negatives?.referenceRanges) || !manifest.negatives.referenceRanges.length
    || manifest.negatives.referenceRanges.some(range => !Array.isArray(range) || range.length !== 2
      || !Number.isFinite(range[0]) || !Number.isFinite(range[1]) || range[0] < 0 || range[1] - range[0] < 10)
    || !Array.isArray(manifest.negatives.otherIndexes) || !manifest.negatives.otherIndexes.length) {
    throw new Error('empty_benchmark_plan');
  }
  if (manifest.recordings.some(r => r.channels.some(channel => !CHANNELS.has(channel)))) throw new Error('unsupported_channel');
  if (manifest.recordings.some(r => !Number.isFinite(r.truthIndexStartSeconds))) throw new Error('invalid_positive_truth');
  const source = manifest.sourceIdentity, window = source?.window;
  // Release packages bind a dated canonical page ID even when they do not repeat
  // the catalog's `date` field directly.
  const releaseDate = release?.serviceDate ?? release?.date ?? /^(\d{4}-\d{2}-\d{2})(?:-|$)/.exec(release?.pageId ?? '')?.[1];
  if (typeof source?.sourceId !== 'string' || !source.sourceId
    || typeof source.sourceUrl !== 'string' || !/^https:\/\/[^\s]+$/.test(source.sourceUrl)
    || source.sourceUrlHash !== hashText(source.sourceUrl)
    || !isServiceDate(source.serviceDate)
    || releaseDate !== source.serviceDate
    || !/^[a-f0-9]{64}$/.test(source.mediaSha256 ?? '')
    || !Number.isFinite(source.durationSeconds) || source.durationSeconds <= 0
    || !Number.isFinite(window?.startSeconds) || !Number.isFinite(window?.endSeconds)
    || window.endSeconds <= window.startSeconds
    || !/^[a-f0-9]{64}$/.test(window.approvalReceiptSha256 ?? '')
    || typeof manifest.index?.pageId !== 'string' || !manifest.index.pageId
    || release?.pageId !== manifest.index.pageId
    || release.targetLocale !== manifest.index.targetLocale
    || release?.sourceIdentity?.sourceId !== source.sourceId
    || release.sourceIdentity.sourceUrlHash !== source.sourceUrlHash
    || release.sourceIdentity.mediaSha256 !== source.mediaSha256
    || release.sourceIdentity.durationSeconds !== source.durationSeconds
    || release.sourceIdentity.window?.approvalReceiptSha256 !== window.approvalReceiptSha256
    || release.sourceIdentity.window?.startSeconds !== window.startSeconds
    || release.sourceIdentity.window?.endSeconds !== window.endSeconds
    || manifest.reference?.sha256 !== source.mediaSha256
    || index.pageId !== manifest.index.pageId || index.sourceSha256 !== source.mediaSha256
    || index.sourceStartSeconds !== window.startSeconds || index.sourceEndSeconds !== window.endSeconds
    || index.durationSeconds !== window.endSeconds - window.startSeconds) {
    throw new Error('source_identity_mismatch');
  }
  if (manifest.negatives.referenceRanges.some(([start, end]) => end > source.durationSeconds
    || (start < index.sourceEndSeconds && end > index.sourceStartSeconds))) {
    throw new Error('invalid_negative_range');
  }
}

export function assertIndependentTruth(manifest, index, truth) {
  if (truth?.schemaVersion !== 'field-venue-independent-truth-v1'
    || truth.methodVersion !== 'band-energy-global-v1+waveform-local-v1'
    || truth.sourceSha256 !== manifest.reference.sha256
    || !Array.isArray(truth.recordings)
    || truth.recordings.length !== manifest.recordings.length) throw new Error('independent_truth_mismatch');
  const byId = new Map(truth.recordings.map(r => [r.id, r]));
  if (byId.size !== manifest.recordings.length) throw new Error('independent_truth_mismatch');
  for (const recording of manifest.recordings) {
    const verified = byId.get(recording.id);
    if (!verified || verified.recordingSha256 !== recording.sha256
      || !Number.isFinite(verified.indexStartSeconds)
      || !Number.isFinite(verified.sourceStartSecondsAbsolute)
      || !Number.isFinite(verified.segmentStartMinSeconds)
      || !Number.isFinite(verified.segmentStartMaxSeconds)
      || !Number.isFinite(verified.bestScore) || !Number.isFinite(verified.runnerUpScore)
      || verified.bestScore <= verified.runnerUpScore
      || verified.segmentStartMinSeconds > verified.segmentStartMaxSeconds
      || verified.segmentStartMaxSeconds - verified.segmentStartMinSeconds > .1
      || verified.sourceStartSecondsAbsolute < verified.segmentStartMinSeconds - .1
      || verified.sourceStartSecondsAbsolute > verified.segmentStartMaxSeconds + .1
      || Math.abs(verified.sourceStartSecondsAbsolute - index.sourceStartSeconds - verified.indexStartSeconds) > .001
      || Math.abs(recording.truthIndexStartSeconds - verified.indexStartSeconds) > .1) {
      throw new Error('independent_truth_mismatch');
    }
  }
}

export function assertPositiveRecordingSpan(truthIndexStartSeconds, spanSeconds, indexDurationSeconds) {
  if (!Number.isFinite(truthIndexStartSeconds) || !Number.isFinite(spanSeconds) || spanSeconds <= 0
    || !Number.isFinite(indexDurationSeconds) || indexDurationSeconds <= 0
    || truthIndexStartSeconds < 0 || truthIndexStartSeconds + spanSeconds > indexDurationSeconds + 1e-6) {
    throw new Error('empty_benchmark_plan: positive recording outside index');
  }
}

export function scoreNegatives(segments, indexes, variant, step) {
  if (!Number.isFinite(step) || step <= 0) throw new Error('invalid_neg_step: expected a finite positive number');
  for (const [id, index] of indexes) assertCompatibleIndex(index, id);
  let windows = 0, matches = 0, maxTargetFraction = 0;
  const byIndex = {};
  for (const x of segments) for (let s = 0; s + 10 <= x.length / SR; s += step) {
    const q = query(variant, x.slice(s * SR, (s + 10) * SR));
    for (const [id, idx] of indexes) {
      const m = matchFingerprint(q, idx); windows++;
      if (id === 'target') maxTargetFraction = Math.max(maxTargetFraction, m.diagnostics.matchFraction ?? 0);
      if (m.matched) { matches++; byIndex[id] = (byIndex[id] || 0) + 1; }
    }
  }
  return {windows, matches, byIndex, maxTargetFraction: round(maxTargetFraction)};
}

function parseArgs(argv) {
  const a = {manifest: null, out: null, variants: Object.keys(VARIANTS), negStep: 5};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--out') a.out = argv[++i];
    else if (argv[i] === '--variants') a.variants = argv[++i].split(',');
    else if (argv[i] === '--neg-step') a.negStep = +argv[++i];
    else if (argv[i] === '--data-root') a.dataRoot = argv[++i];
    else a.manifest = argv[i];
  }
  if (!a.manifest || !a.out) throw new Error('usage: field_venue_fingerprint_benchmark.mjs <manifest.json> --out <dir> [--variants base,cmn] [--neg-step 5]');
  if (!Number.isFinite(a.negStep) || a.negStep <= 0) throw new Error('invalid_neg_step: expected a finite positive number');
  for (const v of a.variants) if (!Object.hasOwn(VARIANTS, v)) throw new Error(`unknown variant ${v}`);
  return a;
}

async function main() {
  const args = parseArgs(process.argv.slice(2)), started = Date.now();
  if (existsSync(resolve(args.out))) throw new Error('output_exists: choose a new run directory');
  if (!existsSync(dirname(resolve(args.out)))) throw new Error('output_parent_missing');
  if (args.dataRoot) ROOT = resolve(args.dataRoot);
  const manifestPath = resolve(args.manifest), manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  if (manifest.schemaVersion !== 'field-venue-fingerprint-benchmark-v2') throw new Error('unsupported manifest');
  if (!manifest.release?.path || !manifest.release?.sha256) throw new Error('source_identity_mismatch: release receipt required');
  verifyInput(manifest.index, 'index');
  verifyInput(manifest.release, 'release');
  verifyInput(manifest.truthEvidence, 'independent truth');
  for (const r of manifest.recordings) verifyInput(r, r.id);
  verifyInput(manifest.reference, 'reference');
  for (const o of manifest.negatives.otherIndexes) verifyInput(o, o.id);
  const index = JSON.parse(readFileSync(at(manifest.index.path), 'utf8'));
  const release = JSON.parse(readFileSync(at(manifest.release.path), 'utf8'));
  const truthEvidence = JSON.parse(readFileSync(at(manifest.truthEvidence.path), 'utf8'));
  const others = manifest.negatives.otherIndexes.map(o => [o.id, JSON.parse(readFileSync(at(o.path), 'utf8'))]);
  assertCompatibleIndex(index, 'target');
  for (const [id, other] of others) assertCompatibleIndex(other, id);
  assertBenchmarkPlan(manifest, index, release);
  assertIndependentTruth(manifest, index, truthEvidence);
  const W0 = index.sourceStartSeconds;

  const execution = {runnerSha256: sha256(fileURLToPath(import.meta.url)),
    matcherSha256: sha256(resolve(dirname(fileURLToPath(import.meta.url)), '../packages/fingerprint/src/fingerprint-core.mjs')),
    variants: args.variants, negativeWindowStepSeconds: args.negStep, roomWindowStepSeconds: 1,
    windowSeconds: WINDOW_SECONDS, checkpointSeconds: CHECKPOINTS, localizationToleranceSeconds: .5};
  const report = {schemaVersion: 'field-venue-fingerprint-report-v2', manifestSha256: sha256(manifestPath), benchmarkId: manifest.benchmarkId,
    execution,
    algorithmVersion: CONFIG.algorithmVersion, indexSha256: manifest.index.sha256, truthEvidenceSha256: manifest.truthEvidence.sha256, tolerancesSeconds: .5,
    evidenceScope: 'offline_replay_of_room_recordings', deviceAppAcceptance: 'not_run', venueAcceptance: 'not_run', promotionAllowed: false,
    variants: {}, recordings: {}};
  const positives = [];
  for (const r of manifest.recordings) for (const channel of r.channels) {
    const x = decode(r.path, {stream: r.stream, channel});
    if (x.length < CHECKPOINTS.at(-1) * SR) throw new Error('empty_benchmark_plan: positive recording too short');
    assertVariantParity(x.slice(0, 10 * SR));
    const span = x.length / SR;
    assertPositiveRecordingSpan(r.truthIndexStartSeconds, span, index.durationSeconds);
    const referenceLeadSeconds = Math.min(1, r.truthIndexStartSeconds), refStart = r.truthIndexStartSeconds + W0 - referenceLeadSeconds;
    const ref = {indexStartSeconds: refStart - W0, samples: decode(manifest.reference.path, {startSeconds: refStart, durationSeconds: span + referenceLeadSeconds})};
    positives.push({id: `${r.id}:${channel}`, x, truth: r.truthIndexStartSeconds, ref});
    report.recordings[`${r.id}:${channel}`] = {durationSeconds: round(span, 2), device: r.device, captureApp: r.captureApp, channel};
  }
  const negSegments = manifest.negatives.referenceRanges.map(([s, e]) => decode(manifest.reference.path, {startSeconds: s, durationSeconds: e - s}));
  if (negSegments.some(x => x.length < 10 * SR)) throw new Error('empty_benchmark_plan: negative segment too short');
  for (const name of args.variants) {
    const variant = VARIANTS[name], v = {positives: {}, negatives: {}};
    for (const p of positives) v.positives[p.id] = scorePositive(p.x, index, p.truth, variant, {ref: name === 'base' ? p.ref : null});
    v.negatives.cleanOutsideWindow = scoreNegatives(negSegments, [['target', index], ...others], variant, args.negStep);
    v.negatives.roomVsOtherSermons = scoreNegatives(positives.map(p => p.x), others, variant, 1);
    report.variants[name] = v;
    const line = Object.entries(v.positives).map(([id, s]) => `${id} L10 ${s.windows[10].correct}/${s.windows[10].total} L15 ${s.windows[15].correct}/${s.windows[15].total} ckpt ${s.checkpoint.locked}/${s.checkpoint.sessions}${s.checkpoint.wrong ? ` WRONG ${s.checkpoint.wrong}` : ''}`).join('; ');
    console.error(`${name}: ${line}; neg ${v.negatives.cleanOutsideWindow.matches}/${v.negatives.cleanOutsideWindow.windows} + ${v.negatives.roomVsOtherSermons.matches}/${v.negatives.roomVsOtherSermons.windows}`);
  }
  report.elapsedSeconds = Math.round((Date.now() - started) / 1000);
  mkdirSync(resolve(args.out), {mode: 0o700});
  writeFileSync(resolve(args.out, 'report.json'), JSON.stringify(report, null, 1) + '\n', {flag: 'wx', mode: 0o600});
  const base = report.variants.base;
  const anyWrong = Object.values(report.variants).some(v => Object.values(v.positives).some(s => s.checkpoint.wrong || Object.values(s.windows).some(w => w.wrong || w.referenceWrong))
    || v.negatives.cleanOutsideWindow.matches || v.negatives.roomVsOtherSermons.matches);
  writeFileSync(resolve(args.out, 'summary.json'), JSON.stringify({schemaVersion: 'field-venue-fingerprint-summary-v2', benchmarkId: manifest.benchmarkId,
    manifestSha256: report.manifestSha256, execution,
    status: anyWrong ? 'false_match_observed' : 'completed_no_false_match', evidenceScope: report.evidenceScope,
    deviceAppAcceptance: 'not_run', venueAcceptance: 'not_run', promotionAllowed: false,
    baseCheckpointLocks: base ? Object.fromEntries(Object.entries(base.positives).map(([id, s]) => [id, `${s.checkpoint.locked}/${s.checkpoint.sessions}`])) : null,
    elapsedSeconds: report.elapsedSeconds}, null, 1) + '\n', {flag: 'wx', mode: 0o600});
}

export function publicErrorMessage(error) {
  if (error && typeof error === 'object'
    && (typeof error.path === 'string' || typeof error.syscall === 'string' || /^E[A-Z0-9_]+$/.test(error.code ?? ''))) {
    return 'filesystem_error';
  }
  return typeof error?.message === 'string' && error.message ? error.message : 'benchmark_failed';
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) main().catch(e => { console.error(publicErrorMessage(e)); process.exit(1); });
