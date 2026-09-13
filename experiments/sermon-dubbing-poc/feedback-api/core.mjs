import { createHash, createHmac, randomBytes } from 'node:crypto';
import { createUsageHandler } from './usage-core.mjs';

export const DAY = 86_400_000;
export const CATEGORIES = ['translation', 'pronunciation', 'fluency', 'voice', 'sync', 'volume', 'playback'];
const COMMON = ['schemaVersion', 'week', 'trackId', 'audioSha256', 'appVersion'];
const COUNTERS = ['plays', 'pauses', 'seeks', 'nudges', 'outlineViews', 'downloadClicks'];
const hash = (value) => createHash('sha256').update(value).digest('hex');
export class ApiError extends Error {
  constructor(status, code) { super(code); this.status = status; this.code = code; }
}
const assert = (valid, code = 'invalid_payload', status = 400) => { if (!valid) throw new ApiError(status, code); };
const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const finite = (value, max) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= max;
const integer = (value, max = 1_000_000) => Number.isSafeInteger(value) && value >= 0 && value <= max;
const keys = (value, allowed) => assert(object(value) && Object.keys(value).every((key) => allowed.includes(key)));
const seq = (value) => assert(integer(value) && value > 0);
const sourceKey = (body) => `${body.week}\0${body.trackId}\0${body.audioSha256}`;

export function prepareCatalog(catalog) {
  assert(catalog?.schemaVersion === 1 && Array.isArray(catalog.sources), 'invalid_catalog', 503);
  const map = new Map();
  for (const item of catalog.sources) {
    assert(/^\d{4}-\d{2}-\d{2}$/.test(item.week) && typeof item.trackId === 'string' && item.trackId.length <= 160 && /^[a-f0-9]{64}$/.test(item.audioSha256) && finite(item.durationSeconds, 21600) && item.durationSeconds > 0 && Array.isArray(item.cueIds) && Array.isArray(item.blockIds) && Array.isArray(item.cues), 'invalid_catalog', 503);
    const cues = new Map();
    for (const cue of item.cues) {
      assert(typeof cue.id === 'string' && item.cueIds.includes(cue.id) && !cues.has(cue.id) && finite(cue.start, item.durationSeconds + 1) && finite(cue.end, item.durationSeconds + 1) && cue.end > cue.start && (cue.blockId === null || item.blockIds.includes(cue.blockId)), 'invalid_catalog', 503);
      cues.set(cue.id, cue);
    }
    assert(cues.size === item.cueIds.length, 'invalid_catalog', 503);
    assert(!map.has(sourceKey(item)), 'duplicate_catalog_source', 503);
    map.set(sourceKey(item), { ...item, cues, cueIds: new Set(item.cueIds), blockIds: new Set(item.blockIds) });
  }
  return map;
}

/** A per-instance, bounded, ephemeral limiter. Only keyed digests live in memory. */
export function createIpLimiter({ now = Date.now, maxKeys = 4096 } = {}) {
  const salt = randomBytes(32), entries = new Map();
  return (address, route) => {
    const minute = Math.floor(now() / 60000);
    const key = createHmac('sha256', salt).update(`${address || 'unknown'}:${route}`).digest('hex');
    let entry = entries.get(key);
    if (!entry || entry.minute !== minute) entry = { minute, count: 0 };
    entry.count += 1;
    entries.delete(key); entries.set(key, entry);
    if (entries.size > maxKeys) entries.delete(entries.keys().next().value);
    assert(entry.count <= (route === '/api/session' ? 20 : 120), 'rate_limited', 429);
  };
}

function identity(body, catalog) {
  assert(body.schemaVersion === 1 && typeof body.appVersion === 'string' && /^[A-Za-z0-9._-]{1,100}$/.test(body.appVersion));
  const source = catalog.get(sourceKey(body));
  assert(source, 'unknown_source');
  return { source, stored: { schemaVersion: 1, week: source.week, trackId: source.trackId, audioSha256: source.audioSha256, appVersion: body.appVersion } };
}

function ranges(raw, duration) {
  assert(Array.isArray(raw) && raw.length <= 256);
  let end = -1, total = 0;
  for (const range of raw) {
    assert(Array.isArray(range) && range.length === 2 && finite(range[0], duration) && finite(range[1], duration) && range[1] > range[0] && range[0] > end);
    end = range[1]; total += range[1] - range[0];
  }
  return total;
}

function containsRanges(next, previous) {
  return previous.every((range) => {
    // Firestore cannot store an array directly inside another array. Wire tuples
    // are persisted as maps; accept legacy tuples only for adapter compatibility.
    const [start, end] = Array.isArray(range) ? range : [range.start, range.end];
    return next.some(([a, b]) => a <= start + .01 && b >= end - .01);
  });
}

function metricsDelta(metrics, oldValue, newValue, now) {
  const result = { schemaVersion: 1, ...metrics, updatedAt: new Date(now) };
  for (const name of new Set([...Object.keys(oldValue), ...Object.keys(newValue)])) {
    result[name] = Math.max(0, (metrics?.[name] || 0) - (oldValue[name] || 0) + (newValue[name] || 0));
  }
  return result;
}
function eventContribution(record) {
  if (!record) return {};
  const result = { sessions: 1, listenedSeconds: record.listenedSeconds, coveredSeconds: record.coveredSeconds, completedSessions: record.coveredSeconds / record.durationSeconds >= .9 ? 1 : 0 };
  for (const name of COUNTERS) result[name] = record[name];
  result.audioLoadErrors = record.errors.audio_load; result.audioPlayErrors = record.errors.audio_play;
  return result;
}

/** Store implements transaction(async tx => ...), with get/set/delete(path). */
export function createService({ store, catalog, origins, now = Date.now, randomToken = () => randomBytes(32).toString('base64url'), ipLimiter = createIpLimiter({ now }), limits = {} }) {
  const sources = prepareCatalog(catalog), allowedOrigins = new Set(origins);
  const usage = createUsageHandler({ catalog, ApiError });
  const budget = { mintsPerMinute: 100, mintsPerDay: 3000, sessionRequestsPerMinute: 30, ...limits };
  for (const value of Object.values(budget)) assert(integer(value, 100000) && value > 0, 'invalid_limits', 503);
  return async ({ method, path, origin, contentType, body, rawBytes, authorization, address }) => {
    assert(method === 'POST', 'method_not_allowed', 405);
    assert(allowedOrigins.has(origin), 'origin_not_allowed', 403);
    assert(/^application\/json(?:\s*;|$)/i.test(contentType || ''), 'json_required', 415);
    assert(Number.isInteger(rawBytes) && rawBytes <= 16384, 'payload_too_large', 413);
    assert(object(body));
    assert(['/api/session', '/api/feedback', '/api/events', '/api/usage'].includes(path), 'not_found', 404);
    ipLimiter(address, path);
    const { source, stored } = identity(body, sources);
    const timestamp = now();
    if (path === '/api/session') {
      keys(body, COMMON);
      const token = randomToken(), sessionId = hash(token), expiresAt = timestamp + DAY;
      await store.transaction(async (tx) => {
        const ratePath = `rateLimits/mint-${Math.floor(timestamp / 60000)}`;
        const dailyPath = `rateLimits/mint-day-${Math.floor(timestamp / DAY)}`;
        const rate = await tx.get(ratePath);
        const daily = await tx.get(dailyPath);
        assert((rate?.count || 0) < budget.mintsPerMinute && (daily?.count || 0) < budget.mintsPerDay, 'rate_limited', 429);
        tx.set(ratePath, { count: (rate?.count || 0) + 1, expiresAt: new Date(timestamp + DAY) });
        tx.set(dailyPath, { count: (daily?.count || 0) + 1, expiresAt: new Date(timestamp + 2 * DAY) });
        tx.set(`apiSessions/${sessionId}`, { ...stored, createdAtMs: timestamp, expiresAtMs: expiresAt, expiresAt: new Date(expiresAt), windowMinute: 0, windowCount: 0, eventSeq: 0, voteSeq: 0, issueCount: 0 });
      });
      return { token, sessionId, expiresAt: new Date(expiresAt).toISOString() };
    }
    assert(typeof authorization === 'string' && /^Bearer [A-Za-z0-9_-]{43}$/.test(authorization), 'invalid_session', 401);
    const sessionId = hash(authorization.slice(7)), sessionPath = `apiSessions/${sessionId}`;
    const metricPath = `weeklyMetrics/${hash(sourceKey(source))}`;
    if (path !== '/api/usage') seq(body.seq);
    return store.transaction(async (tx) => {
      const session = await tx.get(sessionPath);
      assert(session && session.expiresAtMs > timestamp && sourceKey(session) === sourceKey(source), 'invalid_session', 401);
      const minute = Math.floor(timestamp / 60000);
      const nextSession = { ...session, windowMinute: minute, windowCount: session.windowMinute === minute ? session.windowCount + 1 : 1 };
      assert(nextSession.windowCount <= budget.sessionRequestsPerMinute, 'rate_limited', 429);
      if (path === '/api/usage') return usage({ tx, body, session, nextSession, sessionPath, sessionId, stored, timestamp });
      const metric = await tx.get(metricPath) || { ...stored, durationSeconds: source.durationSeconds };
      if (path === '/api/feedback') {
        assert(body.kind === 'vote' || body.kind === 'issue');
        let id, payload, oldSeq;
        if (body.kind === 'vote') {
          keys(body, [...COMMON, 'kind', 'seq', 'vote']);
          assert(['up', 'down', null].includes(body.vote));
          id = `${sessionId}-vote`; oldSeq = session.voteSeq;
          payload = body.vote === null ? null : { ...stored, kind: 'vote', vote: body.vote };
        } else {
          keys(body, [...COMMON, 'kind', 'seq', 'feedbackId', 'action', 'categories', 'comment', 'context', 'positionSeconds', 'cueId', 'blockId']);
          assert(typeof body.feedbackId === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(body.feedbackId));
          assert(['upsert', 'delete'].includes(body.action));
          id = `${sessionId}-${body.feedbackId.toLowerCase()}`;
          if (body.action === 'upsert') {
            assert(Array.isArray(body.categories) && body.categories.length <= CATEGORIES.length && new Set(body.categories).size === body.categories.length && body.categories.every((item) => CATEGORIES.includes(item)));
            assert(typeof body.comment === 'string' && body.comment.length <= 1000 && !/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(body.comment));
            assert(['home', 'venue', 'unspecified'].includes(body.context));
            assert(body.positionSeconds === null || finite(body.positionSeconds, source.durationSeconds));
            assert(body.cueId === null || source.cueIds.has(body.cueId));
            assert(body.blockId === null || source.blockIds.has(body.blockId));
            if (body.cueId !== null) {
              const cue = source.cues.get(body.cueId);
              assert(body.positionSeconds !== null && body.positionSeconds >= cue.start - .5 && body.positionSeconds <= cue.end + .5 && body.blockId === cue.blockId, 'invalid_cue_position');
            } else assert(body.blockId === null, 'invalid_cue_position');
            assert(body.categories.length > 0 || body.comment.trim().length > 0, 'empty_issue');
            payload = { ...stored, kind: 'issue', categories: body.categories, comment: body.comment.trim(), context: body.context, positionSeconds: body.positionSeconds, cueId: body.cueId, blockId: body.blockId };
          } else payload = null;
        }
        const recordPath = `feedback/${id}`, sequencePath = `feedbackSequences/${id}`;
        const old = await tx.get(recordPath);
        const sequence = body.kind === 'issue' ? await tx.get(sequencePath) : null;
        oldSeq ??= sequence?.seq || 0;
        if (body.seq <= oldSeq) { tx.set(sessionPath, nextSession); return { ok: true, accepted: false, lastSeq: oldSeq }; }
        if (body.kind === 'issue' && !sequence) {
          assert(session.issueCount < 50, 'issue_limit', 429); nextSession.issueCount += 1;
        }
        const oldContribution = old ? (old.kind === 'vote' ? { [`votes_${old.vote}`]: 1 } : { issues: 1 }) : {};
        const newContribution = payload ? (payload.kind === 'vote' ? { [`votes_${payload.vote}`]: 1 } : { issues: 1 }) : {};
        for (const category of old?.categories || []) oldContribution[`issues_${category}`] = 1;
        for (const category of payload?.categories || []) newContribution[`issues_${category}`] = 1;
        if (payload) tx.set(recordPath, { ...payload, seq: body.seq, status: 'pending', createdAt: old?.createdAt || new Date(timestamp), updatedAt: new Date(timestamp), expiresAt: new Date(timestamp + 365 * DAY) });
        else tx.delete(recordPath);
        if (body.kind === 'vote') nextSession.voteSeq = body.seq;
        else tx.set(sequencePath, { seq: body.seq, expiresAt: new Date(session.expiresAtMs + DAY) });
        tx.set(metricPath, metricsDelta(metric, oldContribution, newContribution, timestamp));
      } else {
        keys(body, [...COMMON, 'action', 'seq', 'listenedSeconds', 'ranges', ...COUNTERS, 'errors']);
        assert(['upsert', 'delete'].includes(body.action));
        if (body.seq <= session.eventSeq) { tx.set(sessionPath, nextSession); return { ok: true, accepted: false, lastSeq: session.eventSeq }; }
        const recordPath = `listeningSessions/${sessionId}`, old = await tx.get(recordPath);
        let payload = null;
        if (body.action === 'upsert') {
          const maxElapsed = Math.max(0, (timestamp - session.createdAtMs) / 1000) + 10;
          assert(finite(body.listenedSeconds, Math.min(86400, maxElapsed)), 'invalid_listening_time');
          const coveredSeconds = ranges(body.ranges, source.durationSeconds);
          assert(coveredSeconds <= body.listenedSeconds * 3 + 1, 'invalid_coverage');
          for (const name of COUNTERS) assert(integer(body[name], 10000));
          keys(body.errors, ['audio_load', 'audio_play']);
          assert(integer(body.errors.audio_load, 1000) && integer(body.errors.audio_play, 1000));
          if (old) {
            assert(body.listenedSeconds >= old.listenedSeconds && containsRanges(body.ranges, old.ranges), 'non_monotonic_summary');
            for (const name of COUNTERS) assert(body[name] >= old[name], 'non_monotonic_summary');
            for (const name of ['audio_load', 'audio_play']) assert(body.errors[name] >= old.errors[name], 'non_monotonic_summary');
          }
          payload = { ...stored, seq: body.seq, listenedSeconds: body.listenedSeconds, ranges: body.ranges.map(([start, end]) => ({ start, end })), coveredSeconds, durationSeconds: source.durationSeconds, errors: body.errors, ...Object.fromEntries(COUNTERS.map((name) => [name, body[name]])), createdAt: old?.createdAt || new Date(timestamp), updatedAt: new Date(timestamp), expiresAt: new Date(timestamp + 30 * DAY) };
          tx.set(recordPath, payload);
        } else tx.delete(recordPath);
        nextSession.eventSeq = body.seq;
        tx.set(metricPath, metricsDelta(metric, eventContribution(old), eventContribution(payload), timestamp));
      }
      tx.set(sessionPath, nextSession);
      return { ok: true, accepted: true };
    });
  };
}
