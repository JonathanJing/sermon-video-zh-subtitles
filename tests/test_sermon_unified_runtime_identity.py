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
                     'tools/ops/tracker-publisher/publish.mjs',
                     'packages/tracker-contract/src/sanitize.mjs',
                     'packages/production/src/tongxing_production/compute/provider_limits.py',
                     'packages/production/src/tongxing_production/orchestration/unified/runtime.py'):
            self.assertIn(name,modules)
        self.assertFalse(any('/node_modules/' in name for name in modules))
        # DEV-GOV-002: scripts/ and schemas/ enter through the Layer 2 code closure manifest, not wholesale.
        for name in ('config/layer2-code-closure.json', 'scripts/tongxing_host.py',
                     'scripts/language_review_plugins/common.py', 'docs/series-terminology.zh.md',
                     'schemas/sermon-target-language-candidate-v2.schema.json'):
            self.assertIn(name, modules)
        for name in ('scripts/check_run_start.py', 'scripts/plan_run_budgets.py'):
            self.assertNotIn(name, modules)
