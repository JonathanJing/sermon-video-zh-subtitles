import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { validatePublishedCatalogHeader, validatePublishedPage, validatePublishedTarget } from './published-weeks.mjs';

const matrix = JSON.parse(readFileSync(new URL('../../../apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-catalog-pages.json', import.meta.url)));
assert.equal(matrix.schemaVersion, 'sermon-shared-catalog-page-fixtures-v1');
assert.equal(matrix.scope, 'synthetic_decoder_tests_not_production_approval');
assert.equal(matrix.cases.length, 33);
for (const row of matrix.cases) {
  test(`shared catalog header/page: ${row.id}`, () => {
    const validate = () => {
      validatePublishedCatalogHeader(row.catalog);
      for (const page of row.catalog.pages) {
        validatePublishedPage(page);
        for (const [locale, target] of Object.entries(page.targets)) validatePublishedTarget(target, page, locale);
      }
    };
    if (row.expected === 'accept') assert.doesNotThrow(validate);
    else { assert.equal(row.expected, 'reject'); assert.throws(validate); }
  });
}
