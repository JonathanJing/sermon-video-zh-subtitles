import unittest
from scripts.sermon_unified import contracts as c


class RuntimeClosureTests(unittest.TestCase):
    def test_legacy_runtime_and_publisher_are_in_required_closure(self):
        modules=c.required_modules()
        for name in ('experiments/sermon-dubbing-poc/weekly_release.py',
                     'experiments/sermon-dubbing-poc/deploy_firebase.py',
                     'packages/fingerprint/bin/build_fingerprint_index.mjs',
                     'packages/fingerprint/src/fingerprint-core.mjs',
                     'apps/listening-web/app.mjs',
                     'services/feedback/index.mjs',
                     'packages/production/src/tongxing_production/compute/provider_limits.py'):
            self.assertIn(name,modules)
        self.assertFalse(any('/node_modules/' in name for name in modules))
