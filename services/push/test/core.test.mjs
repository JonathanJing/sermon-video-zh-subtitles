import assert from 'node:assert/strict';
import { randomBytes, randomUUID } from 'node:crypto';
import test from 'node:test';
import { PushApiError, createSourceLimiter, createSubscriptionService,
  parseSubscriptionRequest } from '../core.mjs';
import { dispatchOne, eligibleSubscriptions, sha256, verifiedPublication } from '../send-core.mjs';

class MemoryStore {
  rows = new Map();
  async transaction(callback) {
    const writes = new Map();
    const result = await callback({
      get: async (path) => structuredClone(this.rows.get(path) ?? null),
      set: (path, value) => writes.set(path, structuredClone(value)),
    });
    for (const [path, value] of writes) this.rows.set(path, value);
    return result;
  }
}

const installationId = randomUUID();
const secret = randomBytes(32).toString('base64url');
const deviceToken = 'ab'.repeat(32);
const request = (seq = 1, extra = {}) => ({ schemaVersion: 1, action: 'upsert',
  installationId, secret, seq, deviceToken, locale: 'zh-Hans', ...extra });
const deleteRequest = (seq) => ({ schemaVersion: 1, action: 'delete', installationId, secret, seq });
const expectCode = async (promise, status, code) => assert.rejects(promise,
  (error) => error instanceof PushApiError && error.status === status && error.code === code);

test('explicit published page is verified even while catalog default remains old', async () => {
  const pageID = 'new_week';
  const locale = 'zh-Hans';
  const releasePath = `/releases-v2/${pageID}/${locale}.json`;
  const release = Buffer.from(JSON.stringify({ schemaVersion: 'sermon-target-language-release-package-v2',
    status: 'published_http_verified', httpVerification: { status: 'pass' }, pageId: pageID,
    targetLocale: locale, contentStatus: 'human_reviewed', audioStatus: 'human_reviewed' }));
  const poster = Buffer.from('verified poster bytes');
  const posterPath = `/posters/${pageID}/zh-Hans-poster.png`;
  const sourceIdentitySha256 = 'a'.repeat(64);
  const target = { contentStatus: 'human_reviewed', audioStatus: 'human_reviewed',
    releasePackageUrl: releasePath, releasePackageJsonSha256: sha256(release), sourceIdentitySha256 };
  const documents = new Map([
    ['/multilingual-v5.json', Buffer.from(JSON.stringify({ schemaVersion: 'sermon-multilingual-catalog-v5',
      defaultPageId: 'old_week', pages: [{ id: 'old_week', targets: {} },
        { id: pageID, date: '2026-10-25', sourceIdentitySha256, targets: { [locale]: target } }] }))],
    ['/weekly-announcements-v1.json', Buffer.from(JSON.stringify({ schemaVersion: 'tongxing-weekly-announcements-v1',
      announcements: [{ pageID, locale, releaseSHA256: sha256(release), sourceIdentitySHA256: sourceIdentitySha256,
        title: '耶稣得胜 · 启示录 12–13 章', poster: { url: posterPath, sha256: sha256(poster), bytes: poster.length } }] }))],
    [releasePath, release], [posterPath, poster],
  ]);
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const bytes = documents.get(new URL(url).pathname);
    const response = new Response(bytes ?? '', { status: bytes ? 200 : 404 });
    Object.defineProperty(response, 'url', { value: url });
    return response;
  };
  try {
    const result = await verifiedPublication(pageID);
    assert.equal(result.pageID, pageID);
    assert.deepEqual(Object.keys(result.notices), [locale]);
    assert.equal(result.copy[locale].title, '耶稣得胜 · 启示录 12–13 章');
    assert.match(result.copy[locale].body, /查看海报/);
    await assert.rejects(verifiedPublication(), /no_published_locales/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('strict request parsing rejects extra fields and malformed credential/token', () => {
  assert.equal(parseSubscriptionRequest(request()).deviceToken, deviceToken);
  for (const invalid of [request(1, { arbitrary: true }), request(1, { secret: 'abc' }),
    request(1, { deviceToken: 'not-hex' }), request(1, { locale: 'fr' }),
    request(0), request(1, { action: 'delete' })]) {
    assert.throws(() => parseSubscriptionRequest(invalid), (error) => error.code === 'invalid_request');
  }
});

test('upsert, exact replay, rotation, withdrawal and tombstone sequence', async () => {
  const store = new MemoryStore();
  const clock = new Date('2026-10-22T05:00:00Z');
  const subscribe = createSubscriptionService({ store, now: () => clock });
  const first = await subscribe(request());
  assert.equal(first.active, true);
  assert.equal(first.replayed, false);
  assert.equal(first.activeUntil, '2026-12-21T05:00:00.000Z');
  assert.equal((await subscribe(request())).replayed, true);
  await expectCode(subscribe(request(1, { locale: 'ko' })), 409, 'sequence_conflict');
  await expectCode(subscribe(request(2, { secret: randomBytes(32).toString('base64url') })), 403, 'subscription_unavailable');
  const rotated = await subscribe(request(2, { deviceToken: 'cd'.repeat(32), locale: 'ko' }));
  assert.equal(rotated.active, true);
  assert.equal(store.rows.get(`pushSubscriptions/${installationId.toLowerCase()}`).locale, 'ko');
  await expectCode(subscribe(request(1)), 409, 'stale_sequence');
  assert.equal((await subscribe(deleteRequest(3))).active, false);
  assert.equal(store.rows.get(`pushSubscriptions/${installationId.toLowerCase()}`).deviceToken, null);
  assert.equal((await subscribe(deleteRequest(3))).replayed, true);
  await expectCode(subscribe(request(3)), 409, 'sequence_conflict');
  assert.equal((await subscribe(request(4))).active, true);
});

test('global and ephemeral source limits reject bursts without exposing input', async () => {
  const store = new MemoryStore();
  const subscribe = createSubscriptionService({ store, now: () => new Date('2026-10-22T05:00:00Z'),
    maxPerMinute: 1, maxPerDay: 2 });
  await subscribe(request());
  await expectCode(subscribe(request()), 429, 'temporarily_limited');
  const limiter = createSourceLimiter({ now: () => 1_000_000, maxPerMinute: 1 });
  limiter('example-address');
  assert.throws(() => limiter('example-address'), (error) => error.code === 'temporarily_limited');
});

test('fanout excludes expiry, unsupported locale and duplicate APNs tokens', () => {
  const now = new Date('2026-10-22T05:00:00Z');
  const valid = { installationId: 'a', active: true, activeUntil: new Date(now.getTime() + 1000),
    tokenHash: sha256(deviceToken), deviceToken, locale: 'zh-Hans', seq: 1 };
  const publication = { notices: { 'zh-Hans': {} } };
  const result = eligibleSubscriptions([valid, { ...valid, installationId: 'b',
    activeUntil: new Date(now.getTime() - 1000) }, { ...valid, installationId: 'c', locale: 'ko' }], publication, now);
  assert.deepEqual(result.eligible.map((item) => item.installationId), ['a']);
  assert.equal(eligibleSubscriptions([valid, { ...valid, installationId: 'd' }], publication, now).suppressedDuplicates, 2);
});

test('claim prevents duplicate sends; unknown outcome cannot be retried automatically', async () => {
  const store = new MemoryStore();
  const now = new Date('2026-10-22T05:00:00Z');
  const row = { installationId, seq: 1, active: true, activeUntil: new Date(now.getTime() + 1000),
    tokenHash: 'a'.repeat(64), deviceToken, locale: 'zh-Hans' };
  store.rows.set(`pushSubscriptions/${installationId}`, row);
  const notice = { pageID: 'resi-20261018-15030286', locale: 'zh-Hans', releaseSHA256: 'b'.repeat(64) };
  let sends = 0;
  const sendAPNs = async () => { sends++; throw new Error('network_unknown'); };
  assert.deepEqual(await dispatchOne({ store, subscription: row, notice, sendAPNs, now: () => now,
    attemptID: randomUUID() }), { claimed: true, status: 'outcome_unknown' });
  assert.equal((await dispatchOne({ store, subscription: row, notice, sendAPNs, now: () => now,
    attemptID: randomUUID() })).claimed, false);
  assert.equal(sends, 1);
});

test('accepted APNs response is recorded separately from device delivery', async () => {
  const store = new MemoryStore();
  const now = new Date('2026-10-22T05:00:00Z');
  const row = { installationId, seq: 1, active: true, activeUntil: new Date(now.getTime() + 1000),
    tokenHash: 'a'.repeat(64), deviceToken, locale: 'zh-Hans' };
  store.rows.set(`pushSubscriptions/${installationId}`, row);
  const notice = { pageID: 'resi-20261018-15030286', locale: 'zh-Hans', releaseSHA256: 'b'.repeat(64) };
  const result = await dispatchOne({ store, subscription: row, notice,
    sendAPNs: async () => ({ httpStatus: 200, reason: null }), now: () => now, attemptID: randomUUID() });
  assert.equal(result.status, 'accepted');
  const ledger = [...store.rows.entries()].find(([path]) => path.startsWith('pushDispatches/'))[1];
  assert.equal(ledger.status, 'accepted');
  assert.equal(ledger.httpStatus, 200);
  assert.equal(ledger.expiresAt.toISOString(), '2027-10-22T05:00:00.000Z');
  assert.equal(Object.hasOwn(ledger, 'deviceDisplayed'), false);
});
