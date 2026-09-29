import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { loadDryRunWeeks } from '../firebase/dev/public/dry-run-app-weeks.mjs';

const ID = 'dryrun-20260927-unit';
const LANGUAGES = ['zh-Hans', 'ko', 'es'];
const hash = bytes => createHash('sha256').update(bytes).digest('hex');

function fixture() {
  const files = new Map();
  const put = (path, value) => {
    const bytes = Buffer.from(JSON.stringify(value));
    files.set(path, bytes);
    return hash(bytes);
  };
  put(`/english-reference/${ID}.json`, {
    schemaVersion: 'sermon-dev-simulated-english-reference-v1', status: 'simulation_only',
    pageId: ID, units: [{ sourceUnitId: 'u1', english: 'The throne is occupied.' }],
  });
  const releases = {}, layer2Sha256 = {}, layer3Sha256 = {};
  for (const locale of LANGUAGES) {
    layer2Sha256[locale] = 'b'.repeat(64);
    layer3Sha256[locale] = 'c'.repeat(64);
    const cue = { textGroupId: 'g1', sourceUnitIds: ['u1'], start: 0, end: 1, text: `${locale} text` };
    const contentHash = put(`/content/${ID}/${locale}.json`, {
      schemaVersion: 'sermon-dev-simulated-content-v1', status: 'simulation_only',
      pageId: ID, targetLocale: locale, inputLayer2Sha256: layer2Sha256[locale],
      durationSeconds: 1, title: '耶稣配得', series: '启示录', speaker: 'Eric Geiger', cues: [cue],
    });
    const captionsHash = put(`/captions/${ID}/${locale}.json`, {
      schemaVersion: 'sermon-dev-simulated-captions-v1', status: 'simulation_only',
      pageId: ID, targetLocale: locale, inputLayer3Sha256: layer3Sha256[locale], cues: [cue],
    });
    const path = `/releases-v2/${ID}/${locale}.json`;
    releases[locale] = { path, sha256: put(path, {
      schemaVersion: 'sermon-dev-simulated-release-v1', status: 'simulation_only',
      pageId: ID, targetLocale: locale, inputLayer1Sha256: 'a'.repeat(64),
      inputLayer2Sha256: layer2Sha256[locale], inputLayer3Sha256: layer3Sha256[locale],
      assets: { content: contentHash, captions: captionsHash, audio: 'd'.repeat(64) },
    }) };
  }
  const catalogUrl = `/dry-run/${ID}/catalog.json`;
  const catalogSha256 = put(catalogUrl, {
    schemaVersion: 'sermon-dev-simulated-catalog-v1', status: 'simulation_only',
    pageId: ID, releases, inputLayer1Sha256: 'a'.repeat(64), layer2Sha256, layer3Sha256,
    videoDelivery: { canonicalUrl: `/pages/${ID}/full-video-browser.mp4`, sha256: 'e'.repeat(64) },
  });
  put('/dry-run/latest.json', {
    schemaVersion: 'sermon-dev-simulated-app-index-v1', status: 'simulation_only',
    pageId: ID, catalogUrl, catalogSha256,
  });
  const fetcher = async path => files.has(path)
    ? new Response(files.get(path), { status: 200 })
    : new Response('', { status: 404 });
  return { files, fetcher };
}

test('a bound simulated week appears in the App with three locale variants', async () => {
  const { fetcher } = fixture();
  const result = await loadDryRunWeeks(fetcher);
  assert.deepEqual(result.errors, []);
  assert.equal(result.defaultWeekId, ID);
  assert.deepEqual(Object.keys(result.weeks[0].contentVariants), LANGUAGES);
  assert.equal(result.weeks[0].simulationOnly, true);
  assert.equal(result.weeks[0].contentVariants.ko.tracks[0].audioUrl, `/media/${ID}/ko.mp3`);
});

test('a changed Release is withheld from the App', async () => {
  const { files, fetcher } = fixture();
  files.set(`/releases-v2/${ID}/ko.json`, Buffer.from('{}'));
  const result = await loadDryRunWeeks(fetcher);
  assert.equal(result.weeks.length, 0);
  assert.match(result.errors[0], /hash mismatch/);
});

test('without a Dev simulation index the formal App can load alone', async () => {
  const { files, fetcher } = fixture();
  files.delete('/dry-run/latest.json');
  assert.deepEqual(await loadDryRunWeeks(fetcher), { weeks: [], defaultWeekId: null, errors: [] });
});
