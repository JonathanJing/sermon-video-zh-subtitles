import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { sha256, validateSpeakerClips, loadSpeakerClips, verifiedAssetURL, createDemoPlayer, legacyDevClips, legacyProductionClips, validateDemoResponse } from './speaker-clip-demos.mjs';
const hash = 'a'.repeat(64), prefix = '/voice-demos/speaker-clips-v2/';
async function fixture() {
  const englishTextSha256 = await sha256(new TextEncoder().encode('Source clip.'));
  return { schemaVersion: 'sermon-speaker-clip-demo-catalog-v2', status: 'audition_demo', sourceScope: 'source_clip_translation_audition_not_sermon_release', humanListeningStatus: 'pending', speakerCount: 6, sampleCount: 18,
    speakers: Array.from({ length: 6 }, (_, i) => {
      const clipId = `clip-${i}`, asset = name => ({ path: `${prefix}speaker_${i}/${name}`, sha256: hash, bytes: 10, sourceClipId: clipId, englishTextSha256, durationSeconds: 12 });
      return { speakerId: `speaker_${i}`, displayName: `Speaker ${i}`, clipId,
        source: { url: 'https://example.org/source', startSeconds: 120, endSeconds: 132, englishTextSha256 },
        original: { ...asset('en.mp3'), locale: 'en', transcriptStatus: 'machine_screening_only', text: 'Source clip.' }, video: asset('clip.mp4'),
        samples: ['zh-Hans', 'ko', 'es'].map(locale => ({ ...asset(`${locale}.mp3`), locale, text: `${locale} text`, humanListeningStatus: 'pending' })) };
    }) };
}
const response = (status, json) => ({ status, ok: status === 200, json: async () => json });
function legacy() {
  return { schemaVersion: 'sermon-multilingual-voice-demo-public-v1', status: 'audition_demo', humanListeningStatus: 'pending', sourceScope: 'voice_capability_audition_not_sermon_translation', speakerCount: 6, sampleCount: 24, speakers: Array.from({ length: 6 }, (_, i) => ({ speakerId: `speaker_${i}`, displayName: `Speaker ${i}`,
    original: { path: `/voice-demos/2026-09-21-v2/speaker_${i}/en.mp3`, sha256: hash, bytes: 10, text: 'Original source.', transcriptStatus: 'machine_screening_only', sourceUrl: 'https://example.org/source' }, samples: ['zh-Hans', 'ko', 'es', 'vi'].map(locale => ({ path: `/voice-demos/2026-09-21-v2/speaker_${i}/${locale}.mp3`, sha256: hash, bytes: 10, locale, humanListeningStatus: 'pending', text: `Independent ${locale} script` })) })) };
}
test('same-clip contract admits six speakers with exactly three locale tracks', async () => {
  const result = await validateSpeakerClips(await fixture()); assert.equal(result.matchedClip, true); assert.equal(result.speakers.length, 6);
});
test('reject cross-bound source, changed text, duplicate languages, unsafe paths and mismatched video', async () => {
  for (const mutate of [c => c.speakers[0].samples[0].sourceClipId = 'wrong', c => c.speakers[0].samples[0].englishTextSha256 = 'b'.repeat(64), c => c.speakers[0].original.text += ' changed', c => c.speakers[0].samples[0].locale = 'ko', c => c.speakers[0].video.path = `${prefix}../clip.mp4`, c => c.speakers[0].video.durationSeconds = 99, c => c.humanListeningStatus = 'approved']) {
    const catalog = await fixture(); mutate(catalog); await assert.rejects(validateSpeakerClips(catalog));
  }
});
test('fallback occurs only on a v2 404; server failures and bad v2 reject', async () => {
  const calls = []; const old = legacy();
  const catalog = await loadSpeakerClips({ fetcher: async url => { calls.push(url); return response(calls.length === 1 ? 404 : 200, old); } });
  assert.equal(catalog.matchedClip, false); assert.equal(catalog.speakers[0].video, null); assert.equal(catalog.speakers[0].samples.length, 3); assert.equal(calls.length, 2);
  for (const status of [401, 500]) { let count = 0; await assert.rejects(loadSpeakerClips({ fetcher: async () => { count++; return response(status); } })); assert.equal(count, 1); }
  let count = 0; await assert.rejects(loadSpeakerClips({ fetcher: async () => { count++; return response(200, {}); } })); assert.equal(count, 1);
});
test('legacy samples remain independent scripts with no invented same-clip video', () => {
  const result = legacyDevClips(legacy()); assert.equal(result.matchedClip, false); assert.equal(result.speakers[0].video, null); assert.match(result.speakers[0].samples[0].text, /Independent/);
});
test('production fallback uses exact weekly Chinese text and ko/es additions rather than claiming a translation', () => {
  const track = suffix => ({ audioUrl: `/media/${suffix}.mp3`, sha256: hash, durationSeconds: 12, cues: [{ text: `Existing ${suffix} text` }] });
  const weekly = { schemaVersion: 'sermon-weekly-catalog-v1', voiceBank: { speakers: Array.from({ length: 6 }, (_, i) => ({ id: `speaker_${i}`, name: `Speaker ${i}`, humanListeningStatus: 'accepted', reference: track(`en${i}`), chinese: track(`zh${i}`), referenceSourceUrl: 'https://example.org/source' })) } };
  const additions = { schemaVersion: 'sermon-production-voice-auditions-v1', status: 'audition_demo', humanListeningStatus: 'pending', sourceScope: 'voice_capability_audition_not_sermon_translation', speakerCount: 6, sampleCount: 12, speakers: legacy().speakers.map(speaker => ({ ...speaker, samples: speaker.samples.filter(sample => ['ko', 'es'].includes(sample.locale)).map(sample => ({ ...sample, humanListeningStatus: 'pending' })) })) };
  const result = legacyProductionClips(weekly, additions); assert.equal(result.matchedClip, false); assert.equal(result.speakers[0].samples[0].text, 'Existing zh0 text'); assert.equal(result.speakers[0].video, null);
  additions.speakers[0].displayName = 'Wrong person'; assert.throws(() => legacyProductionClips(weekly, additions));
});
test('media is playable only after byte count and SHA verification', async () => {
  const bytes = new TextEncoder().encode('verified-media'), asset = { path: `${prefix}clip.mp3`, sha256: await sha256(bytes), bytes: bytes.length };
  const fetcher = async () => ({ ok: true, arrayBuffer: async () => bytes.buffer });
  assert.equal(await verifiedAssetURL(asset, { fetcher, createURL: () => 'blob:verified' }), 'blob:verified');
  await assert.rejects(verifiedAssetURL({ ...asset, sha256: hash }, { fetcher })); await assert.rejects(verifiedAssetURL({ ...asset, bytes: 1 }, { fetcher }));
});
class Media extends EventTarget {
  paused = true; ended = false; currentTime = 0; duration = 12; src = ''; playCount = 0;
  pause() { this.paused = true; this.dispatchEvent(new Event('pause')); }
  async play() { this.paused = false; this.playCount++; this.dispatchEvent(new Event('play')); }
  removeAttribute(name) { if (name === 'src') this.src = ''; } load() { this.currentTime = 0; }
}
test('video HTML masquerading as an MP4 is rejected before playback', async () => {
  const bytes = new TextEncoder().encode('video-bytes');
  await assert.rejects(verifiedAssetURL({ path: `${prefix}clip.mp4`, sha256: await sha256(bytes), bytes: bytes.length }, {
    fetcher: async () => ({ ok: true, headers: { get: () => 'text/html' }, arrayBuffer: async () => bytes.buffer }),
  }));
});
test('play toggles to pause and resumes at its existing position', async () => {
  const media = new Media(), states = []; let exclusive = 0;
  const player = createDemoPlayer(media, { pauseOthers: () => exclusive++, resolveURL: async () => 'blob:test', onChange: value => states.push(value) });
  player.select({ path: 'clip', durationSeconds: 12 }); await player.toggle(); media.currentTime = 5; assert.equal(media.paused, false);
  await player.toggle(); assert.equal(media.paused, true); assert.equal(media.currentTime, 5); await player.toggle(); assert.equal(media.currentTime, 5); assert.equal(media.playCount, 2); assert.ok(exclusive >= 2); assert.equal(states.at(-1).playing, true);
});
test('three-language switching pauses and does not autoplay; closing while loading cancels late playback', async () => {
  const media = new Media(); let resolve;
  const player = createDemoPlayer(media, { pauseOthers: () => {}, resolveURL: () => new Promise(value => { resolve = value; }) });
  player.select({ path: 'zh' }); const loading = player.toggle(); player.select({ path: 'ko' }); resolve('blob:zh'); await loading; assert.equal(media.playCount, 0); assert.equal(media.paused, true);
  player.select({ path: 'es' }); const pending = player.toggle(); player.pause(); resolve('blob:es'); await pending; assert.equal(media.playCount, 0);
});
test('separate original / video / synthesis controllers enforce one active media', async () => {
  const media = [new Media(), new Media(), new Media()], controllers = [];
  const pauseOthers = active => controllers.forEach((controller, i) => { if (media[i] !== active) controller.pause(); });
  media.forEach((item, i) => { const controller = createDemoPlayer(item, { pauseOthers, resolveURL: async () => `blob:${i}` }); controller.select({ path: `clip${i}` }); controllers.push(controller); });
  for (let i = 0; i < 3; i++) { await controllers[i].toggle(); assert.deepEqual(media.map(item => item.paused), media.map((_, index) => index !== i)); }
});
test('Dev and production renderers and styles are byte identical', async () => {
  for (const name of ['speaker-clip-demos.mjs', 'voice-demo.css']) assert.equal(await readFile(new URL(`./${name}`, import.meta.url), 'utf8'), await readFile(new URL(`../../../firebase/dev/public/${name}`, import.meta.url), 'utf8'));
});

test('a cancelled A download is never cached or played as B after language switch', async () => {
  const media = new Media(), pending = new Map(), requested = [];
  const player = createDemoPlayer(media, { pauseOthers: () => {}, resolveURL: asset => { requested.push(asset.path); return new Promise(resolve => pending.set(asset.path, resolve)); } });
  player.select({ path: 'A', sha256: hash }); const first = player.toggle();
  player.select({ path: 'B', sha256: hash }); pending.get('A')('blob:A'); await first;
  const second = player.toggle(); assert.deepEqual(requested, ['A', 'B']); pending.get('B')('blob:B'); await second;
  assert.equal(media.src, 'blob:B'); assert.equal(media.playCount, 1);
});
test('final asset and catalog response URLs must retain the same origin and exact safe path', () => {
  const path = `${prefix}clip.mp3`, origin = 'https://demo.test';
  validateDemoResponse({ url: origin + path }, path, origin);
  for (const url of ['https://evil.test' + path, origin + path + '?token=1', origin + path + '#secret', 'https://user:pass@demo.test' + path, origin + '/different.mp3']) assert.throws(() => validateDemoResponse({ url }, path, origin));
});
test('an oversized media body is rejected even without Content-Length', async () => {
  const bytes = new Uint8Array(5_000_001);
  await assert.rejects(verifiedAssetURL({ path: `${prefix}clip.mp3`, sha256: await sha256(bytes) }, {
    fetcher: async () => ({ ok: true, arrayBuffer: async () => bytes.buffer }),
  }));
});

test('late completion of an older play request cannot pause the newer requested playback', async () => {
  const media = new Media(), completions = [];
  media.play = () => { media.paused = false; return new Promise(resolve => completions.push(resolve)); };
  const player = createDemoPlayer(media, { pauseOthers: () => {}, resolveURL: async () => 'blob:test' });
  player.select({ path: 'A', sha256: hash }); const old = player.toggle(); await Promise.resolve();
  player.pause(); const current = player.toggle(); await Promise.resolve();
  completions[1](); await current; completions[0](); await old;
  assert.equal(media.paused, false);
});
test('legacy originals reject empty bytes and preserve WAV media type', async () => {
  const empty = new Uint8Array();
  await assert.rejects(verifiedAssetURL({ path: '/media/clip.mp3', sha256: await sha256(empty) }, {
    fetcher: async () => ({ ok: true, arrayBuffer: async () => empty.buffer }),
  }));
  const bytes = new TextEncoder().encode('legacy-wave'); let type;
  await verifiedAssetURL({ path: '/voice-demos/2026-09-21-v2/speaker/en-original.wav', sha256: await sha256(bytes) }, {
    fetcher: async () => ({ ok: true, arrayBuffer: async () => bytes.buffer }), createURL: blob => { type = blob.type; return 'blob:wav'; },
  });
  assert.equal(type, 'audio/wav');
});
