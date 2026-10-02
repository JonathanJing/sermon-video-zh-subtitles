import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { validatePublishedCatalogHeader, validatePublishedPage, validatePublishedTarget } from './published-weeks.mjs';

const matrix = JSON.parse(readFileSync(new URL('../../../apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-video-delivery.json', import.meta.url)));
assert.equal(matrix.schemaVersion, 'sermon-shared-video-delivery-fixtures-v1');
assert.equal(matrix.scope, 'synthetic_decoder_tests_not_production_approval');
assert.equal(matrix.cases.length, 61);
assert.equal(new Set(matrix.cases.map(row => row.id)).size, matrix.cases.length);

for (const row of matrix.cases) {
  test(`shared videoDelivery catalog admission: ${row.id}`, () => {
    assert.ok(['accept', 'reject'].includes(row.webAcceptance));
    const validate = () => {
      validatePublishedCatalogHeader(row.catalog);
      for (const page of row.catalog.pages) {
        validatePublishedPage(page);
        for (const [locale, target] of Object.entries(page.targets)) validatePublishedTarget(target, page, locale);
      }
    };
    // These are the real loader's catalog gates, not a second implementation
    // of the schema. Admission says nothing about video fetching or playback.
    if (row.webAcceptance === 'accept') assert.doesNotThrow(validate, row.note);
    else assert.throws(validate, row.note);
  });
}
