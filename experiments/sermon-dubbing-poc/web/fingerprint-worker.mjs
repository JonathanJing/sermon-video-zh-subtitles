import { CONFIG, fingerprint, matchFingerprint } from './fingerprint-core.mjs';
import { captureQuality, summarizeMatch } from './fingerprint-diagnostics.mjs';

let prepared = null;
const identity = m => JSON.stringify([m.schemaVersion, m.pageId, m.sourceSha256, m.trackSha256,
  m.algorithmVersion, m.indexSha256, m.indexUrl, m.sourceStartSeconds, m.sourceEndSeconds, m.captureSeconds]);
const bindingError = () => { throw new Error('index_binding'); };
const MAX_INDEX_BYTES = 32 * 1024 * 1024;
const INDEX_CACHE = 'tongxing-verified-current-index-v1';

// A streamed size ceiling applies before JSON decoding or persistence. The
// browser may retain HTTP buffers, so this is not a measured peak-memory claim.
async function indexBytes(response) {
  const declared = Number(response.headers?.get?.('content-length'));
  if (Number.isFinite(declared) && declared > MAX_INDEX_BYTES) {
    await response.body?.cancel?.().catch(() => {});
    bindingError();
  }
  if (!response.body?.getReader) {
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength > MAX_INDEX_BYTES) bindingError();
    return bytes;
  }
  const reader = response.body.getReader(), chunks = [];
  let length = 0;
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      if (!(value instanceof Uint8Array) || value.byteLength > MAX_INDEX_BYTES - length) bindingError();
      length += value.byteLength;
      chunks.push(value);
    }
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return bytes.buffer;
  } catch (error) {
    try { await reader.cancel(); } catch { }
    throw error;
  } finally { reader.releaseLock(); }
}

async function validatedIndex(bytes, m) {
  const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(x => x.toString(16).padStart(2, '0')).join('');
  if (digest !== m.indexSha256) bindingError();
  const index = JSON.parse(new TextDecoder().decode(bytes));
  if (index.schemaVersion !== 'sermon-landmark-index-v1' || index.pageId !== m.pageId
    || index.sourceSha256 !== m.sourceSha256 || index.trackSha256 !== m.trackSha256
    || index.algorithmVersion !== m.algorithmVersion || index.algorithmVersion !== CONFIG.algorithmVersion
    || index.sourceStartSeconds !== m.sourceStartSeconds || index.sourceEndSeconds !== m.sourceEndSeconds
    || index.durationSeconds !== m.sourceEndSeconds - m.sourceStartSeconds
    || !Number.isFinite(index.durationSeconds) || index.durationSeconds <= 0
    || index.sampleRate !== CONFIG.sampleRate || index.hopSize !== CONFIG.hopSize
    || !index.postings || typeof index.postings !== 'object' || Array.isArray(index.postings)) bindingError();
  if (index.window && (Array.isArray(index.window)
    ? index.window[0] !== m.sourceStartSeconds || index.window[1] !== m.sourceEndSeconds
    : index.window.startSeconds !== m.sourceStartSeconds || index.window.endSeconds !== m.sourceEndSeconds)) bindingError();
  const lastFrame = Math.ceil(index.durationSeconds * CONFIG.sampleRate / CONFIG.hopSize);
  for (const [hash, positions] of Object.entries(index.postings)) {
    if (!/^\d+$/.test(hash) || !Number.isSafeInteger(Number(hash)) || Number(hash) > 0xffffffff
      || !Array.isArray(positions) || positions.some(pos => !Number.isInteger(pos) || pos < 0 || pos > lastFrame)) bindingError();
  }
  return index;
}

async function prepareIndex(m) {
  const binding = identity(m);
  if (prepared?.binding === binding) return prepared;
  prepared = null;
  const started = performance.now();
  const url = new URL(m.indexUrl, self.location.href);
  if (url.origin !== self.location.origin || !url.pathname.startsWith('/fingerprints/') || url.search || url.hash
      || !/^[a-f0-9]{64}$/.test(m.indexSha256)) bindingError();
  // One fixed cache entry bounds persistent bytes even across simultaneous
  // Workers. Only the last prepared public index is retained, never PCM,
  // microphone features, device labels or diagnostic payloads.
  const key = new URL('/__tongxing_index_cache_v1/current', self.location.origin).href;
  let cache = null, index = null;
  try { cache = await globalThis.caches?.open(INDEX_CACHE); } catch { }
  if (cache) {
    try {
      const cached = await cache.match(key);
      if (cached?.headers.get('X-Tongxing-Index-Sha256') === m.indexSha256) {
        index = await validatedIndex(await indexBytes(cached), m);
      }
    } catch {
      // Corrupt bytes or stale metadata never grant readiness. Online recovery
      // still has to pass the exact same SHA/schema/source/track/window checks.
      try { await cache.delete(key); } catch { }
    }
  }
  if (!index) {
    const response = await fetch(url, { credentials: 'omit', cache: 'force-cache', redirect: 'error' });
    if (!response.ok) throw new Error('index_unavailable');
    const bytes = await indexBytes(response);
    index = await validatedIndex(bytes, m);
    if (cache) {
      try {
        await cache.put(key, new Response(bytes, {headers: {
          'Content-Type': 'application/json', 'X-Tongxing-Index-Sha256': m.indexSha256,
        }}));
      } catch { /* Quota/private-mode errors leave this verified session usable. */ }
    }
  }
  prepared = { binding, index, indexMs: performance.now() - started };
  return prepared;
}

self.onmessage = async ({ data }) => {
  const timings = {};
  try {
    const { samples, sampleRate, metadata: m, requestId, operation } = data;
    const cached = operation === 'match' ? prepared : await prepareIndex(m);
    if (!cached || cached.binding !== identity(m)) bindingError();
    timings.indexMs = cached.indexMs;
    if (operation === 'prepare') {
      self.postMessage({ requestId, ready: true, timings });
      return;
    }
    if (operation !== undefined && operation !== 'match') bindingError();
    const featureStart = performance.now();
    const query = fingerprint(samples, sampleRate);
    const quality = captureQuality(samples, query.rms);
    samples.fill(0);
    timings.featureMs = performance.now() - featureStart;
    const matchStart = performance.now();
    const result = matchFingerprint(query, cached.index);
    timings.matchMs = performance.now() - matchStart;
    self.postMessage({ requestId, result: { matched: result.matched === true, queryStartSeconds: result.queryStartSeconds, confidence: result.confidence, diagnostics: result.diagnostics }, durationSeconds: query.durationSeconds, summary: summarizeMatch(query, result, quality), timings });
  } catch (error) {
    prepared = null;
    self.postMessage({ requestId: data.requestId, error: ['index_binding', 'index_unavailable'].includes(error.message) ? error.message : 'match_failed' });
  } finally { if (data.samples instanceof Float32Array) data.samples.fill(0); }
};
