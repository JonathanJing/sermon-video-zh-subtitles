import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import {
  fetchVerified, sameOriginAsset, validateDemoCatalog, validateDemoContent, validateDemoRelease
} from '../firebase/dev/public/dev-integrity.mjs';

const publicDir = resolve(dirname(fileURLToPath(import.meta.url)), '../firebase/dev/public');
const origin = 'https://ai-for-god-sermon-audio-dev.web.app';
const bytesAt = path => readFile(resolve(publicDir, path.slice(1)));
const jsonAt = async path => JSON.parse(await bytesAt(path));
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const clone = value => structuredClone(value);

test('each advertised release and content is bound to its exact bytes', async () => {
  const catalog = validateDemoCatalog(await jsonAt('/multilingual.json'));
  for (const page of catalog.pages) {
    for (const [locale, target] of Object.entries(page.targets)) {
      const releaseBytes = await bytesAt(target.releasePackageUrl);
      assert.equal(digest(releaseBytes), target.releasePackageJsonSha256, locale);
      const release = validateDemoRelease(JSON.parse(releaseBytes), page, locale);
      const contentBytes = await bytesAt(release.contentUrl);
      assert.equal(digest(contentBytes), release.contentSha256, locale);
      validateDemoContent(JSON.parse(contentBytes), release, locale);
    }
  }
});

test('cross page, cross origin, wrong locale, and promoted review claims are rejected', async () => {
  const catalog = validateDemoCatalog(await jsonAt('/multilingual.json'));
  const page = catalog.pages[0];
  const locale = 'zh-Hans';
  const release = await jsonAt(page.targets[locale].releasePackageUrl);
  for (const change of [
    { pageId: 'other-page' }, { targetLocale: 'ko' }, { productionEligible: true },
    { humanApproval: true }, { audioUrl: 'https://example.com/audio.mp3' },
    { contentUrl: '/content/other/zh-Hans.json' }, { audioStatus: 'approved' }
  ]) {
    assert.throws(() => validateDemoRelease(Object.assign(clone(release), change), page, locale));
  }
  const badVariant = clone(release);
  badVariant.audioVariants[0].cues = [{ start: -2, end: 3, text: 'bad' }];
  assert.throws(() => validateDemoRelease(badVariant, page, locale));
  const content = await jsonAt(release.contentUrl);
  assert.throws(() => validateDemoContent({ ...content, locale: 'ko' }, release, locale));
  assert.throws(() => validateDemoContent({ ...content, humanReview: { humanApproval: true } }, release, locale));
  assert.throws(() => sameOriginAsset('//example.com/audio.mp3', '/media/', '.mp3', origin));
  assert.throws(() => sameOriginAsset('/media/../secrets.mp3', '/media/', '.mp3', origin));
  assert.throws(() => validateDemoCatalog({ ...catalog, pages: [page, page] }));
});

test('text-only target is bound to matching status and exposes no audio', async () => {
  const catalog = validateDemoCatalog(await jsonAt('/multilingual.json'));
  const page = clone(catalog.pages[0]);
  const locale = 'ko';
  const release = await jsonAt(page.targets[locale].releasePackageUrl);
  const content = await jsonAt(release.contentUrl);
  page.targets[locale].audioStatus = 'unavailable';
  const textOnly = {
    ...release, audioStatus: 'unavailable', audioUrl: null, audioSha256: null,
    defaultAudioVariantId: null, audioVariants: []
  };
  assert.equal(validateDemoRelease(textOnly, page, locale), textOnly);
  assert.equal(validateDemoContent({ ...content, audioStatus: 'unavailable' }, textOnly, locale).audioStatus,
    'unavailable');
  assert.throws(() => validateDemoRelease({ ...textOnly, audioUrl: release.audioUrl }, page, locale));
  assert.throws(() => validateDemoRelease({ ...textOnly, audioVariants: [{ id: 'default' }] }, page, locale));
  assert.throws(() => validateDemoContent(content, textOnly, locale));
  assert.throws(() => validateDemoRelease({ ...textOnly, targetLocale: 'en' }, page, locale));
});

test('verified fetch rejects changed bytes, oversize assets, and redirects', async () => {
  const path = '/content/2026-09-20-lion-of-judah-poc/en.json';
  const bytes = await bytesAt(path);
  const hash = digest(bytes);
  const response = (value, url = `${origin}${path}`) => ({
    ok: true, url, headers: new Headers({ 'content-length': String(value.length) }),
    arrayBuffer: async () => Uint8Array.from(value).buffer
  });
  const good = await fetchVerified(path, hash, { origin, fetchImpl: async () => response(bytes) });
  assert.equal(digest(good), hash);
  await assert.rejects(fetchVerified(path, hash, {
    origin, fetchImpl: async () => response(Buffer.from(bytes.toString().replace('Jesus', 'Other')))
  }), /hash mismatch/);
  await assert.rejects(fetchVerified(path, hash, {
    origin, maxBytes: bytes.length - 1, fetchImpl: async () => response(bytes)
  }), /too large/);
  await assert.rejects(fetchVerified(path, hash, {
    origin, fetchImpl: async () => response(bytes, 'https://example.com/redirect.json')
  }), /unavailable/);
});

test('verified fetch accepts hashed formal WAV audio and rejects unknown asset types', async () => {
  const path = '/media/2026-09-20-revelation-clip/zh-Hans.wav';
  const bytes = Buffer.from('RIFF-test-WAVE-audio');
  const hash = digest(bytes);
  const good = await fetchVerified(path, hash, {
    origin,
    fetchImpl: async url => ({
      ok: true, url,
      headers: new Headers({ 'content-length': String(bytes.length) }),
      arrayBuffer: async () => Uint8Array.from(bytes).buffer
    })
  });
  assert.equal(digest(good), hash);
  await assert.rejects(fetchVerified('/media/2026-09-20-revelation-clip/zh-Hans.bin', hash, {
    origin, fetchImpl: async () => { throw new Error('unexpected fetch'); }
  }), /Unsupported Dev asset type/);
  await assert.rejects(fetchVerified(null, hash, {
    origin, fetchImpl: async () => { throw new Error('unexpected fetch'); }
  }), /Unsupported Dev asset type/);
});
