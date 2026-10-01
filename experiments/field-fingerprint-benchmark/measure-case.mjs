/** Local-only worker. Reads bounded, hash-bound inputs; never returns audio or landmarks. */
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {performance} from 'node:perf_hooks';
import {fingerprint, matchFingerprint, CONFIG} from '../sermon-dubbing-poc/web/fingerprint-core.mjs';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
class CaseError extends Error {}
const fail = code => { throw new CaseError(code); };
function asset(root, spec, limit) {
  let file;
  try { file = fs.realpathSync(path.resolve(root, spec.path)); } catch { fail('asset_unavailable'); }
  const relative = path.relative(root, file);
  if (relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) fail('asset_outside_root');
  let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
    const stat = fs.fstatSync(fd);
    if (!stat.isFile() || stat.size > limit) fail('asset_size_or_type');
    // A bounded read also protects against concurrent file growth after fstat.
    const bytes = Buffer.alloc(stat.size);
    let count = 0;
    while (count < bytes.length) {
      const read = fs.readSync(fd, bytes, count, bytes.length - count, null);
      if (!read) fail('asset_changed');
      count += read;
    }
    if (fs.readSync(fd, Buffer.alloc(1), 0, 1, null)) fail('asset_changed');
    if (sha(bytes) !== spec.sha256) fail('asset_hash_mismatch');
    return bytes;
  } catch (error) {
    if (error instanceof CaseError) throw error;
    fail('asset_unavailable');
  } finally { if (fd !== undefined) fs.closeSync(fd); }
}
function parseIndex(bytes, source) {
  let index;
  try { index = JSON.parse(bytes); } catch { fail('index_invalid'); }
  const finite = v => typeof v === 'number' && Number.isFinite(v);
  if (!index || index.schemaVersion !== 'sermon-landmark-index-v1' || index.algorithmVersion !== CONFIG.algorithmVersion ||
      index.sampleRate !== CONFIG.sampleRate || index.hopSize !== CONFIG.hopSize || index.fftSize !== CONFIG.fftSize ||
      index.sourceSha256 !== source.recording.sha256 ||
      !finite(index.sourceStartSeconds) || !finite(index.sourceEndSeconds) || !finite(index.durationSeconds) ||
      index.sourceStartSeconds < 0 || index.sourceEndSeconds > 7200 || index.durationSeconds <= 0 ||
      Math.abs(index.sourceEndSeconds - index.sourceStartSeconds - index.durationSeconds) > 1e-9 ||
      !index.postings || typeof index.postings !== 'object' || Array.isArray(index.postings)) fail('index_binding_invalid');
  for (const [key, positions] of Object.entries(index.postings)) {
    if (!/^(0|[1-9][0-9]*)$/.test(key) || Number(key) > 0x3fffff || !Array.isArray(positions) ||
        !positions.every(v => Number.isSafeInteger(v) && v >= 0 && v * CONFIG.hopSize / CONFIG.sampleRate <= index.durationSeconds)) fail('index_postings_invalid');
  }
  return index;
}
function windowSamples(bytes, item) {
  // Intentionally narrow: PCM16 mono RIFF/WAVE. No ffmpeg, codec downloads or implicit resampling.
  if (bytes.length < 44 || bytes.toString('ascii', 0, 4) !== 'RIFF' || bytes.toString('ascii', 8, 12) !== 'WAVE' ||
      bytes.readUInt32LE(4) + 8 !== bytes.length) fail('wav_invalid');
  let format, data;
  for (let p = 12; p + 8 <= bytes.length;) {
    const id = bytes.toString('ascii', p, p + 4), size = bytes.readUInt32LE(p + 4), end = p + 8 + size;
    if (end > bytes.length) fail('wav_invalid');
    if (id === 'fmt ') {
      if (format || size < 16) fail('wav_invalid');
      format = {encoding: bytes.readUInt16LE(p + 8), channels: bytes.readUInt16LE(p + 10),
        rate: bytes.readUInt32LE(p + 12), byteRate: bytes.readUInt32LE(p + 16),
        block: bytes.readUInt16LE(p + 20), bits: bytes.readUInt16LE(p + 22)};
    }
    if (id === 'data') { if (data) fail('wav_invalid'); data = bytes.subarray(p + 8, end); }
    p = end + (size % 2);
    if (p > bytes.length || (p < bytes.length && p + 8 > bytes.length)) fail('wav_invalid');
  }
  if (!format || !data || format.encoding !== 1 || format.channels !== 1 || format.bits !== 16 || format.block !== 2 ||
      format.rate < 4000 || format.rate > 192000 || format.byteRate !== format.rate * 2 || data.length % 2) fail('wav_unsupported');
  const startExact = item.captureStartSeconds * format.rate, countExact = item.durationSeconds * format.rate;
  const start = Math.round(startExact), count = Math.round(countExact);
  if (Math.abs(startExact - start) > 1e-6 || Math.abs(countExact - count) > 1e-6 || count < 1 || (start + count) * 2 > data.length) fail('capture_window_invalid');
  const samples = new Float32Array(count);
  for (let i = 0; i < count; i++) samples[i] = data.readInt16LE((start + i) * 2) / 32768;
  return {samples, rate: format.rate};
}
async function main() {
  let input = '';
  for await (const chunk of process.stdin) { input += chunk; if (input.length > 16384) fail('worker_input_invalid'); }
  const {root, source, querySource, session, item, algorithmSha256} = JSON.parse(input);
  const currentAlgorithmSha = sha(fs.readFileSync(new URL('../sermon-dubbing-poc/web/fingerprint-core.mjs', import.meta.url)));
  if (currentAlgorithmSha !== algorithmSha256) fail('implementation_changed');
  const localRoot = fs.realpathSync(root), started = performance.now();
  asset(localRoot, source.recording, 512 * 1024 * 1024);
  if (querySource.id !== source.id) asset(localRoot, querySource.recording, 512 * 1024 * 1024);
  const indexBytes = asset(localRoot, source.index, 32 * 1024 * 1024);
  const index = parseIndex(indexBytes, source);
  if (item.expected.kind === 'positive' && (item.expected.sourceStartSeconds < index.sourceStartSeconds ||
      item.expected.sourceStartSeconds + item.durationSeconds > index.sourceEndSeconds + 1e-9)) fail('ground_truth_outside_index');
  const capture = asset(localRoot, session.recording, 512 * 1024 * 1024);
  const {samples, rate} = windowSamples(capture, item), prepared = performance.now();
  let result;
  try { result = matchFingerprint(fingerprint(samples, rate), index); } finally { samples.fill(0); }
  const matched = performance.now();
  console.log(JSON.stringify({status: result.matched ? 'accepted' : 'rejected', reason: result.diagnostics.reason,
    predictedSourceStartSeconds: result.matched ? index.sourceStartSeconds + result.queryStartSeconds : null,
    algorithmSha256: currentAlgorithmSha, nodeVersion: process.version, inputSampleRate: rate,
    preparationMs: prepared - started, dspMs: matched - prepared}));
}
main().catch(error => {
  console.log(JSON.stringify({status:'failed',reason:error instanceof CaseError ? error.message : 'worker_failed'}));
});
