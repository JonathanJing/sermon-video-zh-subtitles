import { createHash, randomUUID } from 'node:crypto';

export const ORIGIN = 'https://ai-for-god-sermon-audio.web.app';
export const TOPIC = 'com.jonathanjing.tongxing.dev';
const LOCALES = ['zh-Hans', 'en', 'ko', 'es', 'vi'];
const SHA = /^[0-9a-f]{64}$/;
const TOKEN = /^(?:[0-9a-f]{2}){16,256}$/;
const IDENTIFIER = /^[A-Za-z0-9_-]+$/;

export function sha256(value) { return createHash('sha256').update(value).digest('hex'); }
const asDate = (value) => value?.toDate ? value.toDate() : value;

async function boundedJSON(path, maxBytes = 3_000_000) {
  const url = ORIGIN + path;
  const response = await fetch(url, { redirect: 'error', signal: AbortSignal.timeout(30000) });
  if (response.status === 404) throw new Error('published_content_absent');
  if (!response.ok || response.url !== url) throw new Error('published_content_unavailable');
  const chunks = [];
  let size = 0;
  for await (const chunk of response.body) {
    size += chunk.length;
    if (size > maxBytes) throw new Error('published_content_too_large');
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks);
  return { document: JSON.parse(raw.toString('utf8')), sha256: sha256(raw) };
}

async function boundedBytes(path, maxBytes = 5_000_000) {
  const url = ORIGIN + path;
  const response = await fetch(url, { redirect: 'error', signal: AbortSignal.timeout(30000) });
  if (!response.ok || response.url !== url) throw new Error('poster_unavailable');
  const chunks = [];
  let size = 0;
  for await (const chunk of response.body) {
    size += chunk.length;
    if (size > maxBytes) throw new Error('poster_too_large');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

export async function verifiedPublication() {
  let catalog;
  for (const version of ['v5', 'v4', 'v3']) {
    try {
      const result = await boundedJSON(`/multilingual-${version}.json`);
      if (result.document.schemaVersion !== `sermon-multilingual-catalog-${version}`) {
        throw new Error('catalog_schema_mismatch');
      }
      catalog = result.document;
      break;
    } catch (error) {
      if (error.message !== 'published_content_absent' || version === 'v3') throw error;
    }
  }
  const pageID = catalog.defaultPageId ?? catalog.defaultPageID;
  if (!IDENTIFIER.test(pageID ?? '')) throw new Error('invalid_default_page');
  const pages = catalog.pages.filter((page) => page.id === pageID);
  if (pages.length !== 1 || pages[0].simulationOnly || pages[0].diagnosticOnly) throw new Error('invalid_default_page');
  const page = pages[0];
  const sidecar = (await boundedJSON('/weekly-announcements-v1.json')).document;
  if (sidecar.schemaVersion !== 'tongxing-weekly-announcements-v1' || !Array.isArray(sidecar.announcements)) {
    throw new Error('announcement_schema_mismatch');
  }
  const byLocale = {};
  for (const locale of LOCALES) {
    const target = page.targets?.[locale];
    if (!target || !['human_reviewed', 'machine_checked'].includes(target.contentStatus) ||
        target.simulationOnly || target.diagnosticOnly || !SHA.test(target.releasePackageJsonSha256 ?? '')) continue;
    const edition = catalog.schemaVersion === 'sermon-multilingual-catalog-v5' && page.sourceMode === 'per_target'
      ? target.editionId : page.id;
    if (!IDENTIFIER.test(edition ?? '')) throw new Error('invalid_edition');
    const machine = target.contentStatus === 'machine_checked' || target.audioStatus === 'machine_checked';
    const releaseVersion = machine ? 'v4' : 'v2';
    const path = `/releases-${releaseVersion}/${edition}/${locale}.json`;
    if (target.releasePackageUrl !== path) throw new Error('release_path_mismatch');
    const release = await boundedJSON(path);
    if (release.sha256 !== target.releasePackageJsonSha256 ||
        release.document.schemaVersion !== `sermon-target-language-release-package-${releaseVersion}` ||
        release.document.status !== 'published_http_verified' ||
        release.document.httpVerification?.status !== 'pass' ||
        release.document.pageId !== edition || release.document.targetLocale !== locale ||
        release.document.contentStatus !== target.contentStatus ||
        release.document.audioStatus !== target.audioStatus) throw new Error('release_binding_mismatch');
    const posters = sidecar.announcements.filter((item) => item.pageID === pageID && item.locale === locale &&
      item.releaseSHA256 === target.releasePackageJsonSha256 &&
      item.sourceIdentitySHA256 === target.sourceIdentitySha256);
    if (posters.length !== 1 || !SHA.test(posters[0].poster?.sha256 ?? '') ||
        !/^\/posters\/[A-Za-z0-9_/-]+\.png$/.test(posters[0].poster.url)) {
      throw new Error('poster_binding_missing');
    }
    // The notification carries no image attachment. A verified App poster is
    // required because its tap destination promises a same-language poster.
    const posterBytes = await boundedBytes(posters[0].poster.url);
    if (posterBytes.length !== posters[0].poster.bytes || sha256(posterBytes) !== posters[0].poster.sha256) {
      throw new Error('poster_hash_mismatch');
    }
    byLocale[locale] = {
      schemaVersion: 'tongxing-production-notification-v1', environment: 'production',
      pageID, locale, releaseSHA256: target.releasePackageJsonSha256,
    };
  }
  if (!Object.keys(byLocale).length) throw new Error('no_published_locales');
  return { pageID, date: page.date, notices: byLocale };
}

export function eligibleSubscriptions(rows, publication, now = new Date()) {
  const eligible = [];
  const byToken = new Map();
  for (const row of rows) {
    if (!row.active || !asDate(row.activeUntil) || asDate(row.activeUntil).getTime() <= now.getTime() ||
        !publication.notices[row.locale] || !TOKEN.test(row.deviceToken ?? '') ||
        row.tokenHash !== sha256(row.deviceToken)) continue;
    const peers = byToken.get(row.tokenHash) ?? [];
    peers.push(row);
    byToken.set(row.tokenHash, peers);
  }
  let suppressedDuplicates = 0;
  for (const peers of byToken.values()) {
    if (peers.length === 1) eligible.push(peers[0]);
    else suppressedDuplicates += peers.length;
  }
  eligible.sort((a, b) => a.installationId.localeCompare(b.installationId));
  return { eligible, suppressedDuplicates };
}

export function dispatchKey(subscription, notice) {
  return sha256(JSON.stringify([TOPIC, subscription.installationId, notice.pageID,
    notice.locale, notice.releaseSHA256]));
}

/** Claim before network. Unknown outcomes remain claimed and cannot auto-retry. */
export async function dispatchOne({ store, subscription, notice, sendAPNs, now = () => new Date(), attemptID = randomUUID() }) {
  const key = dispatchKey(subscription, notice);
  const claimed = await store.transaction(async (tx) => {
    const [current, prior] = await Promise.all([
      tx.get(`pushSubscriptions/${subscription.installationId}`), tx.get(`pushDispatches/${key}`),
    ]);
    if (prior) return { claimed: false, reason: prior.status };
    if (!current || !current.active || !asDate(current.activeUntil) ||
        asDate(current.activeUntil).getTime() <= now().getTime() ||
        current.seq !== subscription.seq || current.tokenHash !== subscription.tokenHash ||
        current.deviceToken !== subscription.deviceToken ||
        current.locale !== notice.locale) return { claimed: false, reason: 'stale_subscription' };
    tx.set(`pushDispatches/${key}`, {
      schemaVersion: 1, status: 'outcome_unknown', attemptID, pageID: notice.pageID,
      locale: notice.locale, releaseSHA256: notice.releaseSHA256,
      installationId: subscription.installationId, tokenHash: subscription.tokenHash,
      claimedAt: now(), apnsID: attemptID,
    });
    return { claimed: true };
  });
  if (!claimed.claimed) return claimed;
  let response;
  try { response = await sendAPNs({ deviceToken: subscription.deviceToken, notice, apnsID: attemptID }); }
  catch { return { claimed: true, status: 'outcome_unknown' }; }
  const status = response.httpStatus === 200 ? 'accepted' : response.httpStatus ? 'rejected' : 'outcome_unknown';
  if (status === 'outcome_unknown') return { claimed: true, status };
  await store.transaction(async (tx) => {
    const path = `pushDispatches/${key}`;
    const current = await tx.get(path);
    if (!current || current.attemptID !== attemptID || current.status !== 'outcome_unknown') {
      throw new Error('dispatch_claim_changed');
    }
    tx.set(path, { ...current, status, httpStatus: response.httpStatus,
      apnsReason: response.reason ?? null, completedAt: now() });
  });
  return { claimed: true, status, httpStatus: response.httpStatus, reason: response.reason ?? null };
}
