import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { validatePublishedContentV3, validatePublishedTarget, validatePublishedV4Release } from './published-weeks.mjs';

// The identical file is bundled into the native Core tests; no copied fixture.
const matrix = JSON.parse(readFileSync(new URL('../../../apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-machine-checked-contracts.json', import.meta.url)));
assert.equal(matrix.schemaVersion, 'sermon-shared-machine-checked-contract-fixtures-v1');
assert.equal(matrix.scope, 'synthetic_decoder_tests_not_production_approval');
assert.equal(matrix.releases.length, 18);
assert.equal(matrix.catalogTargets.length, 12);
assert.equal(matrix.contents.length, 6);
for (const rows of [matrix.releases, matrix.catalogTargets, matrix.contents]) {
  assert.equal(new Set(rows.map(row => row.id)).size, rows.length);
}
// The catalog page binds the release's English source; take it from an accepted row,
// so a future source-mismatch row is still rejected by the four-product check.
const sourceIdentitySha256 = matrix.releases.find(row => row.expected === 'accept').release.englishSourcePackageJsonSha256;

for (const row of matrix.releases) {
  test(`shared machine-checked release: ${row.id}`, () => {
    const release = row.release;
    const validate = () => validatePublishedV4Release(release, { id: release.pageId, sourceIdentitySha256 }, release.targetLocale);
    if (row.expected === 'accept') {
      const assets = validate();
      assert.equal(assets.audio.path, `/media/${release.pageId}/${release.targetLocale}.mp3`);
      assert.deepEqual(Object.keys(assets).sort(), ['audio', 'captions', 'content', 'meditation', 'outline', 'page', 'product_manifest']);
      assert.ok([release.contentStatus, release.audioStatus].includes('machine_checked'));
      assert.equal(release.disclosure.locale, release.targetLocale);
      assert.equal(release.deviceAcceptance.status, 'not_run');
      assert.equal(release.venueAcceptance.status, 'not_run');
    } else {
      assert.equal(row.expected, 'reject');
      assert.throws(validate);
    }
  });
}

for (const row of matrix.catalogTargets) {
  test(`shared machine-checked catalog target: ${row.id}`, () => {
    const validate = () => validatePublishedTarget(row.target, { id: row.pageId }, row.locale, false, 'sermon-multilingual-catalog-v4');
    if (row.expected === 'accept') {
      assert.equal(validate(), row.target);
      // Same playback gate as the loader: audible status plus captions and audio.
      assert.equal(row.webPlayback, ['human_reviewed', 'machine_checked'].includes(row.target.audioStatus)
        && ['text', 'captions', 'audio'].every(value => row.target.capabilities.includes(value)));
      // A v3 catalog never admits a machine-checked target.
      if ([row.target.contentStatus, row.target.audioStatus].includes('machine_checked')) {
        assert.throws(() => validatePublishedTarget(row.target, { id: row.pageId }, row.locale));
      }
    } else {
      assert.equal(row.expected, 'reject');
      assert.throws(validate);
    }
  });
}

for (const row of matrix.contents) {
  test(`shared machine-checked content: ${row.id}`, () => {
    const content = row.content;
    const validate = () => validatePublishedContentV3(content, { id: content.pageId }, content.targetLocale);
    if (row.expected === 'accept') assert.equal(validate(), content);
    else { assert.equal(row.expected, 'reject'); assert.throws(validate); }
  });
}
