import { fingerprint, matchFingerprint } from './fingerprint-core.mjs';
const same = (a, b) => a === b;
self.onmessage = async ({ data }) => {
  try {
    const { samples, sampleRate, metadata: m, requestId } = data;
    const url = new URL(m.indexUrl, self.location.href);
    if (url.origin !== self.location.origin || !url.pathname.startsWith('/fingerprints/') || url.search || url.hash) throw new Error('index_binding');
    const response = await fetch(url, { credentials: 'omit', cache: 'force-cache', redirect: 'error' });
    if (!response.ok) throw new Error('index_unavailable');
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength > 32 * 1024 * 1024) throw new Error('index_binding');
    const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(x => x.toString(16).padStart(2, '0')).join('');
    if (digest !== m.indexSha256) throw new Error('index_binding');
    const index = JSON.parse(new TextDecoder().decode(bytes));
    if (index.schemaVersion !== 'sermon-landmark-index-v1' || !same(index.pageId, m.pageId) || !same(index.sourceSha256, m.sourceSha256) || !same(index.trackSha256, m.trackSha256) || !same(index.algorithmVersion, m.algorithmVersion) || !same(index.sourceStartSeconds, m.sourceStartSeconds) || !same(index.sourceEndSeconds, m.sourceEndSeconds) || !same(index.durationSeconds, m.sourceEndSeconds - m.sourceStartSeconds)) throw new Error('index_binding');
    if (index.window && (Array.isArray(index.window) ? index.window[0] !== m.sourceStartSeconds || index.window[1] !== m.sourceEndSeconds : index.window.startSeconds !== m.sourceStartSeconds || index.window.endSeconds !== m.sourceEndSeconds)) throw new Error('index_binding');
    const query = fingerprint(samples, sampleRate);
    samples.fill(0);
    const result = matchFingerprint(query, index);
    // Only the content location and confidence cross back to UI; never persist PCM/features.
    self.postMessage({ requestId, result: { matched: result.matched === true, queryStartSeconds: result.queryStartSeconds, confidence: result.confidence, diagnostics: result.diagnostics }, durationSeconds: query.durationSeconds });
  } catch (error) { self.postMessage({ requestId: data.requestId, error: error.message || 'match_failed' }); }
};
