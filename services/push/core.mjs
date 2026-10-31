import { createHash, createHmac, randomBytes, timingSafeEqual } from 'node:crypto';

const LOCALES = new Set(['zh-Hans', 'en', 'ko', 'es', 'vi']);
const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const TOKEN = /^(?:[0-9a-f]{2}){16,256}$/i;
const SECRET = /^[A-Za-z0-9_-]{43}$/;
const ACTIVE_MS = 60 * 24 * 60 * 60 * 1000;
const RETAIN_MS = 365 * 24 * 60 * 60 * 1000;

export class PushApiError extends Error {
  constructor(status, code) { super(code); this.status = status; this.code = code; }
}

function digest(value) { return createHash('sha256').update(value).digest('hex'); }
function asDate(value) { return value?.toDate ? value.toDate() : value; }
function secretDigest(value) { return digest('tongxing-push-secret-v1\0' + value); }
function sameDigest(a, b) {
  if (typeof a !== 'string' || !/^[0-9a-f]{64}$/.test(a)) return false;
  return timingSafeEqual(Buffer.from(a, 'hex'), Buffer.from(b, 'hex'));
}
function exactKeys(value, keys) {
  return Object.keys(value).sort().join(',') === [...keys].sort().join(',');
}

export function parseSubscriptionRequest(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) throw new PushApiError(400, 'invalid_request');
  const action = body.action;
  const keys = action === 'upsert'
    ? ['schemaVersion', 'action', 'installationId', 'secret', 'seq', 'deviceToken', 'locale']
    : ['schemaVersion', 'action', 'installationId', 'secret', 'seq'];
  if (!['upsert', 'delete'].includes(action) || !exactKeys(body, keys) || body.schemaVersion !== 1 ||
      typeof body.installationId !== 'string' || !ID.test(body.installationId) ||
      typeof body.secret !== 'string' || !SECRET.test(body.secret) ||
      !Number.isSafeInteger(body.seq) || body.seq < 1 || body.seq > 2_147_483_647) {
    throw new PushApiError(400, 'invalid_request');
  }
  const rawSecret = Buffer.from(body.secret, 'base64url');
  if (rawSecret.length !== 32 || rawSecret.toString('base64url') !== body.secret) {
    throw new PushApiError(400, 'invalid_request');
  }
  if (action === 'upsert' && (typeof body.deviceToken !== 'string' || !TOKEN.test(body.deviceToken) ||
      !LOCALES.has(body.locale))) throw new PushApiError(400, 'invalid_request');
  return {
    action, installationId: body.installationId.toLowerCase(), secretHash: secretDigest(body.secret),
    seq: body.seq, locale: action === 'upsert' ? body.locale : null,
    deviceToken: action === 'upsert' ? body.deviceToken.toLowerCase() : null,
  };
}

export function requestDigest(request) {
  return digest(JSON.stringify([request.action, request.installationId, request.seq,
    request.locale, request.deviceToken]));
}

/** Store transaction adapter: get(path), set(path, value). All reads precede writes. */
export function createSubscriptionService({ store, now = () => new Date(), maxPerMinute = 600, maxPerDay = 10000 }) {
  return async function subscribe(body) {
    const request = parseSubscriptionRequest(body);
    const at = now();
    const requestHash = requestDigest(request);
    const minute = at.toISOString().slice(0, 16).replace(/[^0-9]/g, '');
    const day = at.toISOString().slice(0, 10).replace(/[^0-9]/g, '');
    return store.transaction(async (tx) => {
      const path = `pushSubscriptions/${request.installationId}`;
      const minutePath = `pushRateLimits/m${minute}`;
      const dayPath = `pushRateLimits/d${day}`;
      const [current, minuteCounter, dayCounter] = await Promise.all([
        tx.get(path), tx.get(minutePath), tx.get(dayPath),
      ]);
      if ((minuteCounter?.count ?? 0) >= maxPerMinute || (dayCounter?.count ?? 0) >= maxPerDay) {
        throw new PushApiError(429, 'temporarily_limited');
      }
      if (current && !sameDigest(current.secretHash, request.secretHash)) {
        throw new PushApiError(403, 'subscription_unavailable');
      }
      if (current && request.seq < current.seq) throw new PushApiError(409, 'stale_sequence');
      if (current && request.seq === current.seq && current.requestHash !== requestHash) {
        throw new PushApiError(409, 'sequence_conflict');
      }
      const replayed = !!current && request.seq === current.seq;
      const active = replayed ? current.active : request.action === 'upsert';
      const activeUntil = replayed ? asDate(current.activeUntil) : (active ? new Date(at.getTime() + ACTIVE_MS) : null);
      if (!replayed) {
        tx.set(path, {
          schemaVersion: 1, installationId: request.installationId, secretHash: request.secretHash,
          seq: request.seq, requestHash, active, locale: request.locale,
          deviceToken: request.deviceToken, tokenHash: request.deviceToken ? digest(request.deviceToken) : null,
          activeUntil, updatedAt: at, expiresAt: new Date(at.getTime() + RETAIN_MS),
        });
      }
      tx.set(minutePath, { count: (minuteCounter?.count ?? 0) + 1,
        expiresAt: new Date(at.getTime() + 2 * 24 * 60 * 60 * 1000) });
      tx.set(dayPath, { count: (dayCounter?.count ?? 0) + 1,
        expiresAt: new Date(at.getTime() + 3 * 24 * 60 * 60 * 1000) });
      return { ok: true, accepted: true, active, seq: request.seq,
        activeUntil: activeUntil ? activeUntil.toISOString() : null, replayed };
    });
  };
}

/** Ephemeral per-source guard. HMAC key and IP hashes are never persisted or logged. */
export function createSourceLimiter({ now = () => Date.now(), maxPerMinute = 60 } = {}) {
  const counters = new Map();
  const salt = randomBytes(32);
  return function check(source) {
    const minute = Math.floor(now() / 60000);
    const key = `${minute}:${createHmac('sha256', salt).update(source || '').digest('hex')}`;
    if (counters.size > 5000) counters.clear();
    const count = (counters.get(key) ?? 0) + 1;
    counters.set(key, count);
    if (count > maxPerMinute) throw new PushApiError(429, 'temporarily_limited');
  };
}
