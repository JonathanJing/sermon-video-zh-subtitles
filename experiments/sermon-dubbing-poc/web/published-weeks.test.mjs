import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { loadPublishedWeeks } from './published-weeks.mjs';

const hash = value => createHash('sha256').update(value).digest('hex');
const pageId = '2026-09-27-weekend-sermon-drive-530';
function fixture(mutate = () => {}) {
  const files = new Map(), requests = [];
  const page = {
    id: pageId, title: 'Synthetic published page', date: '2026-09-27', sourceLocale: 'en', defaultTargetLocale: 'zh-Hans',
    sourceIdentitySha256: 'a'.repeat(64), targets: {},
  };
  for (const locale of ['zh-Hans', 'ko', 'es']) {
    const content = {
      schemaVersion: 'sermon-full-video-text-content-v1', pageId, targetLocale: locale, sourceLocale: 'en',
      status: 'human_reviewed', audioStatus: 'unavailable', englishSourcePackageJsonSha256: page.sourceIdentitySha256,
      targetLanguageCandidateJsonSha256: 'b'.repeat(64), title: `Title ${locale}`, speaker: 'Eric Geiger',
      series: 'Series', scripture: 'Revelation 4–5', summary: `Summary ${locale}`, outline: ['Point one'],
      sourceMediaSha256: 'd'.repeat(64), durationSeconds: 10, sourceVideoUrl: `/pages/${pageId}/full-video-browser.mp4`,
      cues: [{ textGroupId: 'first', sourceUnitIds: ['u1','u2'], start: 0, end: 8, text: `Full reading text ${locale}` }],
    };
    const captions = { cues: [{ textGroupId: 'first', start: .5, end: 7, text: `Short spoken text ${locale}` }] };
    const release = {
      schemaVersion: 'sermon-target-language-release-package-v2', pageId, packageId: `${pageId}-${locale}`,
      interfaceLocale: locale, spokenTargetLanguageCandidateJsonSha256: 'e'.repeat(64),
      targetLanguageAudioPackageJsonSha256: 'f'.repeat(64), issues: [],
      deviceAcceptance: { status: 'not_run', evidenceSha256: null },
      venueAcceptance: { status: 'not_run', evidenceSha256: null },
      targetLocale: locale, audioLocale: locale, contentLocale: locale, sourceLocale: 'en',
      status: 'published_http_verified', httpVerification: { status: 'pass', evidenceSha256: '1'.repeat(64) },
      audioStatus: 'human_reviewed', contentStatus: 'human_reviewed',
      targetLanguageCandidateJsonSha256: content.targetLanguageCandidateJsonSha256,
      assets: [
        { role: 'content', path: `/content/${pageId}/${locale}.json` },
        { role: 'captions', path: `/captions/${pageId}/${locale}.json` },
        { role: 'audio', path: `/media/${pageId}/${locale}.mp3`, sha256: 'c'.repeat(64) },
        { role: 'page', path: `/pages/${pageId}/${locale}/index.html`, sha256: '2'.repeat(64) },
      ],
    };
    mutate({ content, captions, release, locale });
    for (const [role, data] of [['content', content], ['captions', captions]]) {
      const asset = release.assets.find(item => item.role === role);
      const body = JSON.stringify(data);
      files.set(asset.path, body); asset.sha256 = hash(body);
    }
    const releasePath = `/releases-v2/${pageId}/${locale}.json`;
    const body = JSON.stringify(release); files.set(releasePath, body);
    page.targets[locale] = {
      releasePackageUrl: releasePath, releasePackageJsonSha256: hash(body),
      contentStatus: 'human_reviewed', audioStatus: 'human_reviewed', capabilities: ['text', 'captions', 'audio'],
    };
  }
  files.set('/multilingual-v3.json', JSON.stringify({ schemaVersion: 'sermon-multilingual-catalog-v3', generatedAt: '2026-09-30T00:00:00Z', defaultPageId: pageId, pages: [page] }));
  const fetchImpl = async path => {
    requests.push(path);
    return files.has(path) ? new Response(files.get(path)) : new Response('', { status: 404 });
  };
  return { files, requests, fetchImpl };
}

test('published three-language tracks work inside the legacy week shape without mixing reading text and spoken captions', async () => {
  const f = fixture();
  const result = await loadPublishedWeeks(f.fetchImpl);
  assert.deepEqual(result.errors, []);
  assert.equal(result.defaultWeekId, pageId);
  const [week] = result.weeks;
  assert.equal(week.title, 'Title zh-Hans');
  assert.equal(week.releaseLabel, '正式播放版');
  assert.equal(week.audioStatus, 'full_reviewed');
  assert.deepEqual(Object.keys(week.contentVariants), ['zh-Hans', 'ko', 'es']);
  for (const [locale, variant] of Object.entries(week.contentVariants)) {
    assert.equal(variant.targetLocale, locale);
    assert.equal(variant.defaultTargetLocale, locale);
    assert.equal(variant.number, '');
    assert.ok(variant.audioNotice.length > 0);
    assert.ok(variant.contentReview.length > 0);
    assert.equal(variant.productionStages.length, 3);
    assert.ok(variant.productionStages.every(stage => stage.status === 'pass' && !/视频同步|人工试听/.test(stage.label)));
    assert.equal(variant.tracks[0].audioUrl, `/media/${pageId}/${locale}.mp3`);
    assert.equal(variant.tracks[0].cues[0].text, `Short spoken text ${locale}`);
    assert.equal(variant.fullTranscript[0].text, `Full reading text ${locale}`);
    assert.equal(variant.tracks[0].scope, 'full_reviewed');
    assert.equal(variant.sourceStartSeconds, 0);
    assert.equal(variant.fingerprint, undefined);
  }
  assert.ok(!f.requests.some(path => /\.mp3$/.test(path)), 'runtime never predownloads audio for validation');
});

test('tampered caption bytes reject only that locale', async () => {
  const f = fixture();
  f.files.set(`/captions/${pageId}/ko.json`, '{"cues":[]}');
  const result = await loadPublishedWeeks(f.fetchImpl);
  assert.deepEqual(Object.keys(result.weeks[0].contentVariants), ['zh-Hans', 'es']);
  assert.match(result.errors[0], /hash mismatch/);
});

test('release hashes are verified before their content is read', async () => {
  const f = fixture();
  f.files.set(`/releases-v2/${pageId}/es.json`, '{}');
  const result = await loadPublishedWeeks(f.fetchImpl);
  assert.equal(result.weeks[0].contentVariants.es, undefined);
  assert.ok(!f.requests.includes(`/content/${pageId}/es.json`));
});

test('wrong identity, unreviewed release, unsafe assets and mismatched caption groups never become selectable', async () => {
  const mutations = [
    ({ release }) => { release.targetLocale = 'wrong'; },
    ({ release }) => { release.audioStatus = 'candidate'; },
    ({ release }) => { release.assets[2].path = 'https://other.test/audio.mp3'; },
    ({ release }) => { release.assets[2].path = `/media/${pageId}/../secret.mp3`; },
    ({ content }) => { content.englishSourcePackageJsonSha256 = 'd'.repeat(64); },
    ({ content }) => { content.sourceVideoUrl = '//other.test/video.mp4'; },
    ({ captions }) => { captions.cues[0].textGroupId = 'other'; },
    ({ captions }) => { captions.cues[0].end = 15; },
  ];
  for (const mutate of mutations) {
    const result = await loadPublishedWeeks(fixture(mutate).fetchImpl);
    assert.deepEqual(result.weeks, []);
    assert.equal(result.errors.length, 3);
  }
});

test('missing contract evidence rejects only the affected locale after release hash verification', async () => {
  const changes = [
    release => { delete release.spokenTargetLanguageCandidateJsonSha256; },
    release => { delete release.targetLanguageAudioPackageJsonSha256; },
    release => { release.assets = release.assets.filter(asset => asset.role !== 'page'); },
    release => { release.httpVerification.evidenceSha256 = null; },
    release => { release.deviceAcceptance = { status: 'pass', evidenceSha256: null }; },
  ];
  for (const change of changes) {
    const f = fixture(({ release, locale }) => { if (locale === 'ko') change(release); });
    const result = await loadPublishedWeeks(f.fetchImpl);
    assert.deepEqual(Object.keys(result.weeks[0].contentVariants), ['zh-Hans', 'es']);
    assert.equal(result.errors.length, 1);
    assert.ok(!f.requests.includes(`/content/${pageId}/ko.json`));
  }
});

test('optional missing or unavailable catalog keeps the legacy app usable', async () => {
  assert.deepEqual(await loadPublishedWeeks(async () => new Response('', { status: 404 })), { weeks: [], defaultWeekId: null, errors: [] });
  const failed = await loadPublishedWeeks(async () => { throw new Error('offline'); });
  assert.deepEqual(failed.weeks, []);
  // The v4 probe failure is recorded before the v3 fallback is attempted.
  assert.deepEqual(failed.errors, ['Catalog v4 unavailable, using v3: offline', 'offline']);
});

test('missing Chinese release falls back to an actually available default locale', async () => {
  const f = fixture();
  f.files.delete(`/releases-v2/${pageId}/zh-Hans.json`);
  const result = await loadPublishedWeeks(f.fetchImpl);
  assert.equal(result.weeks[0].defaultTargetLocale, 'ko');
  assert.equal(result.weeks[0].targetLocale, 'ko');
  assert.equal(result.weeks[0].tracks[0].targetLocale, 'ko');
});

test('optional requests have a bounded timeout and abort pending network work', async () => {
  let signal;
  const result = await loadPublishedWeeks(async (_path, options) => {
    signal = options.signal;
    return new Promise(() => {});
  }, { requestTimeoutMs: 5 });
  assert.deepEqual(result.weeks, []);
  assert.match(result.errors[0], /timed out/);
  assert.equal(signal.aborted, true);
});

function addHistory(f, count) {
  const catalog = JSON.parse(f.files.get('/multilingual-v3.json'));
  const template = [...f.files].filter(([path]) => path !== '/multilingual-v3.json');
  for (let index = 1; index < count; index++) {
    const id = `history-${index}`;
    const page = structuredClone(catalog.pages[0]);
    page.id = id;
    page.date = `2025-01-${String(index % 28 + 1).padStart(2, '0')}`;
    for (const [path, body] of template) {
      if (path.includes('/releases-v2/')) continue;
      f.files.set(path.replaceAll(pageId, id), body.replaceAll(pageId, id));
    }
    for (const locale of ['zh-Hans', 'ko', 'es']) {
      const releasePath = `/releases-v2/${id}/${locale}.json`;
      const release = JSON.parse(f.files.get(`/releases-v2/${pageId}/${locale}.json`).replaceAll(pageId, id));
      for (const role of ['content', 'captions']) {
        const asset = release.assets.find(item => item.role === role);
        asset.sha256 = hash(f.files.get(asset.path));
      }
      const body = JSON.stringify(release);
      f.files.set(releasePath, body);
      page.targets[locale].releasePackageUrl = releasePath;
      page.targets[locale].releasePackageJsonSha256 = hash(body);
    }
    catalog.pages.push(page);
  }
  f.files.set('/multilingual-v3.json', JSON.stringify(catalog));
}

function checkpoint() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

// Advance the deadline only after healthy async hashing/reads settle. Real
// wall-clock deadlines race CI load and can incorrectly reject healthy pages.
const settleReads = () => new Promise(resolve => setImmediate(resolve));

test('current page loads first and slow archive pages cannot hold the player indefinitely', { timeout: 10000 }, async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const currentRead = checkpoint(), archiveStalled = checkpoint();
  const f = fixture();
  addHistory(f, 104);
  let active = 0, peak = 0;
  const pendingSignals = [];
  const fetchImpl = (path, options) => {
    if (path.startsWith('/alignment/history-')) {
      active++;
      peak = Math.max(peak, active);
      pendingSignals.push(options.signal);
      if (pendingSignals.length === 12) archiveStalled.resolve();
      options.signal.addEventListener('abort', () => { active--; }, { once: true });
      return new Promise(() => {});
    }
    if (path === `/english-reference/${pageId}.json`) currentRead.resolve();
    return f.fetchImpl(path, options);
  };
  const loading = loadPublishedWeeks(fetchImpl, { requestTimeoutMs: 1000, pageLoadTimeoutMs: 50 });
  await Promise.all([currentRead.promise, archiveStalled.promise]);
  await settleReads();
  assert.ok(pendingSignals.every(signal => !signal.aborted));
  t.mock.timers.tick(50);
  const result = await loading;
  assert.equal(result.defaultWeekId, pageId);
  assert.ok(result.weeks.some(week => week.id === pageId));
  assert.ok(f.requests.indexOf(`/releases-v2/${pageId}/zh-Hans.json`) < f.requests.findIndex(path => path.startsWith('/releases-v2/history-')));
  assert.ok(peak > 1 && peak <= 12, `expected bounded history concurrency, saw ${peak}`);
  assert.ok(pendingSignals.every(signal => signal.aborted));
  assert.ok(result.errors.some(error => /loading timed out/.test(error)));
});

test('healthy archive pages load while the current-page sidecar is stalled', { timeout: 10000 }, async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const currentStalled = checkpoint(), archiveRead = checkpoint();
  let archiveReferences = 0;
  const f = fixture();
  addHistory(f, 3);
  let stalledSignal;
  let defaultAborted = false;
  let historyRequestedBeforeAbort = false;
  const fetchImpl = (path, options) => {
    if (path === `/alignment/${pageId}.json`) {
      stalledSignal = options.signal;
      currentStalled.resolve();
      stalledSignal.addEventListener('abort', () => { defaultAborted = true; }, { once: true });
      return new Promise(() => {});
    }
    if (path.startsWith('/releases-v2/history-')) {
      historyRequestedBeforeAbort ||= !defaultAborted;
    }
    if (path.startsWith('/english-reference/history-') && ++archiveReferences === 2) archiveRead.resolve();
    return f.fetchImpl(path, options);
  };
  const loading = loadPublishedWeeks(fetchImpl, { requestTimeoutMs: 1000, pageLoadTimeoutMs: 50 });
  await Promise.all([currentStalled.promise, archiveRead.promise]);
  await settleReads();
  assert.equal(stalledSignal.aborted, false);
  t.mock.timers.tick(50);
  const result = await loading;
  assert.equal(result.weeks.length, 3);
  assert.equal(result.defaultWeekId, pageId);
  assert.equal(historyRequestedBeforeAbort, true);
  assert.equal(stalledSignal.aborted, true);
});

test('healthy archive remains selectable when current-page release assets stall', { timeout: 10000 }, async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const currentStalled = checkpoint(), archiveRead = checkpoint();
  let archiveReferences = 0;
  const f = fixture();
  addHistory(f, 3);
  const stalledSignals = [];
  const fetchImpl = (path, options) => {
    if (path.startsWith(`/releases-v2/${pageId}/`)) {
      stalledSignals.push(options.signal);
      if (stalledSignals.length === 3) currentStalled.resolve();
      return new Promise(() => {});
    }
    if (path.startsWith('/english-reference/history-') && ++archiveReferences === 2) archiveRead.resolve();
    return f.fetchImpl(path, options);
  };
  const loading = loadPublishedWeeks(fetchImpl, { requestTimeoutMs: 1000, pageLoadTimeoutMs: 50 });
  await Promise.all([currentStalled.promise, archiveRead.promise]);
  await settleReads();
  assert.ok(stalledSignals.every(signal => !signal.aborted));
  t.mock.timers.tick(50);
  const result = await loading;
  assert.equal(result.weeks.length, 2);
  assert.ok(result.weeks.every(week => week.id.startsWith('history-')));
  assert.ok(result.defaultWeekId.startsWith('history-'));
  assert.ok(stalledSignals.every(signal => signal.aborted));
});

test('all 104 published pages remain available when archive endpoints respond', async () => {
  const f = fixture();
  addHistory(f, 104);
  const result = await loadPublishedWeeks(f.fetchImpl);
  assert.equal(result.weeks.length, 104);
  assert.equal(result.defaultWeekId, pageId);
  assert.deepEqual(result.errors, []);
});

function addAlignment(f, mutate = () => {}) {
  const catalog = JSON.parse(f.files.get('/multilingual-v3.json')), page = catalog.pages[0];
  const targets = Object.fromEntries(Object.entries(page.targets).map(([locale, target]) => [locale, {
    releasePackageJsonSha256: target.releasePackageJsonSha256,
    audioFingerprint: {schemaVersion:'sermon-audio-fingerprint-binding-v1', algorithmVersion:'spectral-landmarks-v1',
      pageId, sourceSha256:'d'.repeat(64), trackSha256:'c'.repeat(64), indexSha256:'e'.repeat(64),
      sourceStartSeconds:0, sourceEndSeconds:10, captureSeconds:10,
      indexUrl:`/fingerprints/${'e'.repeat(16)}-landmarks.json`},
  }]));
  const sidecar={schemaVersion:'sermon-published-alignment-v1',pageId,sourceIdentitySha256:page.sourceIdentitySha256,targets};
  mutate(sidecar);
  f.files.set(`/alignment/${pageId}.json`,JSON.stringify(sidecar));
}
test('published listening alignment binds each locale to its reviewed source and audio', async () => {
  const f=fixture(); addAlignment(f);
  const result=await loadPublishedWeeks(f.fetchImpl);
  assert.deepEqual(result.errors,[]);
  for (const v of Object.values(result.weeks[0].contentVariants)) {
    assert.equal(v.audioFingerprint.trackSha256,v.tracks[0].sha256);
    assert.equal(v.audioFingerprint.sourceSha256,v.sourceSha256);
    assert.equal(v.automaticAudioAlignment.status,'ready');
  }
});
test('stale track, source, release and window bindings disable alignment without losing playback', async () => {
  for (const change of [m=>m.trackSha256='f'.repeat(64),m=>m.sourceSha256='f'.repeat(64),m=>m.sourceEndSeconds=11,m=>m.indexUrl='/wrong.json']) {
    const f=fixture();addAlignment(f,s=>change(s.targets.ko.audioFingerprint));
    const result=await loadPublishedWeeks(f.fetchImpl);
    assert.equal(result.weeks[0].contentVariants.ko.audioFingerprint,undefined);
    assert.ok(result.weeks[0].contentVariants['zh-Hans'].audioFingerprint);
    assert.equal(result.weeks[0].contentVariants.ko.tracks.length,1);
    assert.equal(result.errors.length,1);
  }
  const f=fixture();addAlignment(f,s=>s.targets.es.releasePackageJsonSha256='f'.repeat(64));
  const result=await loadPublishedWeeks(f.fetchImpl);
  assert.equal(result.weeks[0].contentVariants.es.audioFingerprint,undefined);
  assert.equal(result.weeks[0].contentVariants.es.tracks.length,1);
});

function addEnglishReference(f, mutate = () => {}) {
  const page=JSON.parse(f.files.get('/multilingual-v3.json')).pages[0];
  const targets=Object.fromEntries(Object.entries(page.targets).map(([locale,target])=>{
    const release=JSON.parse(f.files.get(target.releasePackageUrl));
    return [locale,{releasePackageJsonSha256:target.releasePackageJsonSha256,
      contentSha256:release.assets.find(a=>a.role==='content').sha256,
      captionsSha256:release.assets.find(a=>a.role==='captions').sha256,
      blocks:[{textGroupId:'first',sourceUnitIds:['u1','u2'],english:'Complete first unit. Complete second unit.'}]}];
  }));
  const reference={schemaVersion:'sermon-published-english-reference-v1',pageId,
    sourceIdentitySha256:page.sourceIdentitySha256,sourceMediaSha256:'d'.repeat(64),reviewState:'human_approved',targets};
  mutate(reference);
  f.files.set(`/english-reference/${pageId}.json`,JSON.stringify(reference));
}
test('approved English maps merged source units to both full text and spoken captions in every locale',async()=>{
  const f=fixture();addEnglishReference(f);
  const result=await loadPublishedWeeks(f.fetchImpl);
  assert.deepEqual(result.errors,[]);
  for(const variant of Object.values(result.weeks[0].contentVariants)) {
    assert.equal(variant.fullTranscript[0].english,'Complete first unit. Complete second unit.');
    assert.equal(variant.tracks[0].cues[0].blockId,'first');
    assert.equal(variant.transcript.blocks[0].blockId,'first');
    assert.equal(variant.transcript.blocks[0].reviewState,'human_approved');
  }
});
test('changed English source, release hashes or unit associations cannot show wrong reference text',async()=>{
  for(const mutate of [s=>s.sourceIdentitySha256='f'.repeat(64),s=>s.targets.ko.contentSha256='f'.repeat(64),
    s=>s.targets.ko.blocks[0].sourceUnitIds=['u2','u1'],s=>s.targets.ko.blocks[0].textGroupId='wrong']) {
    const f=fixture();addEnglishReference(f,mutate);
    const result=await loadPublishedWeeks(f.fetchImpl);
    assert.equal(result.weeks[0].contentVariants.ko.transcript,undefined);
    assert.equal(result.weeks[0].contentVariants.ko.tracks.length,1);
    assert.ok(result.errors.length);
  }
});

test('invalid catalog target is rejected before release fetch while valid locales remain', async () => {
  const mutations = [
    target => { target.releasePackageUrl = '/releases-v2/wrong-page/ko.json'; },
    target => { target.capabilities.push('audio'); },
    target => { target.capabilities.push('unknown'); },
    target => { target.capabilities.push('alignment'); },
  ];
  for (const mutate of mutations) {
    const f = fixture();
    const catalog = JSON.parse(f.files.get('/multilingual-v3.json'));
    const target = catalog.pages[0].targets.ko;
    const original = target.releasePackageUrl;
    mutate(target);
    // The wrong path still serves matching release bytes and a correct hash;
    // rejection must be from catalog admission, not a later transport failure.
    f.files.set(target.releasePackageUrl, f.files.get(original));
    f.files.set('/multilingual-v3.json', JSON.stringify(catalog));
    const result = await loadPublishedWeeks(f.fetchImpl);
    assert.deepEqual(Object.keys(result.weeks[0].contentVariants), ['zh-Hans', 'es']);
    assert.ok(!f.requests.includes(target.releasePackageUrl));
    assert.equal(result.errors.length, 1);
  }
});

test('valid text-only catalog target never requests a release or becomes an audio fallback', async () => {
  const f = fixture();
  const catalog = JSON.parse(f.files.get('/multilingual-v3.json'));
  Object.assign(catalog.pages[0].targets['zh-Hans'], { audioStatus: 'unavailable', capabilities: ['text'] });
  f.files.set('/multilingual-v3.json', JSON.stringify(catalog));
  const result = await loadPublishedWeeks(f.fetchImpl);
  assert.deepEqual(Object.keys(result.weeks[0].contentVariants), ['ko', 'es']);
  assert.equal(result.weeks[0].defaultTargetLocale, 'ko');
  assert.ok(!f.requests.includes(`/releases-v2/${pageId}/zh-Hans.json`));
  assert.match(result.errors[0], /not ready for playback/);
});

for (const [name, mutate] of [
  ['missing default page', c => { c.defaultPageId = 'missing'; }],
  ['duplicate page identity', c => { c.pages.push(structuredClone(c.pages[0])); }],
  ['impossible calendar date', c => { c.pages[0].date = '2026-02-30'; }],
  ['missing title', c => { delete c.pages[0].title; }],
  ['missing default locale', c => { c.pages[0].defaultTargetLocale = 'vi'; }],
  ['bad source media hash', c => { c.pages[0].sourceMediaSha256 = 'bad'; }],
]) {
  test(`catalog metadata admission rejects ${name} before asset requests`, async () => {
    const f = fixture();
    const catalog = JSON.parse(f.files.get('/multilingual-v3.json'));
    mutate(catalog);
    f.files.set('/multilingual-v3.json', JSON.stringify(catalog));
    const result = await loadPublishedWeeks(f.fetchImpl);
    assert.deepEqual(result.weeks, []);
    assert.ok(result.errors.length);
    assert.deepEqual(f.requests, ['/multilingual-v4.json', '/multilingual-v3.json']);
  });
}

test('bad page metadata does not hide a different valid page or request bad-page assets', async () => {
  const f = fixture();
  addHistory(f, 2);
  const catalog = JSON.parse(f.files.get('/multilingual-v3.json'));
  catalog.pages[0].title = '';
  f.files.set('/multilingual-v3.json', JSON.stringify(catalog));
  const result = await loadPublishedWeeks(f.fetchImpl);
  assert.deepEqual(result.weeks.map(week => week.id), ['history-1']);
  assert.equal(result.defaultWeekId, 'history-1');
  assert.deepEqual(result.errors, ['Invalid published page']);
  assert.ok(!f.requests.some(path => path.includes(pageId)));
});

test('original source window metadata cannot replace playback clip duration or hash', async () => {
 const good=fixture(({content})=>{content.sourceWindow={schemaVersion:'sermon-original-recording-window-v1',startSeconds:2015.321,endSeconds:2025.321,mediaSha256:content.sourceMediaSha256};});
 const result=await loadPublishedWeeks(good.fetchImpl);assert.equal(result.weeks.length,1);assert.equal(result.weeks[0].sourceStartSeconds,0);assert.equal(result.weeks[0].sourceFingerprintWindow.startSeconds,2015.321);
 for(const mutate of [w=>w.mediaSha256='e'.repeat(64),w=>w.endSeconds=2026.321]){const f=fixture(({content})=>{content.sourceWindow={schemaVersion:'sermon-original-recording-window-v1',startSeconds:2015.321,endSeconds:2025.321,mediaSha256:content.sourceMediaSha256};mutate(content.sourceWindow);});assert.equal((await loadPublishedWeeks(f.fetchImpl)).weeks.length,0);}
});

function studyFixture(mutate) {
  const f = fixture(mutate);
  const catalog = JSON.parse(f.files.get('/multilingual-v3.json'));
  for (const locale of ['zh-Hans','ko','es']) bindStudy(f, catalog.pages[0], locale);
  f.files.set('/multilingual-v3.json',JSON.stringify(catalog));
  return f;
}

// Adds the four-product study binding to one locale's release (v3, or an existing v4).
function bindStudy(f, page, locale) {
  const stable = value => Array.isArray(value) ? value.map(stable)
    : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key,stable(value[key])])) : value;
  const canonicalHash = value => hash(JSON.stringify(stable(value)));
  const path = page.targets[locale].releasePackageUrl;
  const release = JSON.parse(f.files.get(path));
  if (release.schemaVersion !== 'sermon-target-language-release-package-v4') release.schemaVersion = 'sermon-target-language-release-package-v3';
  release.englishSourcePackageJsonSha256 = page.sourceIdentitySha256;
  release.sourceIdentity = {sourceId:'synthetic-source',sourceUrlHash:'9'.repeat(64),mediaSha256:'d'.repeat(64),durationSeconds:10,
    window:{startSeconds:0,endSeconds:10,approvalReceiptSha256:'8'.repeat(64)}};
  const products = {sourcePackageSha256:page.sourceIdentitySha256,textCandidateSha256:release.targetLanguageCandidateJsonSha256,
    audioPackageSha256:release.targetLanguageAudioPackageJsonSha256,outlineReviewSha256:'3'.repeat(64),meditationReviewSha256:'4'.repeat(64),
    metadataApprovalSha256:'5'.repeat(64),contentSha256:release.assets.find(row=>row.role==='content').sha256};
  for (const kind of ['outline','meditation']) {
    const artifact = {schemaVersion:'sermon-study-artifact-v1',kind,pageId,locale,sourcePackageSha256:products.sourcePackageSha256,
      textCandidateSha256:products.textCandidateSha256,producerIdentity:'synthetic-study-v1',
      sections:[{title:`Reviewed ${kind} ${locale}`,body:`Complete ${kind} sentence.\nLast sentence ${locale}.`,sourceUnitIds:['u1']}]};
    const asset = {role:kind,path:`/study/${pageId}/${locale}/${kind}.json`,sha256:hash(JSON.stringify(artifact))};
    f.files.set(asset.path,JSON.stringify(artifact));release.assets.push(asset);products[kind+'ArtifactSha256']=canonicalHash(artifact);
  }
  const joined = canonicalHash({source:products.sourcePackageSha256,products:{text:products.textCandidateSha256,audio:products.audioPackageSha256,
    outline:{status:'human_reviewed',artifactSha256:products.outlineArtifactSha256,reviewSha256:products.outlineReviewSha256},
    meditation:{status:'human_reviewed',artifactSha256:products.meditationArtifactSha256,reviewSha256:products.meditationReviewSha256}}});
  products.candidateSha256=canonicalHash({products:joined,metadataApproval:products.metadataApprovalSha256,contentSha256:products.contentSha256});
  release.fourProducts=products;
  const manifest={schemaVersion:'sermon-public-app-products-v1',pageId,locale,sourceIdentity:release.sourceIdentity,fourProducts:products};
  const manifestPath=`/study/${pageId}/${locale}/products.json`;
  f.files.set(manifestPath,JSON.stringify(manifest));release.assets.push({role:'product_manifest',path:manifestPath,sha256:hash(JSON.stringify(manifest))});
  f.files.set(path,JSON.stringify(release));page.targets[locale].releasePackageJsonSha256=hash(JSON.stringify(release));
}

test('v3 three-language release loads full independent study and never substitutes legacy metadata outline', async () => {
  const f=studyFixture();const result=await loadPublishedWeeks(f.fetchImpl);
  assert.equal(result.weeks.length,1);assert.deepEqual(result.errors,[]);
  for(const locale of ['zh-Hans','ko','es']) {
    const view=result.weeks[0].contentVariants[locale];
    assert.equal(view.outline[0].title,`Reviewed outline ${locale}`);
    assert.deepEqual(view.outline[0].points,[`Complete outline sentence.\nLast sentence ${locale}.`]);
    assert.equal(view.meditation[0].body,`Complete meditation sentence.\nLast sentence ${locale}.`);
    assert.equal(view.studyStatus,'human_reviewed');
    assert.ok(view.studyArtifacts.outline && view.studyArtifacts.meditation);
  }
});

test('changed or missing study bytes isolate the affected locale and legacy v2 never gains study status', async () => {
  for (const change of ['tamper','missing']) {
    const f=studyFixture();const path=`/study/${pageId}/ko/meditation.json`;
    if(change==='tamper')f.files.set(path,'{}');else f.files.delete(path);
    const result=await loadPublishedWeeks(f.fetchImpl);
    assert.deepEqual(Object.keys(result.weeks[0].contentVariants).sort(),['es','zh-Hans']);
    assert.ok(result.errors.some(error=>error.includes('/ko:')));
  }
  const old=await loadPublishedWeeks(fixture().fetchImpl);
  assert.equal(old.weeks[0].studyStatus,'unavailable');
  assert.deepEqual(old.weeks[0].meditation,[]);
});

test('simulated review page is excluded from production and visibly labelled in Dev', async () => {
  const f = fixture();
  const catalog = JSON.parse(f.files.get('/multilingual-v3.json'));
  catalog.pages[0].simulationOnly = true;
  for (const target of Object.values(catalog.pages[0].targets)) target.simulationOnly = true;
  f.files.set('/multilingual-v3.json', JSON.stringify(catalog));
  const production = await loadPublishedWeeks(f.fetchImpl);
  assert.equal(production.weeks.length, 0);
  const dev = await loadPublishedWeeks(f.fetchImpl, {allowDevCandidates:true});
  assert.equal(dev.weeks.length, 1);
  for (const variant of Object.values(dev.weeks[0].contentVariants)) {
    assert.equal(variant.releaseLabel, '模拟审核测试');
    assert.equal(variant.humanContentReview, 'simulated');
    assert.equal(variant.simulationOnly, true);
    assert.equal(variant.productionStages[0].status, 'review');
  }
});

test('v2 keeps longer spoken audio separate from source reading clock', async () => {
  const f = fixture(({content, captions}) => {
    content.schemaVersion = 'sermon-full-video-text-content-v2';
    content.reviewMode = 'formal'; content.audioDurationSeconds = 15;
    captions.cues[0].end = 14;
  });
  const result = await loadPublishedWeeks(f.fetchImpl);
  assert.deepEqual(result.errors, []);
  const variant = result.weeks[0].contentVariants['zh-Hans'];
  assert.equal(variant.sourceDurationSeconds, 10);
  assert.equal(variant.tracks[0].durationSeconds, 15);
  assert.equal(variant.tracks[0].subtitleTiming, 'target_audio_clock');
  assert.equal(variant.fullTranscript[0].end, 8);
});
for (const value of [undefined, null, 0, -1, '15']) {
  test(`v2 rejects missing/invalid audio duration ${value}`, async () => {
    const f = fixture(({content}) => {
      content.schemaVersion = 'sermon-full-video-text-content-v2'; content.reviewMode = 'formal';
      content.audioDurationSeconds = value;
    });
    const result = await loadPublishedWeeks(f.fetchImpl);
    assert.equal(result.weeks.length, 0);
    assert.equal(result.errors.length, 3);
  });
}
test('v2 cannot use the audio clock to admit full text past the source', async () => {
  const f = fixture(({content}) => {
    content.schemaVersion = 'sermon-full-video-text-content-v2'; content.reviewMode = 'formal';
    content.audioDurationSeconds = 15; content.cues[0].end = 14;
  });
  assert.equal((await loadPublishedWeeks(f.fetchImpl)).weeks.length, 0);
});
test('simulation review mode requires isolated page and target flags', async () => {
  const f = fixture(({content}) => {
    content.schemaVersion = 'sermon-full-video-text-content-v2'; content.reviewMode = 'simulation';
    content.audioDurationSeconds = 10;
  });
  assert.equal((await loadPublishedWeeks(f.fetchImpl, {allowDevCandidates:true})).weeks.length, 0);
});

// Synthetic machine-checked locales: v4 release + content v3 under /releases-v4/,
// listed only in /multilingual-v4.json. /multilingual-v3.json is the human-only projection.
const DISCLOSURES = {
  'zh-Hans': '本语言内容经机器质检后自动发布，未经人工审核。',
  ko: '이 언어 콘텐츠는 기계 품질 검사 후 자동으로 게시되었으며 사람의 검토를 거치지 않았습니다.',
  es: 'Este contenido se publicó automáticamente tras un control de calidad por máquina, sin revisión humana.',
};
const disclosure = locale => ({ locale, text: DISCLOSURES[locale], english: 'Published automatically after machine quality checks, without human review.' });
const basis = status => ({ kind: status === 'machine_checked' ? 'machine_quality_waiver' : 'human_review', receiptSha256: '7'.repeat(64) });
function machineFixture(statuses = { ko: ['machine_checked', 'machine_checked'] }, mutate = () => {}) {
  const f = fixture(args => {
    const { content, release, locale } = args;
    if (statuses[locale]) {
      const [contentStatus, audioStatus] = statuses[locale];
      Object.assign(content, { schemaVersion: 'sermon-full-video-text-content-v3', status: contentStatus, reviewMode: 'formal', audioDurationSeconds: 10,
        ...(contentStatus === 'machine_checked' ? { disclosure: disclosure(locale) } : {}) });
      Object.assign(release, { schemaVersion: 'sermon-target-language-release-package-v4', contentStatus, audioStatus,
        reviewBasis: { fullText: basis(contentStatus), spokenText: basis(audioStatus), audio: basis(audioStatus) }, disclosure: disclosure(locale) });
    }
    mutate(args);
  });
  const catalog = JSON.parse(f.files.get('/multilingual-v3.json')), page = catalog.pages[0];
  for (const [locale, [contentStatus, audioStatus]] of Object.entries(statuses)) {
    const target = page.targets[locale], path = `/releases-v4/${pageId}/${locale}.json`;
    f.files.set(path, f.files.get(target.releasePackageUrl)); f.files.delete(target.releasePackageUrl);
    Object.assign(target, { releasePackageUrl: path, contentStatus, audioStatus });
  }
  for (const locale of ['zh-Hans', 'ko', 'es']) bindStudy(f, page, locale);
  f.files.set('/multilingual-v4.json', JSON.stringify({ ...catalog, schemaVersion: 'sermon-multilingual-catalog-v4' }));
  const projection = structuredClone(catalog);
  for (const locale of Object.keys(statuses)) delete projection.pages[0].targets[locale];
  projection.pages = projection.pages.filter(item => Object.keys(item.targets).length);
  f.files.set('/multilingual-v3.json', JSON.stringify(projection));
  return f;
}
const machineFields = ['machineChecked', 'disclosure', 'fullTextHint', 'spokenHint'];
const productWording = view => [view.contentReview, view.audioNotice, view.fullTextHint, view.spokenHint,
  ...view.productionStages.flatMap(stage => [stage.label, stage.detail])].filter(value => value !== null);

test('v4 catalog loads human-reviewed and machine-checked locales; machine products show the disclosure and never claim approval', async () => {
  const f = machineFixture({ ko: ['machine_checked', 'machine_checked'], es: ['human_reviewed', 'machine_checked'] });
  const result = await loadPublishedWeeks(f.fetchImpl);
  assert.deepEqual(result.errors, []);
  assert.equal(f.requests[0], '/multilingual-v4.json');
  assert.ok(!f.requests.includes('/multilingual-v3.json'), 'a valid v4 catalog is not mixed with the v3 projection');
  const variants = result.weeks[0].contentVariants;
  assert.deepEqual(Object.keys(variants), ['zh-Hans', 'ko', 'es']);
  const human = variants['zh-Hans'];
  assert.equal(human.releaseLabel, '正式播放版');
  assert.equal(human.humanContentReview, 'approved');
  assert.equal(human.tracks[0].scope, 'full_reviewed');
  // Human views state the machine fields explicitly, so merging a locale into a week never inherits them.
  for (const key of machineFields) assert.ok(Object.hasOwn(human, key), key);
  assert.equal(human.machineChecked, false);
  assert.equal(human.disclosure, null);

  const ko = variants.ko;
  assert.equal(ko.releaseLabel, '기계 품질 검사');
  assert.equal(ko.machineChecked, true);
  assert.equal(ko.disclosure, DISCLOSURES.ko);
  assert.equal(ko.humanContentReview, 'machine_checked');
  assert.equal(ko.audioStatus, 'full_machine_checked');
  assert.equal(ko.tracks[0].scope, 'full_machine_checked');
  assert.equal(ko.tracks[0].subtitleTiming, 'target_audio_clock');
  assert.equal(ko.contentReview, '전체 원고와 더빙은 기계 품질 검사를 거쳤으며 사람의 검토를 거치지 않았습니다');
  for (const value of productWording(ko)) assert.doesNotMatch(value, /승인/, value);
  assert.match(ko.fullTextHint, /기계 품질 검사/);
  assert.match(ko.spokenHint, /기계 품질 검사/);
  // Outline and meditation stay human-reviewed in this step; the study join is unchanged.
  assert.equal(ko.studyStatus, 'human_reviewed');
  assert.equal(ko.outline[0].title, 'Reviewed outline ko');

  const es = variants.es;
  assert.equal(es.releaseLabel, 'Control de calidad automático');
  assert.equal(es.disclosure, DISCLOSURES.es);
  assert.equal(es.humanContentReview, 'approved', 'human-reviewed text keeps its human wording');
  assert.equal(es.audioStatus, 'full_machine_checked');
  assert.equal(es.contentReview, 'El texto íntegro tiene revisión y aprobación humanas registradas; el doblaje pasó un control de calidad automático, sin revisión humana');
  assert.equal(es.fullTextHint, null);
  assert.match(es.spokenHint, /control de calidad automático/);
  assert.deepEqual(es.productionStages.map(stage => stage.label), ['Revisión del texto', 'Control automático del doblaje y subtítulos', 'Publicación']);
  assert.doesNotMatch(es.audioNotice, /aprobad/);
  assert.ok(!f.requests.some(path => /\.mp3$/.test(path)));
});

test('every locale has its machine-check label and a Chinese machine-checked product never says approved', async () => {
  const both = ['machine_checked', 'machine_checked'];
  const result = await loadPublishedWeeks(machineFixture({ 'zh-Hans': both, ko: both, es: both }).fetchImpl);
  assert.deepEqual(result.errors, []);
  const variants = result.weeks[0].contentVariants;
  assert.deepEqual(Object.fromEntries(Object.entries(variants).map(([locale, view]) => [locale, view.releaseLabel])),
    { 'zh-Hans': '机器质检', ko: '기계 품질 검사', es: 'Control de calidad automático' });
  for (const [locale, view] of Object.entries(variants)) {
    assert.equal(view.disclosure, DISCLOSURES[locale]);
    assert.notEqual(view.humanContentReview, 'approved');
  }
  for (const value of productWording(variants['zh-Hans'])) assert.doesNotMatch(value, /批准|已审核/, value);
  for (const value of productWording(variants.es)) assert.doesNotMatch(value, /aprobad/, value);
});

test('missing v4 catalog silently falls back to v3, which never admits a machine-checked target', async () => {
  const f = studyFixture();
  const result = await loadPublishedWeeks(f.fetchImpl);
  assert.deepEqual(result.errors, []);
  assert.deepEqual(f.requests.slice(0, 2), ['/multilingual-v4.json', '/multilingual-v3.json']);
  assert.deepEqual(Object.keys(result.weeks[0].contentVariants), ['zh-Hans', 'ko', 'es']);
  assert.ok(Object.values(result.weeks[0].contentVariants).every(view => view.machineChecked === false && view.releaseLabel === '正式播放版'));
  // A machine-checked target copied into v3 is rejected before its release is requested.
  const leaked = machineFixture();
  leaked.files.set('/multilingual-v3.json', leaked.files.get('/multilingual-v4.json').replace('sermon-multilingual-catalog-v4', 'sermon-multilingual-catalog-v3'));
  leaked.files.delete('/multilingual-v4.json');
  const fallback = await loadPublishedWeeks(leaked.fetchImpl);
  assert.deepEqual(Object.keys(fallback.weeks[0].contentVariants), ['zh-Hans', 'es']);
  assert.equal(fallback.errors.length, 1);
  assert.ok(!leaked.requests.some(path => path.startsWith('/releases-v4/')));
});

for (const [name, corrupt] of [
  ['schema version', f => f.files.set('/multilingual-v4.json', f.files.get('/multilingual-v4.json').replace('sermon-multilingual-catalog-v4', 'sermon-multilingual-catalog-v3'))],
  ['missing default page', f => { const c = JSON.parse(f.files.get('/multilingual-v4.json')); c.defaultPageId = 'missing'; f.files.set('/multilingual-v4.json', JSON.stringify(c)); }],
  ['malformed JSON', f => f.files.set('/multilingual-v4.json', '{')],
  ['server error', f => { const fetchImpl = f.fetchImpl; f.fetchImpl = async (path, options) => path === '/multilingual-v4.json' ? new Response('', { status: 500 }) : fetchImpl(path, options); }],
]) {
  test(`v4 catalog ${name} falls back to the v3 projection and records the error`, async () => {
    const f = machineFixture();
    corrupt(f);
    const result = await loadPublishedWeeks(f.fetchImpl);
    assert.equal(result.weeks.length, 1, 'the week is not lost');
    assert.deepEqual(Object.keys(result.weeks[0].contentVariants), ['zh-Hans', 'es']);
    assert.equal(result.errors.length, 1);
    assert.match(result.errors[0], /^Catalog v4 unavailable, using v3: /);
    assert.ok(f.requests.includes('/multilingual-v3.json'));
    assert.ok(!f.requests.some(path => path.startsWith('/releases-v4/')));
  });
}

test('content/release status, version or disclosure mismatches isolate only the machine-checked locale', async () => {
  const changes = [
    ['human content under machine release', 'Published content identity mismatch', ({ content }) => { content.status = 'human_reviewed'; delete content.disclosure; }],
    ['content v2 under machine release', 'Published content identity mismatch', ({ content }) => { content.schemaVersion = 'sermon-full-video-text-content-v2'; content.status = 'human_reviewed'; delete content.disclosure; }],
    ['content disclosure of another locale', 'Invalid machine-checked content status or disclosure', ({ content }) => { content.disclosure = disclosure('es'); }],
    ['content disclosure text differs from release', 'Content disclosure differs from its release', ({ content }) => { content.disclosure = { ...content.disclosure, text: 'Different wording' }; }],
    ['release status differs from the catalog target', 'Release status does not match catalog target', ({ content, release }) => {
      release.contentStatus = 'human_reviewed'; release.reviewBasis.fullText = basis('human_reviewed');
      content.status = 'human_reviewed'; delete content.disclosure;
    }],
    ['v3 release on a v4 path', 'Invalid machine-checked release', ({ release }) => {
      release.schemaVersion = 'sermon-target-language-release-package-v3';
      release.contentStatus = release.audioStatus = 'human_reviewed';
      delete release.reviewBasis; delete release.disclosure;
    }],
    ['release disclosure of another locale', 'Invalid machine-checked release', ({ release }) => { release.disclosure = disclosure('zh-Hans'); }],
  ];
  for (const [name, reason, change] of changes) {
    const f = machineFixture(undefined, args => { if (args.locale === 'ko') change(args); });
    const result = await loadPublishedWeeks(f.fetchImpl);
    assert.deepEqual(Object.keys(result.weeks[0].contentVariants), ['zh-Hans', 'es'], name);
    assert.equal(result.errors.length, 1, name);
    assert.match(result.errors[0], new RegExp(`/ko: ${reason}`), name);
  }
  // Content v3 is read only through a v4 release, even when human-reviewed.
  const f = studyFixture(({ content, locale }) => {
    if (locale === 'ko') Object.assign(content, { schemaVersion: 'sermon-full-video-text-content-v3', reviewMode: 'formal', audioDurationSeconds: 10 });
  });
  const result = await loadPublishedWeeks(f.fetchImpl);
  assert.deepEqual(Object.keys(result.weeks[0].contentVariants), ['zh-Hans', 'es']);
  assert.match(result.errors[0], /\/ko: Published content identity mismatch/);
});

 test('v4 audio waiver retains human-reviewed v1 full text', async () => {
  const f = machineFixture({ es: ['human_reviewed', 'machine_checked'] }, ({ locale, content }) => {
    if (locale === 'es') {
      content.schemaVersion = 'sermon-full-video-text-content-v1';
      delete content.audioDurationSeconds;
      delete content.reviewMode;
    }
  });
  const result = await loadPublishedWeeks(f.fetchImpl);
  const view = result.weeks[0].contentVariants.es;
  assert.ok(view);
  assert.equal(view.humanContentReview, 'approved');
  assert.equal(view.audioStatus, 'full_machine_checked');
  assert.equal(view.disclosure, DISCLOSURES.es);
});
