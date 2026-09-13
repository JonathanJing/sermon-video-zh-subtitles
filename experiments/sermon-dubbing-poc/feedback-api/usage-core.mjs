import { createHash } from 'node:crypto';

export const USAGE_ACTIONS = Object.freeze([
  'app_open', 'page_visible', 'page_hidden', 'page_heartbeat',
  'play_click', 'pause_click', 'back_5_click', 'forward_5_click',
  'nudge_back_1_click', 'nudge_back_quarter_click', 'nudge_forward_quarter_click', 'nudge_forward_1_click',
  'progress_seek', 'time_jump', 'transcript_seek', 'week_select', 'track_select',
  'tab_listen', 'tab_transcript', 'tab_production', 'tab_voices', 'outline_open', 'outline_close',
  'theme_toggle', 'download_click', 'source_link', 'feedback_up', 'feedback_down',
  'feedback_point', 'feedback_details', 'feedback_submit', 'feedback_close',
  'feedback_retract_vote', 'feedback_retract_issue', 'voice_reference_play',
  'voice_reference_pause', 'voice_chinese_play', 'voice_chinese_pause', 'probe_text_open',
  'seek_undo', 'position_restore', 'position_restart', 'transcript_current',
  'more_open', 'precision_open', 'feedback_section_open',
]);
export const USAGE_PANELS = Object.freeze(['listen', 'transcript', 'production', 'voices', 'outline', 'feedback']);
export const USAGE_EVENT_LIMIT = 500;
const DAY = 86400000;
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
const hash = (value) => createHash('sha256').update(value).digest('hex');
const formatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hourCycle: 'h23',
});
export function usageClock(at) {
  const parts = Object.fromEntries(formatter.formatToParts(new Date(at)).map(({ type, value }) => [type, value]));
  return { day: `${parts.year}-${parts.month}-${parts.day}`, hour: Number(parts.hour) };
}
const plain = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const integer = (value, max = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(value) && value >= 0 && value <= max;
const millis = (value) => value?.toMillis?.() ?? value?.getTime?.() ?? null;

/** Reuses the source-bound memory credential, but has its own sequence and tombstone. */
export function createUsageHandler({ catalog, ApiError }) {
  const assert = (condition, code = 'invalid_usage_payload', status = 400) => { if (!condition) throw new ApiError(status, code); };
  const exactKeys = (value, allowed) => assert(plain(value) && Object.keys(value).length === allowed.length && allowed.every((key) => Object.hasOwn(value, key)));
  const commonKeys = ['schemaVersion', 'week', 'trackId', 'audioSha256', 'appVersion'];
  const eventKeys = ['at', 'action', 'panel', 'week', 'trackId', 'positionSeconds', 'speakerId'];
  const actions = new Set(USAGE_ACTIONS), panels = new Set(USAGE_PANELS);
  const suppliedWeeks = catalog.weekIds ?? catalog.sources.map((source) => source.week);
  const suppliedVoices = catalog.voiceIds ?? [];
  assert(Array.isArray(suppliedWeeks) && suppliedWeeks.every((id) => typeof id === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(id)), 'invalid_usage_catalog', 503);
  assert(Array.isArray(suppliedVoices) && suppliedVoices.every((id) => typeof id === 'string' && id.length > 0 && id.length <= 160), 'invalid_usage_catalog', 503);
  const weeks = new Set([...suppliedWeeks, ...catalog.sources.map((source) => source.week)]), voices = new Set(suppliedVoices);
  const tracks = new Map();
  for (const source of catalog.sources) {
    const key = `${source.week}\0${source.trackId}`;
    tracks.set(key, Math.max(tracks.get(key) || 0, source.durationSeconds));
  }

  return async ({ tx, body, session, nextSession, sessionPath, sessionId, stored, timestamp }) => {
    const recordPath = `usageSessions/${sessionId}`;
    if (body.action === 'delete') {
      exactKeys(body, [...commonKeys, 'action']);
      // Terminal for this usage credential. An append arriving after withdrawal
      // must not recreate the document; re-enabling uses a new page credential.
      tx.delete(recordPath);
      tx.set(sessionPath, { ...nextSession, usageDeleted: true });
      return { ok: true, accepted: true, deleted: true };
    }
    exactKeys(body, [...commonKeys, 'action', 'seq', 'day', 'browserId', 'events', 'droppedEvents']);
    assert(body.action === 'append');
    assert(!session.usageDeleted, 'usage_withdrawn', 410);
    assert(integer(body.seq, 1000000) && body.seq > 0);
    assert(typeof body.day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(body.day));
    assert(body.browserId === null || (typeof body.browserId === 'string' && UUID.test(body.browserId)));
    assert(Array.isArray(body.events) && body.events.length <= 30);
    assert(integer(body.droppedEvents, 10000) && (body.events.length > 0 || body.droppedEvents > 0));
    const canonicalEvents = body.events.map((event) => {
      exactKeys(event, eventKeys);
      assert(integer(event.at) && event.at >= timestamp - DAY && event.at >= session.createdAtMs - 300000 && event.at <= timestamp + 300000, 'invalid_usage_time');
      assert(usageClock(event.at).day === body.day, 'usage_day_mismatch');
      assert(actions.has(event.action) && panels.has(event.panel));
      assert(event.week === null || weeks.has(event.week), 'invalid_usage_context');
      assert(event.trackId === null || (typeof event.trackId === 'string' && event.week !== null && tracks.has(`${event.week}\0${event.trackId}`)), 'invalid_usage_context');
      const duration = event.trackId === null ? null : tracks.get(`${event.week}\0${event.trackId}`);
      assert(event.positionSeconds === null || (duration !== null && typeof event.positionSeconds === 'number' && Number.isFinite(event.positionSeconds) && event.positionSeconds >= 0 && event.positionSeconds <= duration), 'invalid_usage_context');
      const voiceAction = event.action.startsWith('voice_') || event.action === 'probe_text_open';
      assert(event.speakerId === null || (voiceAction && voices.has(event.speakerId)), 'invalid_usage_context');
      // Canonical key order makes the retry digest independent of JSON key order.
      return Object.fromEntries(eventKeys.map((key) => [key, event[key]]));
    });
    // A drop-only report is still scoped to the current server-derived LA day.
    if (!body.events.length) assert(body.day === usageClock(timestamp).day, 'usage_day_mismatch');
    const dailyBrowserKey = body.browserId === null ? null : hash(`${body.day}\0${body.browserId.toLowerCase()}`);
    const digest = hash(JSON.stringify({ day: body.day, dailyBrowserKey, events: canonicalEvents, droppedEvents: body.droppedEvents }));
    const lastSeq = session.usageSeq || 0;
    if (body.seq === lastSeq && digest === session.usageDigest) {
      tx.set(sessionPath, nextSession);
      return { ...session.usageLastResult, replayed: true };
    }
    assert(body.seq > lastSeq, 'usage_sequence_conflict', 409);
    assert(body.seq === lastSeq + 1, 'usage_sequence_gap', 409);
    assert(!session.usageDay || session.usageDay === body.day, 'usage_day_changed', 409);
    assert(!session.usageDay || session.usageBrowserKey === dailyBrowserKey, 'usage_browser_changed', 409);

    const old = await tx.get(recordPath);
    const oldEvents = old?.events || [];
    const remaining = Math.max(0, USAGE_EVENT_LIMIT - oldEvents.length);
    const receivedAt = new Date(timestamp);
    const acceptedEvents = canonicalEvents.slice(0, remaining).map((event, index) => ({
      ...event, at: new Date(Math.floor(event.at / 1000) * 1000), receivedAt,
      sequence: oldEvents.length + index + 1, hour: usageClock(event.at).hour,
    }));
    const totalEvents = oldEvents.length + acceptedEvents.length;
    const droppedEvents = Math.min(Number.MAX_SAFE_INTEGER, (old?.droppedEvents || 0) + body.droppedEvents + canonicalEvents.length - acceptedEvents.length);
    const allTimes = acceptedEvents.map((event) => event.at.getTime());
    const priorFirst = millis(old?.firstEventAt), priorLast = millis(old?.lastEventAt);
    if (priorFirst !== null) allTimes.push(priorFirst);
    if (priorLast !== null) allTimes.push(priorLast);
    const result = { ok: true, accepted: true, replayed: false, lastSeq: body.seq, totalEvents, droppedEvents, closed: totalEvents >= USAGE_EVENT_LIMIT };
    tx.set(recordPath, {
      ...stored, seq: body.seq, day: body.day, dailyBrowserKey,
      events: [...oldEvents, ...acceptedEvents], totalEvents, droppedEvents,
      firstReceivedAt: old?.firstReceivedAt || receivedAt, updatedAt: receivedAt,
      firstEventAt: allTimes.length ? new Date(Math.min(...allTimes)) : null,
      lastEventAt: allTimes.length ? new Date(Math.max(...allTimes)) : null,
      expiresAt: new Date(timestamp + 30 * DAY),
    });
    tx.set(sessionPath, {
      ...nextSession, usageSeq: body.seq, usageDigest: digest,
      usageDay: body.day, usageBrowserKey: dailyBrowserKey, usageLastResult: result,
    });
    return result;
  };
}
