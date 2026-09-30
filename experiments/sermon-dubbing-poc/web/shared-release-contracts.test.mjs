import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { validatePublishedRelease } from './published-weeks.mjs';

// The identical file is bundled into the native Core tests; no copied fixture.
const matrix = JSON.parse(readFileSync(new URL('../../../apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-release-contracts.json', import.meta.url)));
assert.equal(matrix.schemaVersion, 'sermon-shared-release-contract-fixtures-v1');
assert.equal(matrix.scope, 'synthetic_decoder_tests_not_production_approval');
assert.equal(matrix.cases.length, 30);
for (const row of matrix.cases) {
  test(`shared production release contract: ${row.id}`, () => {
    const validate = () => validatePublishedRelease(row.release, { id: row.release.pageId }, row.release.targetLocale);
    if (row.expected === 'accept') {
      const assets = validate();
      assert.equal(assets.audio.path, `/media/${row.release.pageId}/${row.release.targetLocale}.mp3`);
      assert.equal(row.release.deviceAcceptance.status, 'not_run');
      assert.equal(row.release.venueAcceptance.status, 'not_run');
    } else {
      assert.equal(row.expected, 'reject');
      assert.throws(validate);
    }
  });
}
