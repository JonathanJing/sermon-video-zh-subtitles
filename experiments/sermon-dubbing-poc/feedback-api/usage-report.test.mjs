import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ACTIONS, epoch, escapeHtml, fetchUsageSessions, parseUsageArgs, renderUsageHtml, summarizeUsage, validateRange, writeUsageReport } from './usage-report.mjs';
import { USAGE_ACTIONS } from './usage-core.mjs';

const now = Date.parse('2026-09-07T00:00:00Z');
const options = { from: '2026-09-05', to: '2026-09-06', now };
const browser = 'a'.repeat(64);
function event(action = 'app_open', at = '2026-09-05T15:00:00Z', extra = {}) {
  return { at: Date.parse(at), action, panel: 'listen', week: '2026-08-30', trackId: 'full_candidate', positionSeconds: 1, speakerId: null, ...extra };
}
function session(events = [event()], extra = {}) {
  return { day: '2026-09-05', dailyBrowserKey: browser, firstReceivedAt: new Date('2026-09-05T16:00:00Z'), events, droppedEvents: 0, totalEvents: events.length, ...extra };
}

test('daily browsers deduplicate sessions, cross-day totals are browser-days and null identities stay separate', () => {
  const report = summarizeUsage([session(), session(), session([event('app_open', '2026-09-06T15:00:00Z')], { day: '2026-09-06', dailyBrowserKey: browser, firstReceivedAt: new Date('2026-09-06T16:00:00Z') }), session([], { dailyBrowserKey: null })], options);
  assert.deepEqual(report.daily.map(({ anonymousBrowsers, sessions }) => [anonymousBrowsers, sessions]), [[1, 3], [1, 1]]);
  assert.equal(report.totals.browserDays, 2);
  assert.equal(report.totals.sessions, 4);
  assert.equal(report.totals.sessionsWithoutBrowserId, 1);
  assert.match(report.definitions.browserDays, /不是月度 UV/);
  assert.ok(!JSON.stringify(report).includes(browser));
});

test('all accepted backend actions have report labels', () => {
  assert.deepEqual(Object.keys(ACTIONS).filter((key) => key !== 'unknown').sort(), [...USAGE_ACTIONS].sort());
});

test('visible heartbeats deduplicate per session-hour and action usage counts sessions separately from events', () => {
  const report = summarizeUsage([session([event(), event('page_heartbeat'), event('page_heartbeat', '2026-09-05T15:01:00Z'), event('page_heartbeat', '2026-09-05T16:00:00Z')]), session([event('page_heartbeat')])], options);
  assert.equal(report.hourly[8].activeSessionHours, 2);
  assert.equal(report.hourly[9].activeSessionHours, 1);
  assert.deepEqual(report.actions.find(({ key }) => key === 'page_heartbeat'), { key: 'page_heartbeat', label: '页面可见心跳', events: 4, sessions: 2 });
  assert.equal(report.panels[0].sessions, 2);
  assert.match(report.definitions.hourly, /不代表人在操作/);
});

test('funnel is documented session intersection, and timeline orders event time then server sequence', () => {
  const report = summarizeUsage([session([event('download_click', undefined, { sequence: 3 }), event('play_click', undefined, { sequence: 2 }), event('app_open', undefined, { sequence: 1 })]), session([event('download_click')]), session([event(), event('play_click')])], options);
  assert.deepEqual(report.funnel, { appOpenSessions: 2, appOpenAndPlaySessions: 2, appOpenAndPlayAndDownloadSessions: 1 });
  assert.deepEqual(report.sessions[0].events.map((row) => row.action), ['app_open', 'play_click', 'download_click']);
  assert.match(report.definitions.funnel, /不要求先后顺序/);
});

test('retention uses server firstReceivedAt and accepts Date, Firestore Timestamp and epoch timestamps', () => {
  const millis = Date.parse('2026-09-05T16:00:00Z');
  const timestamp = { toMillis: () => millis };
  assert.equal(epoch(timestamp), millis);
  assert.equal(epoch({ toDate: () => new Date(millis) }), millis);
  const report = summarizeUsage([session([event('app_open', undefined, { at: timestamp })], { firstReceivedAt: timestamp }), session([], { firstReceivedAt: now - 31 * 86400000 }), session([], { firstReceivedAt: now + 1000 }), session([], { firstReceivedAt: null }), session([event('app_open', '2026-09-07T15:00:00Z')], { firstReceivedAt: millis })], options);
  assert.equal(report.totals.sessions, 2);
  assert.equal(report.totals.ignoredRecords, 3);
  assert.equal(report.totals.ignoredEvents, 1);
  assert.equal(report.totals.events, 1);
});

test('event LA date must match its stored session day even when both days are in the selected range', () => {
  const report = summarizeUsage([session([event('app_open', '2026-09-06T15:00:00Z')])], options);
  assert.equal(report.totals.events, 0);
  assert.equal(report.totals.ignoredEvents, 1);
  assert.ok(report.hourly.every((row) => row.activeSessionHours === 0));
});

test('cap and recorded drops remain separate and do not claim knowledge of post-cap traffic', () => {
  const report = summarizeUsage([session([event()], { totalEvents: 500, droppedEvents: 0 }), session([event()], { droppedEvents: 12 })], options);
  assert.equal(report.totals.cappedSessions, 1);
  assert.equal(report.totals.droppedEvents, 12);
  assert.equal(report.totals.sessionsWithDroppedEvents, 1);
  assert.match(report.definitions.limits, /停止后的事件数量未知/);
  assert.match(renderUsageHtml(report), /达到事件上限的会话：1/);
});

test('unknown metadata and unexpected secrets never enter JSON or HTML; known voices are counted', () => {
  const secret = '<script>private-token-and-feedback</script>';
  const report = summarizeUsage([session([event(secret, undefined, { panel: secret, week: secret, trackId: secret, speakerId: secret, positionSeconds: Infinity, comment: secret }), event('voice_chinese_play', undefined, { speakerId: 'christine_caine' })], { documentId: secret, token: secret, comment: secret })], options);
  const output = JSON.stringify(report) + renderUsageHtml(report);
  assert.ok(!output.includes(secret));
  assert.ok(!output.includes('private-token-and-feedback'));
  assert.ok(!output.includes(browser));
  assert.equal(report.actions.find((row) => row.key === 'unknown').events, 1);
  assert.deepEqual(report.voices, [{ key: 'Christine Caine', label: 'Christine Caine', events: 1, sessions: 1 }]);
  assert.equal(report.sessions[0].events[0].week, null);
  assert.equal(report.sessions[0].events[0].positionSeconds, null);
});

test('HTML escaping is safe and report is self-contained with no script or external resources', () => {
  assert.equal(escapeHtml('<b a="x">&\'</b>'), '&lt;b a=&quot;x&quot;&gt;&amp;&#39;&lt;/b&gt;');
  const report = summarizeUsage([], options);
  report.definitions.coverage = '<img src=x onerror="attack()">';
  const html = renderUsageHtml(report);
  assert.ok(html.includes('&lt;img src=x onerror=&quot;attack()&quot;&gt;'));
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('<script'));
  assert.ok(!/\b(?:src|href)=["']https?:/.test(html));
  assert.match(html, /default-src 'none'/);
});

test('zero state distinguishes absence of received data from absence of visitors', () => {
  const report = summarizeUsage([], options);
  assert.equal(report.totals.sessions, 0);
  assert.equal(report.daily.length, 2);
  assert.ok(report.hourly.every((row) => row.activeSessionHours === 0));
  assert.match(renderUsageHtml(report), /这不表示没有人使用应用/);
});

test('strict date and argument bounds reject impossible dates, reversed ranges and more than 31 days', () => {
  assert.deepEqual(parseUsageArgs(['--from', '2026-08-01', '--to', '2026-08-31', '--out', '/tmp/new-private-report']), { from: '2026-08-01', to: '2026-08-31', out: '/tmp/new-private-report' });
  for (const [from, to] of [['2026-02-30', '2026-03-01'], ['2026-08-02', '2026-08-01'], ['2026-08-01', '2026-09-01'], ['x', '2026-08-01']]) assert.throws(() => validateRange(from, to));
  for (const args of [['--from', '2026-08-01'], ['--from', '2026-08-01', '--to', '2026-08-02', '--out', '/tmp/x', '--out', '/tmp/y'], ['--other', 'x']]) assert.throws(() => parseUsageArgs(args));
});

function fakeDatabase(records) {
  const calls = [];
  const docs = records.map((record, index) => ({ id: `private-db-id-${index}`, index, data: () => record }));
  function query(start = 0, limit = 500) {
    return {
      where(...args) { calls.push(['where', ...args]); return this; },
      orderBy(...args) { calls.push(['orderBy', ...args]); return this; },
      limit(count) { calls.push(['limit', count]); return query(start, count); },
      startAfter(doc) { calls.push(['startAfter', doc.index]); return query(doc.index + 1, limit); },
      async get() { return { docs: docs.slice(start, start + limit) }; },
    };
  }
  return { calls, collection(name) { calls.push(['collection', name]); return query(); } };
}

test('query paginates one bounded collection and marks a hard-cap partial report without outputting IDs', async () => {
  const db = fakeDatabase([session(), session(), session(), session()]);
  const { records, query } = await fetchUsageSessions(db, { ...options, pageSize: 2, maxDocuments: 3 });
  assert.equal(records.length, 3);
  assert.equal(query.documentsRead, 4);
  assert.equal(query.truncated, true);
  assert.deepEqual(db.calls.filter(([name]) => name === 'collection'), [['collection', 'usageSessions']]);
  assert.deepEqual(db.calls.filter(([name]) => name === 'where'), [['where', 'day', '>=', options.from], ['where', 'day', '<=', options.to]]);
  assert.ok(db.calls.some(([name]) => name === 'startAfter'));
  const report = summarizeUsage(records, { ...options, query });
  assert.ok(!JSON.stringify(report).includes('private-db-id'));
  assert.match(renderUsageHtml(report), /结果已截断/);
  const complete = await fetchUsageSessions(fakeDatabase([session(), session()]), { ...options, pageSize: 2, maxDocuments: 2 });
  assert.equal(complete.query.truncated, false);
});

test('report files are exclusive and private, leaving prior output untouched', async () => {
  const root = await mkdtemp(join(tmpdir(), 'sermon-usage-test-'));
  try {
    const report = summarizeUsage([], options), out = join(root, 'report');
    const result = await writeUsageReport(out, report);
    assert.equal(result.sessions, 0);
    assert.deepEqual(JSON.parse(await readFile(join(out, 'summary.json'), 'utf8')), report);
    assert.equal((await stat(out)).mode & 0o777, 0o700);
    assert.equal((await stat(join(out, 'summary.json'))).mode & 0o777, 0o600);
    const before = await readFile(join(out, 'index.html'), 'utf8');
    await assert.rejects(writeUsageReport(out, report), { code: 'EEXIST' });
    assert.equal(await readFile(join(out, 'index.html'), 'utf8'), before);
  } finally { await rm(root, { recursive: true, force: true }); }
});
