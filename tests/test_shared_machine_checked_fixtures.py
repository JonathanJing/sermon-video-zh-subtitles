"""The machine-checked matrix the Web and native readers share also binds the producer schemas."""
import json
from pathlib import Path
import unittest
from jsonschema import Draft202012Validator, ValidationError
from scripts import delivery_contract as contract

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / 'apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-machine-checked-contracts.json'


def validator(name):
    return Draft202012Validator(json.loads((ROOT / 'schemas' / f'{name}.schema.json').read_text()),
                                format_checker=Draft202012Validator.FORMAT_CHECKER)


def catalog(row):
    page = {'id': row['pageId'], 'title': 'Synthetic fixture', 'date': '2026-10-04', 'sourceLocale': 'en',
            'sourceIdentitySha256': 'a' * 64, 'sourceMediaSha256': 'b' * 64,
            'defaultTargetLocale': row['locale'], 'targets': {row['locale']: row['target']}}
    return {'schemaVersion': contract.CATALOG_V4, 'generatedAt': '2026-10-04T00:00:00Z',
            'defaultPageId': row['pageId'], 'pages': [page]}


def accepts(check):
    try:
        check()
    except (ValueError, ValidationError):
        return False
    return True


class SharedMachineCheckedFixturesTests(unittest.TestCase):
    def setUp(self):
        self.matrix = json.loads(MATRIX.read_text())

    def test_matrix_is_decoder_evidence_not_an_approval(self):
        self.assertEqual(self.matrix['scope'], 'synthetic_decoder_tests_not_production_approval')
        self.assertEqual((len(self.matrix['releases']), len(self.matrix['catalogTargets']), len(self.matrix['contents'])),
                         (23, 12, 6))
        for name in ('releases', 'catalogTargets', 'contents'):
            for row in self.matrix[name]:
                with self.subTest(matrix=name, case=row['id']):
                    if row['expected'] == 'accept':
                        self.assertTrue(row['schemaValid'])

    def test_schema_valid_flags_match_the_producer_schemas(self):
        checks = [('releases', 'release', validator('sermon-target-language-release-package-v4')),
                  ('contents', 'content', validator('sermon-full-video-text-content-v3'))]
        for name, key, schema in checks:
            for row in self.matrix[name]:
                with self.subTest(matrix=name, case=row['id']):
                    self.assertEqual(schema.is_valid(row[key]), row['schemaValid'])
        schema = validator('sermon-multilingual-catalog-v4')
        for row in self.matrix['catalogTargets']:
            with self.subTest(matrix='catalogTargets', case=row['id']):
                self.assertEqual(schema.is_valid(catalog(row)), row['schemaValid'])

    def test_producer_validators_reproduce_every_expected_value(self):
        for row in self.matrix['catalogTargets']:
            with self.subTest(matrix='catalogTargets', case=row['id']):
                self.assertEqual(accepts(lambda: contract.validate_catalog_schema(catalog(row))),
                                 row['expected'] == 'accept')
        for row in self.matrix['releases']:
            release = row['release']

            def published_release():
                contract.validate_release_schema(release)
                contract.require(release['status'] == 'published_http_verified', 'Unpublished release')
            with self.subTest(matrix='releases', case=row['id']):
                self.assertEqual(accepts(published_release), row['expected'] == 'accept')
        schema = validator('sermon-full-video-text-content-v3')
        for row in self.matrix['contents']:
            content = row['content']

            def machine_content():
                schema.validate(content)
                contract.require(content.get('disclosure', {}).get('locale', content['targetLocale'])
                                 == content['targetLocale'], 'Content disclosure is for another locale')
            with self.subTest(matrix='contents', case=row['id']):
                self.assertEqual(accepts(machine_content), row['expected'] == 'accept')


if __name__ == '__main__':
    unittest.main()
