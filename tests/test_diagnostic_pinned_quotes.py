"""Real validators/plugins with synthetic model replies; no provider calls."""
import copy
import json
import unittest
from unittest.mock import patch

from scripts import codex_layer2_diagnostic as diagnostic
from scripts import target_language_policy as policies
from scripts import target_language_rule_preflight as preflight
from scripts.language_review_plugins import diagnostic_pinned_quotes as quotes
from tests import test_codex_layer2_diagnostic as chain_tests


class PinnedQuoteTests(unittest.TestCase):
    def setUp(self):
        self.helper = chain_tests.DiagnosticChainTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        h = self.helper
        first = h.anchor['sourceUnits'][0]
        target = h.data.evidence['groups'][0]['targetUtterances'][0]
        provenance = h.root / 'pending-local-target.json'
        provenance.write_text(json.dumps(h.data.evidence, ensure_ascii=False))
        self.bindings = {'schemaVersion': quotes.SCHEMA,
            'sourceSha256': policies.canonical_sha256(h.source),
            'anchorSha256': policies.canonical_sha256(h.anchor),
            'groupPlanSha256': policies.canonical_sha256(h.plan), 'targetLocale': 'zh-Hans',
            'editionId': quotes.EDITION, 'citationUseStatus': 'pending',
            'provenance': {'status': 'pending', 'artifactSha256': policies.file_sha256(provenance), 'artifactPath': str(provenance)},
            'quotes': [{'translationGroupId': 'g1', 'sourceUnitIds': h.plan[0]['sourceUnitIds'],
                'reference': 'REV.4:2-3', 'parts': [{'sourceUnitId': first['sourceUnitId'],
                    'englishStartOffset': 0, 'englishEndOffset': len(first['english']),
                    'englishExcerpt': first['english'], 'englishExcerptSha256': quotes.text_hash(first['english']),
                    'targetText': target, 'targetTextSha256': quotes.text_hash(target)}]}]}
        self.plugin = h.root / 'diagnostic-pinned-plugin.py'
        h.policy = quotes.freeze_quote_plugin(h.source, h.anchor, h.plan, h.policy, self.bindings, self.plugin)

    def freeze(self):
        h = self.helper
        return diagnostic.freeze_fixture(h.source, h.anchor, h.policy, h.plan, self.plugin, h.fixture,
            authorization_ref='isolated test', code_commit='a' * 40, translator_model='gpt-6.1-sol',
            scripture_classification='contains_direct_quotations',
            source_quotation_units=[h.anchor['sourceUnits'][0]['sourceUnitId']])

    def test_complete_machine_chain_pending_citation_never_enters_formal(self):
        h = self.helper
        self.assertFalse(policies.validate_policy(h.policy)['productionPolicyReady'])
        self.assertIn('scripture_policy_pending', policies.validate_policy(h.policy)['unresolved'])
        self.freeze()
        report = h.invoke()
        self.assertEqual(len(h.calls), 4)
        self.assertFalse(report['productionEligible'] or report['humanApproval'])
        candidate = json.loads((h.out / 'diagnostic-candidate.json').read_text())
        self.assertEqual(candidate['candidate']['humanReview']['translation'], 'pending')
        rules = json.loads((h.out / 'rule-preflight.json').read_text())['modelRules']
        self.assertEqual(rules['scripture']['citationUseStatus'], 'pending')
        self.assertEqual(rules['exactQuotes'][0]['classification'], 'diagnostic_pinned_excerpt')
        self.assertEqual(h.invoke(process=lambda *_a, **_kw: self.fail('resume model call')), report)

    def test_span_hash_group_plan_provenance_and_quote_annotation_tampering_blocked(self):
        h = self.helper
        request = {'sourceUnits': h.anchor['sourceUnits'], 'englishSourcePackageJsonSha256': self.bindings['sourceSha256'],
                   'anchorManifestSha256': self.bindings['anchorSha256']}
        for change in ('span', 'group', 'provenance'):
            bad = copy.deepcopy(self.bindings)
            if change == 'span': bad['quotes'][0]['parts'][0]['englishStartOffset'] = 1
            if change == 'group': bad['groupPlanSha256'] = 'b' * 64
            if change == 'provenance': bad['provenance']['status'] = 'approved'
            with self.subTest(change=change), self.assertRaises(ValueError):
                quotes.validate_bindings(bad, request, h.policy, h.plan)
        with self.assertRaisesRegex(ValueError, 'quotation annotation'):
            diagnostic.freeze_fixture(h.source, h.anchor, h.policy, h.plan, self.plugin, h.fixture,
                authorization_ref='test', code_commit='a' * 40, scripture_classification='contains_direct_quotations')

    def test_plugin_rejects_truncated_reordered_duplicated_leaked_and_reference_metadata(self):
        self.freeze()
        *_, context, _manifest = diagnostic.load_fixture(self.helper.fixture)
        h = self.helper
        text = self.bindings['quotes'][0]['parts'][0]['targetText']
        def checked(target, group_id='g1', units=None):
            source_units = units or [h.anchor['sourceUnits'][0]]
            group = {'translationGroupId': group_id, 'sourceUnitIds': [u['sourceUnitId'] for u in source_units],
                'targetText': target, 'targetUtterances': [target],
                'englishSourcePackageJsonSha256': self.bindings['sourceSha256']}
            return quotes.review_group(h.policy, source_units, group, diagnostic_context=context,
                                       bindings=self.bindings)[-1]['status']
        self.assertEqual(checked(text), 'pass')
        for target in (text[:-1], text + text, text + ' REV.4:2-3', text + ' 4:2'):
            self.assertEqual(checked(target), 'fail')
        self.assertEqual(checked(text, 'g2', [h.anchor['sourceUnits'][1]]), 'fail')

    def test_three_locales_run_actual_surface_and_integrity_checks(self):
        self.freeze()
        *_, context, _manifest = diagnostic.load_fixture(self.helper.fixture)
        h = self.helper
        for locale, text in [('zh-Hans', '要记得起初的爱。'), ('ko', '처음 사랑을 기억하세요.'), ('es', 'Recuerda el primer amor.')]:
            policy, bindings = copy.deepcopy(h.policy), copy.deepcopy(self.bindings)
            policy['targetLocale'] = bindings['targetLocale'] = locale
            part = bindings['quotes'][0]['parts'][0]
            part.update(targetText=text, targetTextSha256=quotes.text_hash(text))
            group = {'translationGroupId': 'g1', 'sourceUnitIds': h.plan[0]['sourceUnitIds'],
                'targetText': text, 'targetUtterances': [text], 'englishSourcePackageJsonSha256': bindings['sourceSha256']}
            checks = quotes.review_group(policy, [h.anchor['sourceUnits'][0]], group,
                                        diagnostic_context=context, bindings=bindings)
            self.assertEqual([r['checkId'] for r in checks], quotes.REQUIRED)
            self.assertTrue(all(r['status'] == 'pass' for r in checks), (locale, checks))

    def test_two_fragments_keep_order_and_provenance_cannot_be_invented(self):
        self.freeze()
        *_, context, _manifest = diagnostic.load_fixture(self.helper.fixture)
        h = self.helper
        bindings = copy.deepcopy(self.bindings)
        original = bindings['quotes'][0]['parts'][0]
        english, target = original['englishExcerpt'], original['targetText']
        middle = len(english) // 2
        parts = []
        for start, end, fragment in [(0, middle, target[:2]), (middle, len(english), target[2:])]:
            part = copy.deepcopy(original)
            part.update(englishStartOffset=start, englishEndOffset=end, englishExcerpt=english[start:end],
                englishExcerptSha256=quotes.text_hash(english[start:end]), targetText=fragment,
                targetTextSha256=quotes.text_hash(fragment))
            parts.append(part)
        bindings['quotes'][0]['parts'] = parts
        group = {'translationGroupId': 'g1', 'sourceUnitIds': h.plan[0]['sourceUnitIds'],
            'targetText': target[2:] + target[:2], 'targetUtterances': [target[2:] + target[:2]],
            'englishSourcePackageJsonSha256': bindings['sourceSha256']}
        self.assertEqual(quotes.review_group(h.policy, [h.anchor['sourceUnits'][0]], group,
            diagnostic_context=context, bindings=bindings)[-1]['status'], 'fail')
        bad = copy.deepcopy(self.bindings)
        part = bad['quotes'][0]['parts'][0]
        part.update(targetText='虚构测试片段', targetTextSha256=quotes.text_hash('虚构测试片段'))
        with self.assertRaisesRegex(ValueError, 'absent from pending provenance'):
            quotes.freeze_quote_plugin(h.source, h.anchor, h.plan, h.policy, bad, h.root / 'other-plugin.py')


if __name__ == '__main__':
    unittest.main()
