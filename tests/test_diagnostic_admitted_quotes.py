"""Admitted-quotation plugin: exact CUV check, frozen literals, and rule-preflight output.

Receipts are synthetic inputs built from the pinned CUV text; nothing here is a
human approval.
"""
import json
import tempfile
import unittest
from pathlib import Path

from scripts import cuv_scripture
from scripts import scripture_adjudication as adjudication
from scripts import target_language_policy as policies
from scripts import target_language_rule_preflight as preflight
from scripts.language_review_plugins import diagnostic_admitted_quotes as helper

LIBRARY = cuv_scripture.CuvLibrary.from_path()
REV = LIBRARY.lookup('REV 4:2-3')['text']
UNITS = ['u-quote-1', 'u-quote-2']
BINDINGS = {'source.json': 'a' * 64, 'anchor.json': 'b' * 64, 'group-plan.json': 'c' * 64}


def receipt():
    return {'schemaVersion': adjudication.SCHEMA, 'targetLocale': 'zh-Hans', 'bindings': dict(BINDINGS),
            'decision': 'approved', 'decidedBy': 'synthetic test reviewer', 'decidedByRole': 'human_reviewer',
            'reviewedAt': '2026-10-08T00:00:00+00:00',
            'candidates': [
                {'candidateId': 'q1', 'sourceUnitIds': [UNITS[0]], 'classification': 'direct_quote',
                 'reference': 'REV 4:2-3', 'editionId': 'CUV', 'exactSentence': REV},
                {'candidateId': 'q2', 'sourceUnitIds': [UNITS[1]], 'classification': 'partial_direct_quote',
                 'reference': 'REV 3:16', 'editionId': 'CUV', 'exactSentence': '也不冷也不热'}]}


def summary():
    return adjudication.validate_receipt(receipt(), target_locale='zh-Hans', bindings=BINDINGS,
                                         flagged_units=UNITS, library=LIBRARY)


def units():
    return [{'sourceUnitId': UNITS[0], 'english': 'Verse two and three, John says the throne was in heaven.'},
            {'sourceUnitId': UNITS[1], 'english': 'The one seated had the appearance of jasper.'}]


def group(text):
    return {'translationGroupId': 'g1', 'sourceUnitIds': UNITS, 'targetText': text,
            'targetUtterances': [text]}


class ExactQuoteCheckTests(unittest.TestCase):
    def test_every_admitted_sentence_present_verbatim_passes(self):
        rows = summary()['admitted']
        target = REV + '。' + '也不冷也不热'
        check = helper._exact_result(UNITS, target, rows)
        self.assertEqual(check['status'], 'pass')

    def test_missing_or_altered_sentence_fails_with_candidate_ids(self):
        rows = summary()['admitted']
        check = helper._exact_result(UNITS, '译文没有引文', rows)
        self.assertEqual(check['status'], 'fail')
        self.assertIn('q1', check['evidence'])
        self.assertIn('q2', check['evidence'])

    def test_group_without_admitted_quotes_passes_without_claiming_approval(self):
        check = helper._exact_result(['other'], 'anything', summary()['admitted'])
        self.assertEqual(check['status'], 'pass')
        self.assertIn('No admitted', check['evidence'])

    def test_quote_split_across_groups_fails(self):
        spanning = [{'candidateId': 'q9', 'sourceUnitIds': list(UNITS), 'classification': 'direct_quote',
                     'canonicalRef': 'REV 4:2-3', 'exactSentence': REV, 'textSha256': 'x' * 64}]
        check = helper._exact_result([UNITS[0]], REV, spanning)
        self.assertEqual(check['status'], 'fail')
        self.assertIn('split', check['evidence'])

    def test_plugin_rejects_policy_without_the_cuv_exact_quote_scripture_block(self):
        policy = {'schemaVersion': 'sermon-target-language-policy-v2', 'targetLocale': 'zh-Hans',
                  'languageReview': {'pluginId': helper.PLUGIN_ID, 'requiredChecks': helper.REQUIRED},
                  'scripture': {'editionId': None, 'citationUseStatus': 'pending',
                                'quoteCheckPolicy': 'references_only', 'referenceStyle': 'x'}}
        with self.assertRaisesRegex(ValueError, 'admitted_plugin_scripture_mismatch'):
            helper.review_group(policy, units(), group(REV), diagnostic_context={}, admitted_quotes=summary()['admitted'])


class FrozenPluginTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.baseline = json.loads(Path('config/target-language-policies/zh-Hans.json').read_text(encoding='utf-8'))

    def freeze(self):
        return helper.freeze_admitted_plugin(summary(), None, None, None, self.baseline, self.root / 'plugin.py')

    def test_frozen_plugin_carries_exactly_the_admitted_literals(self):
        self.freeze()
        facts = preflight._literals(self.root / 'plugin.py')
        self.assertIs(facts['DIAGNOSTIC_ADMITTED_QUOTES'], True)
        self.assertEqual(facts['ADMITTED_RECEIPT_SHA256'], summary()['receiptSha256'])
        self.assertEqual(facts['ADMITTED_QUOTES'], summary()['admitted'])
        self.assertEqual(facts['REQUIRED'], helper.REQUIRED)

    def test_frozen_policy_is_exact_quote_cuv_and_validates(self):
        policy = self.freeze()
        self.assertEqual(policy['scripture']['editionId'], 'CUV')
        self.assertEqual(policy['scripture']['quoteCheckPolicy'], 'source_bound_exact_quote')
        self.assertEqual(policy['scripture']['citationUseStatus'], 'project_source_reviewed')
        self.assertEqual(policy['languageReview']['pluginId'], helper.PLUGIN_ID)
        self.assertEqual(policy['componentSha256']['scripture'], policies.canonical_sha256(policy['scripture']))

    def test_freeze_refuses_to_overwrite_an_existing_plugin(self):
        self.freeze()
        with self.assertRaisesRegex(ValueError, 'new frozen plugin path'):
            self.freeze()

    def test_rule_preflight_emits_the_exact_sentence_for_the_translator(self):
        policy = self.freeze()
        facts = preflight._literals(self.root / 'plugin.py')
        request = {'sourceUnits': units()}
        plan = [{'translationGroupId': 'g1', 'sourceUnitIds': UNITS}]
        quotes = preflight._quoted_rules(facts, request, policy, plan)
        self.assertEqual([q['classification'] for q in quotes], ['admitted_direct_quote', 'admitted_partial_direct_quote'])
        self.assertEqual(quotes[0]['targetText'], REV)
        self.assertEqual(quotes[1]['targetText'], '也不冷也不热')
        self.assertEqual(quotes[0]['translationGroupId'], 'g1')
        self.assertEqual(quotes[0]['citationUseStatus'], 'project_source_reviewed')


if __name__ == '__main__':
    unittest.main()
