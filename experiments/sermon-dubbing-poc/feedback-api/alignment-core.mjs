import { createHash } from 'node:crypto';
import { usageClock } from './usage-core.mjs';
import { INTERFACE_LOCALES, validListeningDay } from './listening-core.mjs';

const DAY = 86400000;
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
const hash = (value) => createHash('sha256').update(value).digest('hex');
const common = ['schemaVersion', 'week', 'trackId', 'audioSha256', 'appVersion', 'action', 'seq'];

// Terminal states of one "听声定位" press. `applied` is the only jump that reached playback.
export const ALIGNMENT_OUTCOMES = Object.freeze(['applied', 'matched', 'play_failed', 'play_blocked', 'no_match', 'expired',
  'timeout', 'cancelled', 'error', 'permission_denied', 'unavailable', 'unsupported']);
// Furthest step reached before the outcome: index prepared, microphone recording, matcher finished.
export const ALIGNMENT_STAGES = Object.freeze(['opened', 'index_ready', 'recording', 'matched_audio']);
export const ALIGNMENT_REASONS = Object.freeze(['matched', 'silence', 'insufficient_audio', 'no_consensus', 'ambiguous', 'low_confidence', 'incompatible_index', 'incompatible_query', 'unknown']);
export const ALIGNMENT_ERROR_CODES = Object.freeze('MIC_BUDGET MIC_START_TIMEOUT INPUT_INTERRUPTED AUDIO_INTERRUPTED MIC_ENDED PROCESSOR_ERROR INVALID_CAPTURE INDEX_MISMATCH INDEX_UNAVAILABLE MATCH_ERROR MIC_PERMISSION MIC_MISSING MIC_BUSY MIC_SETTINGS AUDIO_UNSUPPORTED WORKLET_LOAD AUDIO_START UNKNOWN'.split(' '));
export const ALIGNMENT_LEVELS = Object.freeze(['silent', 'very_low', 'low', 'moderate', 'high', 'unknown']);
// matchFraction bands around the frozen 0.055 accept gate (FIELD-07); near misses are 0.045-0.055.
export const ALIGNMENT_FRACTION_BANDS = Object.freeze(['below_0_03', '0_03_to_0_045', '0_045_to_0_055', 'at_least_0_055']);
export const ALIGNMENT_SHADOW_PROFILES = Object.freeze(['cmn-v1']);
export const ALIGNMENT_ATTEMPT_LIMIT = 40;
const ATTEMPT_KEYS = ['at', 'outcome', 'stage', 'reason', 'errorCode', 'level', 'fractionBand', 'captureSeconds', 'totalMs', 'shadow'];

/**
 * Cumulative per-credential list of alignment attempts. Only whitelisted enums,
 * whole seconds and 100 ms buckets are accepted: no PCM, landmarks, device route,
 * error text or playback position.
 */
export function createAlignmentUsageHandler({ ApiError, catalog }) {
  const contentLocales = new Map();
  for (const source of catalog.sources) {
    if (source.pageId && source.audioLocale) {
      if (!contentLocales.has(source.pageId)) contentLocales.set(source.pageId, new Set());
      contentLocales.get(source.pageId).add(source.audioLocale);
    }
  }
  const sets = Object.fromEntries(Object.entries({ outcome: ALIGNMENT_OUTCOMES, stage: ALIGNMENT_STAGES, reason: ALIGNMENT_REASONS,
    errorCode: ALIGNMENT_ERROR_CODES, level: ALIGNMENT_LEVELS, fractionBand: ALIGNMENT_FRACTION_BANDS }).map(([key, values]) => [key, new Set(values)]));
  const assert = (condition, code = 'invalid_alignment_payload', status = 400) => { if (!condition) throw new ApiError(status, code); };
  const keys = (value, allowed) => assert(value !== null && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === allowed.length && allowed.every((key) => Object.hasOwn(value, key)));
  const nullableEnum = (value, key) => assert(value === null || sets[key].has(value));
  function attempt(item, day, timestamp) {
    keys(item, ATTEMPT_KEYS);
    // Clients mint lazily, possibly long after an offline press; bound attempts
    // by the upload time and their own reporting day, not the credential's age.
    assert(Number.isSafeInteger(item.at) && item.at % 1000 === 0 && item.at >= timestamp - DAY && item.at <= timestamp + 300000
      && usageClock(item.at).day === day, 'invalid_alignment_time');
    assert(sets.outcome.has(item.outcome) && sets.stage.has(item.stage));
    for (const key of ['reason', 'errorCode', 'level', 'fractionBand']) nullableEnum(item[key], key);
    assert(item.captureSeconds === null || [7, 10, 12, 15].includes(item.captureSeconds));
    assert(item.totalMs === null || (Number.isSafeInteger(item.totalMs) && item.totalMs >= 0 && item.totalMs <= 600000 && item.totalMs % 100 === 0));
    if (item.shadow !== null) {
      keys(item.shadow, ['profile', 'matched', 'agrees']);
      assert(ALIGNMENT_SHADOW_PROFILES.includes(item.shadow.profile) && typeof item.shadow.matched === 'boolean' && [true, false, null].includes(item.shadow.agrees));
    }
    // Stage and outcome must describe one consistent path.
    if (['applied', 'matched', 'play_failed', 'play_blocked'].includes(item.outcome)) assert(item.stage === 'matched_audio' && item.reason === 'matched');
    if (item.outcome === 'no_match') assert(item.stage === 'matched_audio' && item.reason !== null && item.reason !== 'matched');
    if (item.stage !== 'matched_audio') assert(item.reason === null && item.fractionBand === null && item.shadow === null);
    return Object.fromEntries(ATTEMPT_KEYS.map((key) => [key, key === 'shadow' && item.shadow ? { profile: item.shadow.profile, matched: item.shadow.matched, agrees: item.shadow.agrees } : item[key]]));
  }
  return async ({ tx, body, source, stored, session, nextSession, sessionPath, sessionId, timestamp }) => {
    const recordPath = `alignmentUsageSessions30d/${sessionId}`;
    if (body.action === 'delete') {
      keys(body, common);
      const lastSeq = Math.max(session.alignmentSeq || 0, body.seq);
      tx.delete(recordPath);
      tx.set(sessionPath, { ...nextSession, alignmentDeleted: true, alignmentSeq: lastSeq });
      return { ok: true, accepted: true, deleted: true, lastSeq };
    }
    keys(body, [...common, 'day', 'clientId', 'platform', 'interfaceLocale', 'contentLocale', 'attempts']);
    assert(body.action === 'upsert');
    assert(!session.alignmentDeleted, 'alignment_withdrawn', 410);
    // Presses before midnight may upload on a credential minted the next day.
    const mintDay = usageClock(session.createdAtMs).day, previousDay = usageClock(session.createdAtMs - DAY).day;
    assert(validListeningDay(body.day) && (body.day === mintDay || body.day === previousDay), 'alignment_day_mismatch');
    assert(['web', 'ios'].includes(body.platform) && INTERFACE_LOCALES.includes(body.interfaceLocale));
    assert(INTERFACE_LOCALES.includes(body.contentLocale) && contentLocales.get(source.pageId)?.has(body.contentLocale), 'unknown_content_locale');
    assert(body.clientId === null || (typeof body.clientId === 'string' && UUID.test(body.clientId)));
    assert(Array.isArray(body.attempts) && body.attempts.length > 0 && body.attempts.length <= ALIGNMENT_ATTEMPT_LIMIT);
    const attempts = body.attempts.map((item) => attempt(item, body.day, timestamp));
    for (let i = 1; i < attempts.length; i++) assert(attempts[i].at >= attempts[i - 1].at, 'invalid_alignment_time');
    const dailyClientKey = body.clientId === null ? null : hash(`${body.day}\0${body.platform}\0${body.clientId.toLowerCase()}`);
    if (session.alignmentDay) {
      assert(session.alignmentDay === body.day && session.alignmentPlatform === body.platform && session.alignmentClientKey === dailyClientKey
        && session.alignmentInterfaceLocale === body.interfaceLocale && session.alignmentContentLocale === body.contentLocale, 'alignment_identity_changed', 409);
    }
    const digest = hash(JSON.stringify({ day: body.day, platform: body.platform, dailyClientKey, interfaceLocale: body.interfaceLocale, contentLocale: body.contentLocale, attempts }));
    const lastSeq = session.alignmentSeq || 0;
    if (body.seq <= lastSeq) {
      assert(body.seq !== lastSeq || digest === session.alignmentDigest, 'alignment_sequence_conflict', 409);
      tx.set(sessionPath, nextSession);
      return { ok: true, accepted: false, lastSeq };
    }
    const old = await tx.get(recordPath);
    // Attempts are append-only: a later summary must repeat every stored attempt unchanged.
    if (old) assert(attempts.length >= old.attempts.length && old.attempts.every((item, i) => JSON.stringify(item) === JSON.stringify(attempts[i])), 'non_monotonic_summary');
    tx.set(recordPath, {
      ...stored, pageId: source.pageId ?? null, audioLocale: source.audioLocale ?? null,
      seq: body.seq, day: body.day, platform: body.platform, dailyClientKey,
      interfaceLocale: body.interfaceLocale, contentLocale: body.contentLocale, attempts,
      createdAt: old?.createdAt || new Date(timestamp), updatedAt: new Date(timestamp), expiresAt: new Date(timestamp + 30 * DAY),
    });
    tx.set(sessionPath, { ...nextSession, alignmentSeq: body.seq, alignmentDigest: digest, alignmentDay: body.day, alignmentPlatform: body.platform,
      alignmentClientKey: dailyClientKey, alignmentInterfaceLocale: body.interfaceLocale, alignmentContentLocale: body.contentLocale });
    return { ok: true, accepted: true, lastSeq: body.seq };
  };
}
