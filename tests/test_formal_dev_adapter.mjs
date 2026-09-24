import assert from 'node:assert/strict';
import test from 'node:test';
import {
  formalReleaseView, loadOptionalFormalCatalog, validateFormalCaptions, validateFormalCatalog,
  validateFormalContent, validateFormalRelease
} from '../firebase/dev/public/formal-dev-adapter.mjs';

const hash = digit => digit.repeat(64);
const pageId = 'formal-page-1';
const locale = 'ko';
const page = {
  id: pageId, date: '2026-09-20', sourceLocale: 'en', sourceIdentitySha256: hash('a'),
  defaultTargetLocale: 'zh-Hans', targets: Object.fromEntries(['zh-Hans', 'ko', 'es'].map(key =>
    [key, { releasePackageUrl: `/releases/${pageId}/${key}.json`,
      releasePackageJsonSha256: hash('b'), contentStatus: 'human_reviewed',
      audioStatus: 'human_reviewed', capabilities: ['text', 'captions', 'audio'] }]))
};
const catalog = { schemaVersion: 'sermon-multilingual-catalog-v2', generatedAt: '2026-09-23T00:00:00Z',
  defaultPageId: pageId, pages: [page] };
const release = {
  schemaVersion: 'sermon-target-language-release-package-v1', packageId: 'fixture',
  pageId, sourceLocale: 'en', targetLocale: locale,
  targetLanguageCandidateJsonSha256: hash('c'), targetLanguageAudioPackageJsonSha256: hash('d'),
  status: 'candidate', contentStatus: 'human_reviewed', audioStatus: 'human_reviewed',
  interfaceLocale: locale, contentLocale: locale, audioLocale: locale,
  assets: [
    { role: 'content', path: `/content/${pageId}/${locale}.json`, sha256: hash('e') },
    { role: 'audio', path: `/media/${pageId}/${locale}.wav`, sha256: hash('f') },
    { role: 'captions', path: `/captions/${pageId}/${locale}.json`, sha256: hash('1') }
  ],
  httpVerification: { status: 'not_run', evidenceSha256: null },
  deviceAcceptance: { status: 'not_run', evidenceSha256: null },
  venueAcceptance: { status: 'not_run', evidenceSha256: null }, issues: []
};
const content = {
  schemaVersion: 'sermon-formal-dev-content-v1', pageId, sourceLocale: 'en', locale,
  englishSourcePackageJsonSha256: hash('a'),
  targetLanguageCandidateJsonSha256: hash('c'), targetLanguageAudioPackageJsonSha256: hash('d'),
  contentStatus: 'human_reviewed', audioStatus: 'human_reviewed',
  series: 'Series', title: 'Title', speaker: 'Speaker', scripture: 'Revelation', date: '2026-09-20',
  summary: 'Summary', durationSeconds: 1,
  cues: [{ textGroupId: 'g1', sourceUnitIds: ['u1'], start: 0, end: 1, text: 'Text' }], outline: []
};
const captions = { cues: [{ textGroupId: 'g1', text: 'Text', start: 0, end: 1 }] };
const clone = value => structuredClone(value);

test('optional formal catalog failure leaves POC catalog available', async () => {
  const quiet = console.warn;
  console.warn = () => {};
  try {
    assert.equal(await loadOptionalFormalCatalog(async () => { throw new Error('offline'); }), null);
    assert.equal(await loadOptionalFormalCatalog(async () => ({ ok: false, status: 503 })), null);
    assert.equal(await loadOptionalFormalCatalog(async () => ({ ok: true, status: 200,
      json: async () => ({ malformed: true }) })), null);
    assert.equal(await loadOptionalFormalCatalog(async () => ({ ok: true, status: 200,
      json: async () => catalog }), [pageId]), null);
    assert.deepEqual(await loadOptionalFormalCatalog(async () => ({ ok: true, status: 200,
      json: async () => catalog })), catalog);
  } finally {
    console.warn = quiet;
  }
});

test('formal page IDs match the player route grammar', () => {
  for (const invalid of ['_leading', '-leading', 'x'.repeat(129)]) {
    const changed = clone(catalog);
    changed.defaultPageId = invalid;
    changed.pages[0].id = invalid;
    assert.throws(() => validateFormalCatalog(changed));
  }
  const dotted = clone(catalog);
  dotted.defaultPageId = 'formal.page-1';
  dotted.pages[0].id = 'formal.page-1';
  for (const target of Object.values(dotted.pages[0].targets)) {
    target.releasePackageUrl = target.releasePackageUrl.replace(pageId, 'formal.page-1');
  }
  assert.deepEqual(validateFormalCatalog(dotted), dotted);
});

test('formal v2 catalog and release produce a separate verified player view', () => {
  validateFormalCatalog(catalog);
  const checked = validateFormalRelease(release, page, locale);
  validateFormalContent(content, release, page, locale);
  validateFormalCaptions(captions, content);
  const view = formalReleaseView(checked, page, locale);
  assert.equal(view.formal, true);
  assert.equal(view.schemaVersion, 'sermon-target-language-release-package-v1');
  assert.equal(view.audioUrl, `/media/${pageId}/${locale}.wav`);
  assert.equal(view.pageUrl, `/pages/${pageId}/${locale}`);
  assert.equal(view.status, 'candidate');
});

test('formal reader accepts reviewed MP3 delivery without changing locale binding', () => {
  const compressed = clone(release);
  compressed.assets[1].path = `/media/${pageId}/${locale}.mp3`;
  const view = formalReleaseView(validateFormalRelease(compressed, page, locale), page, locale);
  assert.equal(view.audioUrl, compressed.assets[1].path);
  const foreign = clone(compressed);
  foreign.assets[1].path = `/media/${pageId}/es.mp3`;
  assert.throws(() => validateFormalRelease(foreign, page, locale));
});

test('formal reader rejects POC relabeling but accepts independently published locales', () => {
  assert.throws(() => validateFormalCatalog({ ...catalog, schemaVersion: 'sermon-multilingual-demo-catalog-v1' }));
  const incomplete = clone(catalog);
  delete incomplete.pages[0].targets.es;
  assert.deepEqual(validateFormalCatalog(incomplete), incomplete);
  delete incomplete.pages[0].targets.ko;
  assert.deepEqual(validateFormalCatalog(incomplete), incomplete);
  delete incomplete.pages[0].targets['zh-Hans'];
  assert.throws(() => validateFormalCatalog(incomplete));
  const second = clone(catalog);
  second.pages.push({ ...clone(page), id: 'next-week',
    targets: { ko: { ...page.targets.ko, releasePackageUrl: '/releases/next-week/ko.json' } },
    defaultTargetLocale: 'ko' });
  assert.deepEqual(validateFormalCatalog(second), second);
  second.pages[1].id = pageId;
  assert.throws(() => validateFormalCatalog(second));
  assert.throws(() => validateFormalRelease({ ...release, poc: true, schemaVersion: 'sermon-target-language-demo-package-v1' }, page, locale));
  assert.throws(() => validateFormalRelease({ ...release, poc: true }, page, locale));
  assert.throws(() => validateFormalRelease({ ...release, audioVariants: [
    { audioUrl: '/media/other/ko.mp3', audioSha256: hash('3') }
  ] }, page, locale));
});

test('formal reader rejects cross-locale assets, review drift and unverified text', () => {
  const otherLocale = clone(release);
  otherLocale.assets[1].path = `/media/${pageId}/es.wav`;
  assert.throws(() => validateFormalRelease(otherLocale, page, locale));
  assert.throws(() => validateFormalRelease({ ...release, audioStatus: 'candidate' }, page, locale));
  assert.throws(() => validateFormalContent({ ...content, targetLanguageCandidateJsonSha256: hash('0') }, release, page, locale));
  assert.throws(() => validateFormalContent({ ...content, poc: true }, release, page, locale));
  assert.throws(() => validateFormalContent({ ...content, cues: [{ ...content.cues[0], end: 3 }] }, release, page, locale));
  assert.throws(() => validateFormalCaptions({ cues: [{ ...captions.cues[0], text: 'Changed' }] }, content));
});

test('HTTP publication claim needs evidence and does not imply device acceptance', () => {
  const published = { ...release, status: 'published_http_verified',
    httpVerification: { status: 'pass', evidenceSha256: hash('2') } };
  assert.equal(validateFormalRelease(published, page, locale).release.deviceAcceptance.status, 'not_run');
  assert.throws(() => validateFormalRelease({ ...published,
    httpVerification: { status: 'not_run', evidenceSha256: null } }, page, locale));
});
