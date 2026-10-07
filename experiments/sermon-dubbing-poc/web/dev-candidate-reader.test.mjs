import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { loadPublishedWeeks, validateDevCandidateRelease, validatePublishedRelease } from './published-weeks.mjs';
import { buildCatalogNavigation, validateCatalog, downloadFilename } from './catalog.mjs';

const metadata = JSON.parse(await readFile(new URL('../../../apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/dev-candidate-catalog-readback.json', import.meta.url)));
const clone = value => structuredClone(value);
const hash = value => createHash('sha256').update(value).digest('hex');
const pageId = 'if-i-had-more-time-jesus-is-worthy';
function fixture(mutate = () => {}) {
  const page = clone(metadata.catalog.pages.find(page => page.id === pageId));
  const files = new Map(), requests = [];
  for (const locale of ['zh-Hans', 'ko', 'es']) {
    const release = clone(metadata.releases[locale]);
    const content = {
      schemaVersion: locale === 'zh-Hans' ? 'sermon-formal-dev-content-v1' : 'sermon-dev-podcast-candidate-content-v2',
      pageId, locale, sourceLocale: 'en', englishSourcePackageJsonSha256: page.sourceIdentitySha256,
      targetLanguageCandidateJsonSha256: release.targetLanguageCandidateJsonSha256,
      targetLanguageAudioPackageJsonSha256: release.targetLanguageAudioPackageJsonSha256,
      contentStatus: release.contentStatus, audioStatus: release.audioStatus, date: page.date,
      title: 'Synthetic candidate', speaker: 'Two speakers', series: 'Synthetic series', scripture: 'Synthetic reference',
      summary: 'Synthetic summary', durationSeconds: 10, outline: [{ title: 'Point', body: 'Body' }],
      cues: [{ textGroupId: 'u1', sourceUnitIds: ['u1'], start: 0, end: 9, text: `Synthetic ${locale}` }],
    };
    const captions = {
      schemaVersion: 'sermon-target-language-captions-v1', pageId, locale,
      audioPackageJsonSha256: release.targetLanguageAudioPackageJsonSha256,
      timingBasis: 'concatenated target audio; natural unit durations; no source-video synchronization',
      cues: clone(content.cues),
    };
    mutate({ release, content, captions, locale, page });
    for (const [role, value] of [['content', content], ['captions', captions]]) {
      const asset = release.assets.find(asset => asset.role === role), body = JSON.stringify(value);
      files.set(asset.path, body); asset.sha256 = hash(body);
    }
    const target = page.targets[locale], body = JSON.stringify(release);
    files.set(target.releasePackageUrl, body);
    target.releasePackageJsonSha256 = hash(body);
  }
  files.set('/multilingual-v3.json', JSON.stringify({ ...metadata.catalog, pages: [page], defaultPageId: page.id }));
  return { files, page, requests, fetchImpl: async path => {
    requests.push(path);
    return files.has(path) ? new Response(files.get(path)) : new Response('', { status: 404 });
  } };
}

test('frozen public candidate metadata requires explicit Dev release admission with review states intact', () => {
  const page = metadata.catalog.pages[1];
  for (const locale of ['zh-Hans', 'ko', 'es']) {
    const release = metadata.releases[locale];
    assert.throws(() => validatePublishedRelease(release, page, locale));
    const assets = validateDevCandidateRelease(release, page, locale);
    assert.equal(assets.audio.path, `/media/${pageId}/${locale}.wav`);
    assert.equal(release.contentStatus, locale === 'zh-Hans' ? 'human_reviewed' : 'machine_reviewed');
    assert.equal(release.status, 'candidate');
  }
});

test('Dev candidate loader exposes three separate locales as diagnostics without human or publication promotion', async () => {
  const result = await loadPublishedWeeks(fixture().fetchImpl, { allowDevCandidates: true });
  assert.deepEqual(result.errors, []);
  const week = result.weeks[0];
  assert.equal(week.diagnosticOnly, true);
  assert.equal(week.releaseStatus, 'candidate');
  assert.deepEqual(Object.keys(week.contentVariants), ['zh-Hans', 'ko', 'es']);
  for (const [locale, variant] of Object.entries(week.contentVariants)) {
    assert.equal(variant.contentStatus, locale === 'zh-Hans' ? 'human_reviewed' : 'machine_reviewed');
    assert.equal(variant.humanContentReview, locale === 'zh-Hans' ? 'approved' : 'pending');
    assert.equal(variant.tracks[0].subtitleTiming, 'target_audio_clock');
    assert.equal(variant.tracks[0].scope, 'full_candidate');
    assert.ok(!variant.productionStages.every(stage => stage.status === 'pass'));
    assert.ok(!variant.contentReview.includes('豁免'));
  }
  const navigation = buildCatalogNavigation({ schemaVersion: 'sermon-weekly-catalog-v1', defaultWeekId: week.id, weeks: result.weeks }, { environment: 'development' });
  assert.equal(navigation.groups.find(group => group.id === 'diagnostics').items.length, 1);
  assert.match(downloadFilename(week, week.tracks[0]), /\.wav$/);
  const catalog = { schemaVersion: 'sermon-weekly-catalog-v1', weeks: [week], defaultWeekId: week.id };
  assert.throws(() => validateCatalog({ ...catalog, weeks: [{ ...week, devCandidate: false }] }), /Invalid track/);
});

test('Production does not fetch machine releases and rejects the human candidate package before content fetch', async () => {
  const f = fixture(), result = await loadPublishedWeeks(f.fetchImpl);
  assert.deepEqual(result.weeks, []);
  assert.ok(!f.requests.includes(`/releases-v2/${pageId}/ko.json`));
  assert.ok(!f.requests.includes(`/releases-v2/${pageId}/es.json`));
  assert.ok(f.requests.includes(`/releases-v2/${pageId}/zh-Hans.json`));
  assert.ok(!f.requests.includes(`/content/${pageId}/zh-Hans.json`));
});

test('machine receipt, acceptance and caption binding failures reject only the affected Dev locale', async () => {
  const changes = [
    ({ release }) => { delete release.audioHumanReviewReceiptJsonSha256; },
    ({ release }) => { release.deviceAcceptance = { status: 'pass', evidenceSha256: 'a'.repeat(64) }; },
    ({ release }) => { release.assets.find(asset => asset.role === 'audio').path = `/media/${pageId}/es.wav`; },
    ({ captions }) => { captions.audioPackageJsonSha256 = 'a'.repeat(64); },
    ({ content }) => { content.contentStatus = 'human_reviewed'; },
    ({ content }) => { content.englishSourcePackageJsonSha256 = 'a'.repeat(64); },
  ];
  for (const change of changes) {
    const f = fixture(args => { if (args.locale === 'ko') change(args); });
    const result = await loadPublishedWeeks(f.fetchImpl, { allowDevCandidates: true });
    assert.deepEqual(Object.keys(result.weeks[0].contentVariants), ['zh-Hans', 'es']);
    assert.equal(result.errors.length, 1);
  }
});

test('explicit development page flags are filtered before release requests', async () => {
  const f = fixture();
  const catalog = JSON.parse(f.files.get('/multilingual-v3.json'));
  catalog.pages[0].diagnosticOnly = true;
  f.files.set('/multilingual-v3.json', JSON.stringify(catalog));
  assert.deepEqual((await loadPublishedWeeks(f.fetchImpl)).weeks, []);
  assert.deepEqual(f.requests, ['/multilingual-v4.json', '/multilingual-v3.json']);
});

const frozenRoot = process.env.TONGXING_DEV_CATALOG_FIXTURE_ROOT;
test('full frozen real three-locale candidate assets pass current reader hash and binding checks offline', { skip: !frozenRoot }, async () => {
  const requests = [];
  const fetchImpl = async path => {
    requests.push(path);
    try { return new Response(await readFile(`${frozenRoot}${path}`)); }
    catch (error) { if (error.code === 'ENOENT') return new Response('', { status: 404 }); throw error; }
  };
  const dev = await loadPublishedWeeks(fetchImpl, { allowDevCandidates: true });
  assert.deepEqual(dev.errors, []);
  const candidate = dev.weeks.find(week => week.id === pageId);
  assert.ok(candidate);
  assert.deepEqual(Object.keys(candidate.contentVariants), ['zh-Hans', 'ko', 'es']);
  for (const [locale, variant] of Object.entries(candidate.contentVariants)) {
    assert.equal(variant.fullTranscript.length, 839);
    assert.equal(variant.tracks[0].cues.length, 839);
    assert.equal(variant.contentStatus, metadata.releases[locale].contentStatus);
  }
  assert.ok(!requests.some(path => /\.(wav|mp3|m4a)$/.test(path)), 'no audio download or playback in this test');
  const production = await loadPublishedWeeks(fetchImpl);
  assert.ok(!production.weeks.some(week => week.id === pageId));
  assert.ok(production.weeks.some(week => week.id === metadata.catalog.defaultPageId));
});
