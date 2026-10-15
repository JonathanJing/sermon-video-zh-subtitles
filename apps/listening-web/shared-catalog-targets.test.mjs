import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { validatePublishedTarget } from './published-weeks.mjs';

const matrix = JSON.parse(readFileSync(new URL('../../../apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-catalog-targets.json', import.meta.url)));
assert.equal(matrix.schemaVersion, 'sermon-shared-catalog-target-fixtures-v1');
assert.equal(matrix.scope, 'synthetic_decoder_tests_not_production_approval');
assert.equal(matrix.cases.length, 31);
for (const row of matrix.cases) {
  test(`shared production catalog target: ${row.id}`, () => {
    const validate = () => validatePublishedTarget(row.target, { id: row.pageId }, row.locale);
    if (row.expected === 'accept') {
      assert.equal(validate(), row.target);
      // This bridge only exposes audio with captions; native may expose the
      // valid text-only page. Admission is not a claim of playback parity.
      assert.equal(row.webPlayback, row.target.audioStatus === 'human_reviewed'
        && row.target.capabilities.includes('captions'));
    } else {
      assert.equal(row.expected, 'reject');
      assert.throws(validate);
    }
  });
}
