"""One fixture matrix for schema, catalog producer, Web audio and native reader."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from jsonschema import Draft202012Validator
from tests import test_build_multilingual_catalog as producer_fixture

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / 'apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-text-only-releases.json'


class SharedTextOnlyReleaseFixturesTests(unittest.TestCase):
    def setUp(self):
        self.matrix = json.loads(MATRIX.read_text())
        self.fixture = producer_fixture.BuildMultilingualCatalogTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def inputs(self, row):
        locale = row['release']['targetLocale']
        candidate = self.fixture.write('candidate.json', self.matrix['supportingCandidates'][locale])
        audio = self.fixture.write('audio.json', self.matrix['supportingUnavailableAudioPackages'][locale])
        release = self.fixture.write('release.json', row['release'])
        return self.fixture.arguments([candidate], [release], audio_packages=[audio],
                                      allow_legacy=False, default_target=locale)

    def test_shared_matrix_records_schema_and_consumer_semantics_separately(self):
        self.assertEqual(len(self.matrix['cases']), 27)
        self.assertEqual(self.matrix['scope'], 'synthetic_decoder_tests_not_production_approval')
        accepted = [r for r in self.matrix['cases'] if r['nativeAdmission'] == 'accept']
        self.assertEqual(len(accepted), 15)
        validators = {version: Draft202012Validator(json.loads(
            (ROOT / 'schemas' / f'sermon-target-language-release-package-{version}.schema.json').read_text()))
            for version in ('v1', 'v2')}
        for row in self.matrix['cases']:
            with self.subTest(case=row['id']):
                package = row['release']
                self.assertEqual(validators[package['schemaVersion'][-2:]].is_valid(package), row['schemaValid'])
                if row['nativeAdmission'] == 'accept':
                    self.assertTrue(row['schemaValid'])
        # A structurally valid status/flag does not establish semantic readiness.
        self.assertTrue(any(r['schemaValid'] and r['nativeAdmission'] == 'reject'
                            for r in self.matrix['cases']))

    def test_exact_v1_shared_release_bytes_build_text_only_catalog_for_each_locale(self):
        for row in self.matrix['cases']:
            if not (row['id'].startswith('v1-') and row['id'].endswith('unavailable-package')):
                continue
            with self.subTest(case=row['id']):
                catalog, report = producer_fixture.MODULE.build(self.inputs(row))
                locale = row['release']['targetLocale']
                target = catalog['pages'][0]['targets'][locale]
                self.assertEqual(target['capabilities'], ['text'])
                self.assertEqual(target['audioStatus'], 'unavailable')
                self.assertEqual(target['contentStatus'], 'human_reviewed')

    def test_legacy_null_binding_is_only_accepted_with_explicit_compatibility_flag(self):
        rows = [r for r in self.matrix['cases'] if r['id'].startswith('v1-') and r['id'].endswith('legacy-null')]
        self.assertEqual(len(rows), 3)
        for row in rows:
            with self.subTest(case=row['id']):
                args = self.inputs(row)
                with self.assertRaisesRegex(producer_fixture.MODULE.CatalogBuildError, 'requires an audio_unavailable'):
                    producer_fixture.MODULE.build(args)
                args.allow_legacy_null_audio = True
                catalog, _ = producer_fixture.MODULE.build(args)
                self.assertEqual(catalog['pages'][0]['targets'][row['release']['targetLocale']]['capabilities'], ['text'])

    def test_schema_v2_decoder_acceptance_does_not_invent_v1_producer_support(self):
        row = next(r for r in self.matrix['cases'] if r['id'] == 'v2-ko-unavailable-package')
        with self.assertRaises(producer_fixture.MODULE.CatalogBuildError):
            producer_fixture.MODULE.build(self.inputs(row))

    def test_same_locale_unavailable_audio_package_remains_a_real_producer_gate(self):
        row = next(r for r in self.matrix['cases'] if r['id'] == 'v1-ko-unavailable-package')
        for key, value in [('targetLocale', 'es'), ('status', 'candidate'),
                           ('targetLanguageCandidateJsonSha256', 'f'*64),
                           ('englishSourcePackageJsonSha256', 'f'*64)]:
            with self.subTest(field=key):
                args = self.inputs(row)
                audio = copy.deepcopy(self.matrix['supportingUnavailableAudioPackages']['ko'])
                audio[key] = value
                encoded = producer_fixture.encoded(audio)
                Path(args.audio_package[0]).write_bytes(encoded)
                release = copy.deepcopy(row['release'])
                release['targetLanguageAudioPackageJsonSha256'] = hashlib.sha256(encoded).hexdigest()
                Path(args.release[0]).write_bytes(producer_fixture.encoded(release))
                with self.assertRaisesRegex(producer_fixture.MODULE.CatalogBuildError, 'binding or state is invalid'):
                    producer_fixture.MODULE.build(args)


if __name__ == '__main__':
    unittest.main()
