"""One synthetic matrix records schema, Web and Swift catalog gates separately."""
import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / 'apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-video-delivery.json'


class SharedVideoDeliveryFixturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = json.loads(MATRIX.read_text(encoding='utf-8'))
        cls.rows = cls.matrix['cases']
        cls.by_id = {row['id']: row for row in cls.rows}
        schema = json.loads((ROOT / 'schemas/sermon-multilingual-catalog-v3.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)

    def test_matrix_has_explicit_independent_expectations(self):
        self.assertEqual(self.matrix['schemaVersion'], 'sermon-shared-video-delivery-fixtures-v1')
        self.assertEqual(self.matrix['scope'], 'synthetic_decoder_tests_not_production_approval')
        self.assertEqual(len(self.rows), 61)
        self.assertEqual(len(self.by_id), len(self.rows))
        expectation_keys = {'schemaAcceptance', 'webAcceptance', 'swiftAcceptance'}
        self.assertEqual(set(self.matrix['acceptanceMeaning']), expectation_keys)
        self.assertEqual({row['category'] for row in self.rows}, {
            'legacy', 'valid', 'path', 'bucket', 'hash', 'binding', 'bytes',
            'shape', 'source', 'locale', 'unknown',
        })
        for row in self.rows:
            with self.subTest(case=row['id']):
                self.assertTrue(row['note'].strip())
                for key in expectation_keys:
                    self.assertIn(row[key], {'accept', 'reject'})

    def test_every_row_matches_catalog_v3_schema_including_rejections(self):
        for row in self.rows:
            with self.subTest(case=row['id']):
                errors = list(self.validator.iter_errors(row['catalog']))
                self.assertEqual(not errors, row['schemaAcceptance'] == 'accept',
                                 '; '.join(error.message for error in errors))

    def test_video_shape_rejections_do_not_hide_invalid_base_catalogs(self):
        isolated_categories = {'path', 'bucket', 'hash', 'shape', 'bytes'}
        rejected = [row for row in self.rows if row['category'] in isolated_categories
                    and row['schemaAcceptance'] == 'reject']
        self.assertTrue(rejected)
        for row in rejected:
            with self.subTest(case=row['id']):
                without_video = copy.deepcopy(row['catalog'])
                without_video['pages'][0].pop('videoDelivery')
                self.validator.validate(without_video)

    def test_both_buckets_and_all_existing_target_locales_are_covered(self):
        for bucket in ('dev', 'prod'):
            for locale in ('zh-Hans', 'ko', 'es'):
                row = self.by_id[f'valid-{bucket}-{locale}']
                page = row['catalog']['pages'][0]
                with self.subTest(bucket=bucket, locale=locale):
                    self.assertEqual(page['defaultTargetLocale'], locale)
                    self.assertEqual(set(page['targets']), {locale})
                    delivery = page['videoDelivery']
                    self.assertEqual(delivery['canonicalUrl'], f"/pages/{page['id']}/full-video-browser.mp4")
                    self.assertEqual(delivery['storageUrl'],
                                     f"https://storage.googleapis.com/ai-for-god-sermon-media-{bucket}"
                                     f"/weekly/{page['id']}/{delivery['sha256']}.mp4")
                    # Source media and browser-encoded delivery are independent hashes.
                    self.assertNotEqual(page['sourceMediaSha256'], delivery['sha256'])
                    self.assertEqual([row[key] for key in self.matrix['acceptanceMeaning']], ['accept'] * 3)

    def test_observed_differences_are_not_labeled_cross_client_equivalence(self):
        for case in ('video-missing-source-hash', 'video-null-source-hash',
                     'storage-wrong-bucket', 'video-null', 'unknown-catalog-field',
                     'unknown-page-field', 'unknown-target-field', 'unknown-video-field'):
            with self.subTest(case=case):
                row = self.by_id[case]
                self.assertEqual((row['schemaAcceptance'], row['webAcceptance'], row['swiftAcceptance']),
                                 ('reject', 'accept', 'accept'))
        # Syntax-only schema admission cannot enforce cross-field equality.
        for case in ('canonical-other-page', 'storage-other-page', 'storage-other-valid-hash',
                     'declared-other-valid-video-hash'):
            row = self.by_id[case]
            self.assertEqual((row['schemaAcceptance'], row['webAcceptance'], row['swiftAcceptance']),
                             ('accept', 'accept', 'accept'))
        row = self.by_id['video-wrong-release-locale']
        self.assertEqual((row['schemaAcceptance'], row['webAcceptance'], row['swiftAcceptance']),
                         ('accept', 'reject', 'reject'))
        for case in ('video-malformed-source-hash', 'video-number-source-hash'):
            row = self.by_id[case]
            self.assertEqual((row['schemaAcceptance'], row['webAcceptance'], row['swiftAcceptance']),
                             ('reject', 'reject', 'reject'))


if __name__ == '__main__':
    unittest.main()
