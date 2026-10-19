"""L4 D5: the unified delivery stage accepts exactly the release-basis audio waivers.

The stage used ``machine_quality_release_basis.is_audio_waiver`` through the app
release builder; D2 removed that attribute, so the machine-waived audio branch would
have raised. It now asks the Waivers port's release-basis check, which keeps the
original schema set (v1/v2, not the v3 listening waiver).
"""
import unittest

from scripts import machine_audio_waiver_acceptance as acceptance
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.review import release_basis as basis
from tongxing_production.delivery import unified_stage as stage
from tongxing_production.delivery import unified_stage


class UnifiedDeliveryStageTests(unittest.TestCase):
    def test_facade_is_the_package_module(self):
        self.assertIs(stage, unified_stage)

    def test_audio_waiver_check_keeps_the_release_basis_schemas(self):
        for schema in (basis.AUDIO_WAIVER_SCHEMA, basis.LEGACY_AUDIO_WAIVER_SCHEMA):
            with self.subTest(schema=schema):
                self.assertTrue(unified_stage._audio_waived({'schemaVersion': schema}))
        self.assertFalse(unified_stage._audio_waived({'schemaVersion': acceptance.SCHEMA}))
        self.assertFalse(unified_stage._audio_waived({'schemaVersion': 'sermon-human-audio-review-v4'}))
        self.assertFalse(unified_stage._audio_waived(None))


if __name__ == '__main__':
    unittest.main()
