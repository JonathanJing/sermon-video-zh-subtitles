import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { loadPublishedWeeks } from './published-weeks.mjs';

const hash = value => createHash('sha256').update(value).digest('hex');
const pageId = '2026-09-27-weekend-sermon-drive-530';
function fixture(mutate = () => {}) {
  const files = new Map(), requests = [];
  const page = {
    id: pageId, date: '2026-09-27', sourceLocale: 'en', defaultTargetLocale: 'zh-Hans',
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
      schemaVersion: 'sermon-target-language-release-package-v2', pageId,
      targetLocale: locale, audioLocale: locale, contentLocale: locale, sourceLocale: 'en',
      status: 'published_http_verified', httpVerification: { status: 'pass' },
      audioStatus: 'human_reviewed', contentStatus: 'human_reviewed',
      targetLanguageCandidateJsonSha256: content.targetLanguageCandidateJsonSha256,
      assets: [
        { role: 'content', path: `/content/${pageId}/${locale}.json` },
        { role: 'captions', path: `/captions/${pageId}/${locale}.json` },
        { role: 'audio', path: `/media/${pageId}/${locale}.mp3`, sha256: 'c'.repeat(64) },
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
  files.set('/multilingual-v3.json', JSON.stringify({ schemaVersion: 'sermon-multilingual-catalog-v3', defaultPageId: pageId, pages: [page] }));
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

test('optional missing or unavailable catalog keeps the legacy app usable', async () => {
  assert.deepEqual(await loadPublishedWeeks(async () => new Response('', { status: 404 })), { weeks: [], defaultWeekId: null, errors: [] });
  const failed = await loadPublishedWeeks(async () => { throw new Error('offline'); });
  assert.deepEqual(failed.weeks, []);
  assert.deepEqual(failed.errors, ['offline']);
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

test('current page loads first and slow archive pages cannot hold the player indefinitely', async () => {
  const f = fixture();
  addHistory(f, 104);
  let active = 0, peak = 0;
  const pendingSignals = [];
  const fetchImpl = (path, options) => {
    if (path.startsWith('/alignment/history-')) {
      active++;
      peak = Math.max(peak, active);
      pendingSignals.push(options.signal);
      options.signal.addEventListener('abort', () => { active--; }, { once: true });
      return new Promise(() => {});
    }
    return f.fetchImpl(path, options);
  };
  const started = Date.now();
  const result = await loadPublishedWeeks(fetchImpl, { requestTimeoutMs: 1000, pageLoadTimeoutMs: 50 });
  assert.ok(Date.now() - started < 500);
  assert.equal(result.defaultWeekId, pageId);
  assert.ok(result.weeks.some(week => week.id === pageId));
  assert.ok(f.requests.indexOf(`/english-reference/${pageId}.json`) < f.requests.findIndex(path => path.startsWith('/releases-v2/history-')));
  assert.ok(peak > 1 && peak <= 12, `expected bounded history concurrency, saw ${peak}`);
  assert.ok(pendingSignals.every(signal => signal.aborted));
  assert.ok(result.errors.some(error => /loading timed out/.test(error)));
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
