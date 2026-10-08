"""Real validators/plugins with synthetic model replies; no provider calls."""
import copy
from contextlib import contextmanager
import hashlib
import subprocess
import sys
import json
import unittest
from unittest.mock import patch

from scripts import codex_layer2_diagnostic as diagnostic
from scripts import cuv_scripture
from scripts import scripture_adjudication as adjudication
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
        target = cuv_scripture.CuvLibrary.from_path().lookup('REV 4:2-3')['text'].split('，', 1)[1]
        h.data.evidence['groups'][0]['targetUtterances'] = [target]
        h.data.evidence['groups'][0]['coverage'][0]['targetText'] = target
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

    def receipt(self):
        # Synthetic test receipt built from the pinned CUV text. It is never a human approval.
        h = self.helper
        text = cuv_scripture.CuvLibrary.from_path().lookup('REV 4:2-3')['text'].split('，', 1)[1]
        return {'schemaVersion': adjudication.SCHEMA, 'targetLocale': 'zh-Hans',
            'bindings': {'source.json': policies.canonical_sha256(h.source),
                         'anchor.json': policies.canonical_sha256(h.anchor),
                         'group-plan.json': policies.canonical_sha256(h.plan)},
            'decision': 'approved', 'decidedBy': 'synthetic test reviewer', 'decidedByRole': 'human_reviewer',
            'reviewedAt': '2026-10-08T00:00:00+00:00',
            'candidates': [{'candidateId': 'test-quote-1', 'sourceUnitIds': [h.anchor['sourceUnits'][0]['sourceUnitId']],
                'classification': 'partial_direct_quote', 'reference': 'REV 4:2-3', 'editionId': 'CUV', 'exactSentence': text}]}

    def freeze(self, receipt=None):
        h = self.helper
        return diagnostic.freeze_fixture(h.source, h.anchor, h.policy, h.plan, self.plugin, h.fixture,
            authorization_ref='isolated test', code_commit='a' * 40, translator_model='gpt-6.1-sol',
            scripture_classification='contains_direct_quotations',
            source_quotation_units=[h.anchor['sourceUnits'][0]['sourceUnitId']],
            scripture_adjudication=receipt or self.receipt())

    def mismatched_receipt(self, change):
        value = self.receipt()
        row = value['candidates'][0]
        if change == 'reference':
            row.update(reference='REV 3:16', exactSentence=cuv_scripture.CuvLibrary.from_path().lookup('REV 3:16')['text'])
        elif change == 'text':
            row.update(classification='partial_direct_quote', exactSentence=row['exactSentence'][:4])
        elif change == 'classification':
            row['classification'] = 'direct_quote'
        else:
            row.update(classification=change, reference=None, editionId=None, exactSentence=None)
        return value

    def test_mismatched_receipt_payload_refused_before_freezing(self):
        for change in ('reference', 'text', 'classification', 'speaker_paraphrase', 'reference_only'):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'payload differs|exact_sentence_mismatch'):
                self.freeze(self.mismatched_receipt(change))
            self.assertFalse(self.helper.fixture.exists())
            self.assertEqual(self.helper.calls, [])

    def test_matching_full_quote_and_split_parts_are_admitted(self):
        h = self.helper
        text = cuv_scripture.CuvLibrary.from_path().lookup('REV 3:15')['text']
        bindings = copy.deepcopy(self.bindings)
        quote = bindings['quotes'][0]
        quote['reference'] = 'REV.3:15'
        original = quote['parts'][0]
        middle = len(original['englishExcerpt']) // 2
        quote['parts'] = []
        for start, end, target in [(0, middle, text[:4]), (middle + 1, original['englishEndOffset'], text[4:])]:
            part = copy.deepcopy(original)
            english = original['englishExcerpt'][start:end]
            part.update(englishStartOffset=start, englishEndOffset=end, englishExcerpt=english,
                        englishExcerptSha256=quotes.text_hash(english), targetText=target,
                        targetTextSha256=quotes.text_hash(target))
            quote['parts'].append(part)
        provenance = h.root / 'full-quote-target.json'
        provenance.write_text(json.dumps(text, ensure_ascii=False))
        bindings['provenance'].update(artifactPath=str(provenance), artifactSha256=policies.file_sha256(provenance))
        self.plugin = h.root / 'full-quote-plugin.py'
        h.policy = quotes.freeze_quote_plugin(h.source, h.anchor, h.plan, h.policy, bindings, self.plugin)
        receipt = self.receipt()
        receipt['candidates'][0].update(classification='direct_quote', reference='REV 3:15', exactSentence=text)
        wrong_classification = copy.deepcopy(receipt)
        wrong_classification['candidates'][0]['classification'] = 'partial_direct_quote'
        with self.assertRaisesRegex(ValueError, 'payload differs'):
            self.freeze(wrong_classification)
        self.freeze(receipt)
        diagnostic.load_fixture(h.fixture)

    def test_load_rechecks_payload_even_with_consistent_fixture_hashes(self):
        self.freeze()
        h = self.helper
        manifest_path = h.fixture / 'fixture-manifest.json'
        context_path = h.fixture / 'diagnostic-context.json'
        for change in ('reference', 'text', 'speaker_paraphrase'):
            value = self.mismatched_receipt(change)
            data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            (h.fixture / 'scripture-adjudication.json').write_bytes(data)
            manifest = json.loads(manifest_path.read_text())
            manifest['scriptureAdjudication']['sha256'] = hashlib.sha256(data).hexdigest()
            manifest_path.write_text(json.dumps(manifest))
            context = json.loads(context_path.read_text())
            digest = policies.canonical_sha256(manifest)
            context.update(runId=digest, runConfigSha256=digest, storeSha256=digest)
            context_path.write_text(json.dumps(context))
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'payload differs'):
                h.invoke()
            self.assertEqual(h.calls, [])

    def test_delayed_freezer_preserves_the_winning_fixture(self):
        h = self.helper
        original_lock = diagnostic.work_lock
        snapshot = {}
        @contextmanager
        def delayed_lock(out):
            # Another caller completes after our exists check, before lock acquisition.
            with patch.object(diagnostic, 'work_lock', original_lock):
                self.freeze()
            snapshot.update({p.name: p.read_bytes() for p in h.fixture.iterdir()})
            with original_lock(out):
                yield
        second = self.receipt()
        second['decidedBy'] = 'another synthetic reviewer'
        with patch.object(diagnostic, 'work_lock', delayed_lock), self.assertRaisesRegex(ValueError, 'new directory'):
            self.freeze(second)
        self.assertEqual(snapshot, {p.name: p.read_bytes() for p in h.fixture.iterdir()})
        diagnostic.load_fixture(h.fixture)

    def test_fixture_cli_accepts_receipt_json(self):
        h = self.helper
        argv = [sys.executable, '-m', 'scripts.codex_layer2_diagnostic']
        for name, value in [('source', h.source), ('anchor', h.anchor), ('policy', h.policy),
                            ('group-plan', h.plan), ('scripture-adjudication', self.receipt())]:
            path = h.root / (name + '-input.json')
            path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            argv.extend(['--' + name, str(path)])
        argv.extend(['--plugin', str(self.plugin), '--out', str(h.fixture),
                     '--authorization-ref', 'synthetic test', '--code-commit', 'a' * 40,
                     '--translator-model', 'gpt-6.1-sol',
                     '--scripture-classification', 'contains_direct_quotations',
                     '--source-quotation-unit', h.anchor['sourceUnits'][0]['sourceUnitId']])
        result = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('scriptureAdjudication', json.loads(result.stdout))
        diagnostic.load_fixture(h.fixture)

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
        # Without an adjudication receipt the freeze refuses before the annotation check.
        with self.assertRaisesRegex(ValueError, 'scripture_adjudication_required'):
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
