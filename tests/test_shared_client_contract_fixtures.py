"""The shared clients' accepted fixtures must also satisfy the producer schema."""
import json
from pathlib import Path
import unittest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


class SharedClientContractFixturesTests(unittest.TestCase):
    def test_accepted_shared_catalog_targets_satisfy_production_schema(self):
        matrix = json.loads((ROOT / 'apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-catalog-targets.json').read_text())
        schema = json.loads((ROOT / 'schemas/sermon-multilingual-catalog-v3.schema.json').read_text())
        validator = Draft202012Validator(schema)
        accepted = [row for row in matrix['cases'] if row['expected'] == 'accept']
        self.assertEqual(len(matrix['cases']), 31)
        self.assertTrue(any(row['target']['audioStatus'] == 'unavailable' for row in accepted))
        for row in accepted:
            page = {'id': row['pageId'], 'title': 'Synthetic fixture', 'date': '2026-09-30',
                    'sourceLocale': 'en', 'sourceIdentitySha256': 'a' * 64,
                    'sourceMediaSha256': 'b' * 64, 'defaultTargetLocale': row['locale'],
                    'targets': {row['locale']: row['target']}}
            catalog = {'schemaVersion': 'sermon-multilingual-catalog-v3',
                       'generatedAt': '2026-09-30T00:00:00Z',
                       'defaultPageId': row['pageId'], 'pages': [page]}
            with self.subTest(case=row['id']):
                validator.validate(catalog)

    def test_accepted_web_native_fixture_is_valid_production_release_schema(self):
        matrix = json.loads((ROOT / 'apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-release-contracts.json').read_text())
        schema = json.loads((ROOT / 'schemas/sermon-target-language-release-package-v2.schema.json').read_text())
        validator = Draft202012Validator(schema)
        accepted = [row for row in matrix['cases'] if row['expected'] == 'accept']
        self.assertEqual({row['release']['targetLocale'] for row in accepted}, {'zh-Hans', 'ko', 'es'})
        for row in accepted:
            with self.subTest(case=row['id']):
                validator.validate(row['release'])

    def test_producer_page_boundary_is_not_reused_as_package_identifier_limit(self):
        from scripts import build_full_video_app_release as producer
        matrix = json.loads((ROOT / 'apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-release-contracts.json').read_text())
        boundaries = [row for row in matrix['cases'] if row['id'].startswith('producer-page-')]
        self.assertEqual(len(boundaries), 9)
        for row in boundaries:
            package = row['release']
            self.assertIsNotNone(producer.PAGE_ID.fullmatch(package['pageId']))
            self.assertEqual(package['packageId'], f"{package['pageId']}-{package['targetLocale']}-dual-script")
            self.assertEqual(row['expected'], 'accept')
        self.assertEqual(max(len(row['release']['packageId']) for row in boundaries), 180)
