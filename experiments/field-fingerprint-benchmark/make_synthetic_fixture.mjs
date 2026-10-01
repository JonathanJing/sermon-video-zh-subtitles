/** Generate disposable PCM16 fixtures to test the harness, never acoustic qualification. */
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {fingerprint, CONFIG} from '../sermon-dubbing-poc/web/fingerprint-core.mjs';
const sha = b => createHash('sha256').update(b).digest('hex');
function signal(rate, seconds, variant) {
  return Float32Array.from({length: rate * seconds}, (_, i) => {
    const t = i / rate;
    return .18 * Math.sin(2 * Math.PI * ((300 + variant * 370) * t + 45 * t * t + 90 * Math.sin(1.7 * t)))
      + .12 * Math.sin(2 * Math.PI * ((1100 + variant * 230) * t - 29 * t * t + 65 * Math.sin(2.3 * t)))
      + .08 * Math.sin(2 * Math.PI * ((2100 - variant * 410) * t + 13 * t * t + 40 * Math.sin(.9 * t)));
  });
}
function wav(samples, rate) {
  const b = Buffer.alloc(44 + samples.length * 2);
  b.write('RIFF'); b.writeUInt32LE(b.length - 8, 4); b.write('WAVEfmt ', 8); b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(rate, 24); b.writeUInt32LE(rate * 2, 28);
  b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write('data', 36); b.writeUInt32LE(samples.length * 2, 40);
  for (let i = 0; i < samples.length; i++) b.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(samples[i] * 32768))), 44 + i * 2);
  return b;
}
export function createFixture(destination) {
  fs.mkdirSync(destination); // exclusive new directory, no replacement or nested implied paths
  const write = (name, bytes) => { fs.writeFileSync(path.join(destination, name), bytes, {flag:'wx',mode:0o600}); return {path:name,sha256:sha(bytes)}; };
  const manifest = {schemaVersion:'sermon-field-benchmark-manifest-v1',datasetId:'synthetic-harness-v1',datasetKind:'synthetic_only',
    splitPolicy:'source_family_recording_and_capture_session_disjoint',
    protocol:{frozenAt:'2026-10-01T00:00:00Z',localizationToleranceSeconds:.5,caseTimeoutSeconds:30},sources:[],sessions:[],cases:[]};
  for (const [split, variant] of [['dev',0],['holdout',1]]) {
    const rate = 8000, source = signal(rate, 40, variant), bytes = wav(source, rate);
    const recording = write(`${split}-source.wav`, bytes);
    // Index the actual quantized source bytes, with a nonzero source origin.
    const quantized = Float32Array.from({length:source.length}, (_,i) => bytes.readInt16LE(44+i*2)/32768);
    const features = fingerprint(quantized.subarray(10*rate), rate), postings = {};
    for (const [hash,t] of features.landmarks) (postings[hash] ??= []).push(t);
    const index = write(`${split}-index.json`, JSON.stringify({schemaVersion:'sermon-landmark-index-v1',algorithmVersion:CONFIG.algorithmVersion,
      sampleRate:CONFIG.sampleRate,hopSize:CONFIG.hopSize,fftSize:CONFIG.fftSize,sourceSha256:recording.sha256,
      sourceStartSeconds:10,sourceEndSeconds:40,durationSeconds:30,postings}));
    manifest.sources.push({id:`source-${split}`,familyId:`family-${split}`,split,recording,index});
    for (const kind of ['match','silence']) {
      // Vary silence file duration so exact capture hashes also remain split-disjoint.
      const capture = kind === 'match' ? source.subarray(20*rate,30*rate) : new Float32Array((10+variant)*rate);
      const captureAsset = write(`${split}-${kind}.wav`, wav(capture, rate));
      manifest.sessions.push({id:`session-${split}-${kind}`,captureSessionId:`capture-${split}-${kind}`,split,sourceRecordingId:`source-${split}`,recording:captureAsset,
        authorization:'synthetic_generated',capturePlatform:'synthetic',systemVersion:'not_recorded',deviceTier:'not_recorded',route:'not_recorded',condition:kind === 'silence' ? 'silence' : 'synthetic'});
      manifest.cases.push({id:`case-${split}-${kind}`,sessionId:`session-${split}-${kind}`,targetSourceRecordingId:`source-${split}`,
        captureStartSeconds:0,durationSeconds:10,expected:kind === 'match' ? {kind:'positive',sourceStartSeconds:20} : {kind:'negative'}});
    }
  }
  write('manifest.json', JSON.stringify(manifest,null,2)+'\n');
  return manifest;
}
if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  if (process.argv.length !== 3 || process.argv[2] === '--help') {
    console.log('Usage: node make_synthetic_fixture.mjs NEW_LOCAL_DIRECTORY\nSynthetic harness data only; keep it out of Git and do not upload.');
    if (process.argv[2] !== '--help') process.exitCode = 2;
  } else {
    try { const m = createFixture(process.argv[2]); console.log(JSON.stringify({datasetKind:m.datasetKind,caseCount:m.cases.length})); }
    catch { console.error('Synthetic fixture creation failed; requires a new local directory.'); process.exitCode = 1; }
  }
}
