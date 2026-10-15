import { sanitizeSnapshot } from '../sanitize.mjs';

/** Read-only browser state. Timestamps order snapshots, never prove worker liveness. */
export const SUPPORTED_SNAPSHOTS = ['sermon-public-tracker-snapshot-v1', 'sermon-public-tracker-snapshot-v2'];
export const STALE_AFTER_SECONDS = 120;
const timestamp = (value) => typeof value === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(value)
  && Number.isFinite(Date.parse(value)) ? Date.parse(value) : null;

export function snapshotFreshness(generatedAt, now = Date.now()) {
  const at = timestamp(generatedAt);
  if (at === null || !Number.isFinite(now)) return { status: 'unknown', ageSeconds: null };
  const seconds = Math.floor((now - at) / 1000);
  if (seconds < -30) return { status: 'clock_skew', ageSeconds: null };
  const ageSeconds = Math.max(0, seconds);
  return { status: ageSeconds > STALE_AFTER_SECONDS ? 'stale' : 'recent', ageSeconds };
}

export function reconcileSnapshots(previous, incoming, { fromCache = false } = {}) {
  const before = new Map(previous.map((item) => [item.pageId, item]));
  const seen = new Set();
  let rejected = 0;
  const runs = incoming.flatMap((supplied) => {
    let item = supplied;
    if (!item || !SUPPORTED_SNAPSHOTS.includes(item.schemaVersion) || typeof item.pageId !== 'string'
        || !Array.isArray(item.steps) || !Array.isArray(item.locales)
        || !item.sharedLayer1 || typeof item.sharedLayer1 !== 'object'
        || !item.progress || typeof item.progress !== 'object'
        || !item.source || typeof item.source !== 'object'
        || item.steps.some((row) => !row || typeof row.id !== 'string')
        || item.locales.some((row) => !row || typeof row.locale !== 'string')
        || seen.has(item.pageId)) { rejected += 1; return []; }
    seen.add(item.pageId);
    try { item = sanitizeSnapshot(item); } catch { rejected += 1; return []; }
    const originalOld = before.get(item.pageId);
    let old = originalOld;
    if (old) { try { old = sanitizeSnapshot(old); } catch { /* retained data is still caller-owned */ } }
    if (old) {
      const oldAt = timestamp(old.generatedAt), nextAt = timestamp(item.generatedAt);
      if (oldAt !== null && (nextAt === null || nextAt < oldAt
          || (nextAt === oldAt && JSON.stringify(item) !== JSON.stringify(old)))) {
        rejected += 1;
        return [originalOld];
      }
    }
    return [JSON.stringify(item) === JSON.stringify(supplied) ? supplied : item];
  });
  // Malformed entries have no trustworthy page ID. Keep missing previous pages
  // rather than treating a partial invalid update as deletion; a valid empty query may clear.
  if (rejected || fromCache) for (const old of previous) {
    if (!runs.some((item) => item.pageId === old.pageId)) runs.push(old);
  }
  return { runs, rejected };
}

export function legacyEtaState(report, freshness = 'recent') {
  if (report.total > 0 && report.complete === report.total) return 'complete';
  if (freshness !== 'recent') return 'stale';
  return report.earliestContinuousEta ? 'serial_reference' : 'unknown';
}
