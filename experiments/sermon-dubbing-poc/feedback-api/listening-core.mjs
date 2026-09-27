import { createHash } from 'node:crypto';
import { usageClock } from './usage-core.mjs';

const DAY = 86400000;
export const INTERFACE_LOCALES = ['zh-Hans', 'en', 'ko', 'es', 'vi'];
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
const hash = (value) => createHash('sha256').update(value).digest('hex');
export const validListeningDay = (day) => typeof day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(day) && Number.isFinite(Date.parse(day)) && new Date(day).toISOString().slice(0, 10) === day;
const finite = (value, maximum) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= maximum;
const common = ['schemaVersion', 'week', 'trackId', 'audioSha256', 'appVersion', 'action', 'seq'];

/** Source identity and credential/rate checks are performed by the shared router. */
export function createListeningHandler({ ApiError, catalog, interfaceUsage = false }) {
  const prefix = interfaceUsage ? 'interfaceUsage' : 'listening';
  const contentLocales = new Map();
  for (const source of catalog.sources) {
    if (source.pageId && source.audioLocale) {
      if (!contentLocales.has(source.pageId)) contentLocales.set(source.pageId, new Set());
      contentLocales.get(source.pageId).add(source.audioLocale);
    }
  }
  const assert = (condition, code = 'invalid_listening_payload', status = 400) => { if (!condition) throw new ApiError(status, code); };
  const keys = (body, allowed) => assert(Object.keys(body).length === allowed.length && allowed.every((key) => Object.hasOwn(body, key)));
  return async ({ tx, body, source, stored, session, nextSession, sessionPath, sessionId, timestamp }) => {
    const recordPath = `${interfaceUsage ? 'interfaceUsageSessions30d' : 'languageListeningSessions30d'}/${sessionId}`;
    // Withdrawal is terminal and wins even when a buffered higher sequence is
    // already in flight. It needs no client identifier and never creates a row.
    if (body.action === 'delete') {
      keys(body, common);
      const lastSeq = Math.max(session[`${prefix}Seq`] || 0, body.seq);
      tx.delete(recordPath);
      tx.set(sessionPath, { ...nextSession, [`${prefix}Deleted`]: true, [`${prefix}Seq`]: lastSeq });
      return { ok: true, accepted: true, deleted: true, lastSeq };
    }
    keys(body, [...common, 'day', 'clientId', 'platform', 'interfaceLocale', ...(interfaceUsage ? [] : ['contentLocale', 'listenedSeconds', 'ranges'])]);
    assert(body.action === 'upsert');
    assert(!session[`${prefix}Deleted`], 'listening_withdrawn', 410);
    assert(validListeningDay(body.day));
    assert(['web', 'ios'].includes(body.platform));
    assert(INTERFACE_LOCALES.includes(body.interfaceLocale));
    if (!interfaceUsage) assert(INTERFACE_LOCALES.includes(body.contentLocale) && contentLocales.get(source.pageId)?.has(body.contentLocale), 'unknown_content_locale');
    assert(body.clientId === null || (typeof body.clientId === 'string' && UUID.test(body.clientId)));
    // Bind the entire credential to its mint day. Late retries after midnight
    // stay in the original day, while a new day requires a new credential.
    assert(body.day === usageClock(session.createdAtMs).day, 'listening_day_mismatch');
    const dailyClientKey = body.clientId === null ? null : hash(`${body.day}\0${body.platform}\0${body.clientId.toLowerCase()}`);
    if (session[`${prefix}Day`]) {
      assert(session[`${prefix}Day`] === body.day && session[`${prefix}Platform`] === body.platform && session[`${prefix}ClientKey`] === dailyClientKey && session[`${prefix}InterfaceLocale`] === body.interfaceLocale && (interfaceUsage || session.listeningContentLocale === body.contentLocale), 'listening_identity_changed', 409);
    }
    let coveredSeconds = 0;
    if (!interfaceUsage) {
      const maxElapsed = Math.max(0, (timestamp - session.createdAtMs) / 1000) + 10;
      assert(finite(body.listenedSeconds, Math.min(86400, maxElapsed)), 'invalid_listening_time');
      assert(Array.isArray(body.ranges) && body.ranges.length <= 256);
      let end = -1;
      for (const range of body.ranges) {
        assert(Array.isArray(range) && range.length === 2 && finite(range[0], source.durationSeconds) && finite(range[1], source.durationSeconds) && range[1] > range[0] && range[0] > end, 'invalid_listening_ranges');
        end = range[1]; coveredSeconds += range[1] - range[0];
      }
      assert(coveredSeconds <= body.listenedSeconds * 3 + 1, 'invalid_coverage');
    }
    const digest = hash(JSON.stringify({ day: body.day, platform: body.platform, dailyClientKey, interfaceLocale: body.interfaceLocale, contentLocale: body.contentLocale ?? null, listenedSeconds: body.listenedSeconds ?? null, ranges: body.ranges ?? null }));
    const lastSeq = session[`${prefix}Seq`] || 0;
    if (body.seq <= lastSeq) {
      assert(body.seq !== lastSeq || digest === session[`${prefix}Digest`], 'listening_sequence_conflict', 409);
      tx.set(sessionPath, nextSession);
      return { ok: true, accepted: false, lastSeq };
    }
    const old = await tx.get(recordPath);
    if (old && !interfaceUsage) {
      assert(body.listenedSeconds >= old.listenedSeconds && old.ranges.every(({ start, end: previousEnd }) => body.ranges.some(([a, b]) => a <= start + .01 && b >= previousEnd - .01)), 'non_monotonic_summary');
    }
    const qualified = body.listenedSeconds >= 30;
    const completed = coveredSeconds / source.durationSeconds >= .9;
    tx.set(recordPath, {
      ...stored, pageId: source.pageId ?? null, audioLocale: source.audioLocale ?? null,
      seq: body.seq, day: body.day, platform: body.platform, dailyClientKey, interfaceLocale: body.interfaceLocale,
      ...(interfaceUsage ? {} : {
        contentLocale: body.contentLocale, listenedSeconds: body.listenedSeconds,
        coveredSeconds, durationSeconds: source.durationSeconds,
        ranges: body.ranges.map(([start, end]) => ({ start, end })),
      }),
      createdAt: old?.createdAt || new Date(timestamp), updatedAt: new Date(timestamp), expiresAt: new Date(timestamp + 30 * DAY),
    });
    tx.set(sessionPath, { ...nextSession, [`${prefix}Seq`]: body.seq, [`${prefix}Digest`]: digest, [`${prefix}Day`]: body.day, [`${prefix}Platform`]: body.platform, [`${prefix}ClientKey`]: dailyClientKey, [`${prefix}InterfaceLocale`]: body.interfaceLocale, ...(interfaceUsage ? {} : { listeningContentLocale: body.contentLocale }) });
    return { ok: true, accepted: true, lastSeq: body.seq, ...(interfaceUsage ? {} : { qualified, completed }) };
  };
}
