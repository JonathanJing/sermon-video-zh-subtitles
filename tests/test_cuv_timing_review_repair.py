import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from scripts import sermon_cuv_translation as m


class TimingReviewRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.prior = {'operation': m.TIMING_REVISION, 'promptPolicy': m.TIMING_AWARE_POLICY}
        self.source = self.root / 'cuv-manifest.json'
        m.atomic_json(self.source, self.prior)
        self.manifest = {**self.prior, 'reuseFrom': m.bind(self.source), 'timingReviewRepairFrom': m.bind(self.source)}
        self.rows = [{'id': 28, 'zhTemplate': '甲乙丙'}, {'id': 29, 'zhTemplate': '丁戊'}]
        self.review = {'issues': [], 'blocks': self.rows}
        self.draft = [{'id': 28, 'zhTemplate': '甲乙'}, {'id': 29, 'zhTemplate': '丁戊'}]
        req = {'version': m.VERSION, 'stage': 'review-timing-narration-6', 'identity': m.digest(self.prior), 'payload': {'original': True}}
        response = {'model': m.MODEL, 'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(self.review)}}]}
        path = self.root / 'cache' / (req['stage'] + '-' + m.digest(req) + '.json')
        m.atomic_json(path, {'request': req, 'requestSha256': m.digest(req), 'response': response, 'responseSha256': m.digest(response)})
        self.receipt = m.bind(path)

    def call(self):
        return m.timing_review_repair(self.root / 'new', self.manifest, 6, self.rows, self.draft,
                                     self.review, self.receipt, {'draft': self.draft}, 'review', offline=True)

    def test_only_violation_repaired_with_full_evidence(self):
        with mock.patch.object(m, 'cached_call', return_value=({'issues': [], 'blocks': [{'id': 28, 'zhTemplate': '甲乙'}]}, {'proof': True})) as call:
            result, receipts = self.call()
        self.assertEqual(result['blocks'][1], self.rows[1])
        data = call.call_args.args[3]
        self.assertEqual(data['repairBlockIds'], [28])
        self.assertEqual(data['originalFailedReview'], self.review)
        self.assertEqual(data['characterBudgetViolations'], [{'id': 28, 'maximumFinalNarrationChars': 2, 'actualFinalNarrationChars': 3}])
        self.assertEqual(data['originalFailedReviewReceipt'], self.receipt)
        self.assertEqual(call.call_args.args[1], 'repair-timing-review-6')
        self.assertTrue(call.call_args.kwargs['offline'])

    def test_no_opt_in_preserves_old_failure_path_without_call(self):
        self.manifest = self.prior
        with mock.patch.object(m, 'cached_call') as call:
            result, receipts = self.call()
        self.assertEqual(result, self.review)
        call.assert_not_called()

    def test_still_expanded_fails_no_retry(self):
        with mock.patch.object(m, 'cached_call', return_value=({'issues': [], 'blocks': [self.rows[0]]}, {})) as call:
            with self.assertRaisesRegex(ValueError, 'still expanded'):
                self.call()
        self.assertEqual(call.call_count, 1)

    def test_changed_source_rejected_before_call(self):
        self.manifest['changedEvidence'] = True
        with mock.patch.object(m, 'cached_call') as call:
            with self.assertRaisesRegex(ValueError, 'changed original'):
                self.call()
        call.assert_not_called()

    def test_extra_accepted_block_or_global_issue_rejected(self):
        for response in [self.review, {'issues': ['cannot fit meaning'], 'blocks': [self.rows[0]]}]:
            with mock.patch.object(m, 'cached_call', return_value=(response, {})):
                with self.assertRaises(ValueError):
                    self.call()

if __name__ == '__main__':
    unittest.main()
