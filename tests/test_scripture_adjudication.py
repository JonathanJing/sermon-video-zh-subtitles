"""Adjudication receipt gate: every refusal path, against the real pinned CUV text.

Receipts here are synthetic test inputs. They exercise validation only and never
represent a human decision.
"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts import cuv_scripture
from scripts import scripture_adjudication as adjudication
from scripts import scripture_editions

UNITS = ['u-quote-1', 'u-quote-2']
BINDINGS = {'source.json': 'a' * 64, 'anchor.json': 'b' * 64, 'group-plan.json': 'c' * 64}
LIBRARY = cuv_scripture.CuvLibrary.from_path()
REV = LIBRARY.lookup('REV 4:2-3')['text']
REV316 = LIBRARY.lookup('REV 3:16')['text']
# A whole reading of John 3:16 in the pinned public-domain English wording.
READ_3_16 = ('For God so loved the world, that he gave his one and only Son, that whoever believes in him '
             'should not perish, but have eternal life.')


def receipt(**overrides):
    base = {'schemaVersion': adjudication.SCHEMA, 'targetLocale': 'zh-Hans', 'bindings': dict(BINDINGS),
            'decision': 'approved', 'decidedBy': 'synthetic test reviewer', 'decidedByRole': 'human_reviewer',
            'reviewedAt': '2026-10-08T00:00:00+00:00',
            'candidates': [
                {'candidateId': 'q1', 'sourceUnitIds': [UNITS[0]], 'classification': 'direct_quote',
                 'reference': 'REV 4:2-3', 'editionId': 'CUV', 'exactSentence': REV},
                {'candidateId': 'q2', 'sourceUnitIds': [UNITS[1]], 'classification': 'partial_direct_quote',
                 'reference': 'REV 3:16', 'editionId': 'CUV', 'exactSentence': '也不冷也不热'}]}
    base.update(overrides)
    return base


def validate(value, **kwargs):
    arguments = dict(target_locale='zh-Hans', bindings=BINDINGS, flagged_units=UNITS, library=LIBRARY)
    arguments.update(kwargs)
    return adjudication.validate_receipt(value, **arguments)


def reason(value, **kwargs):
    try:
        validate(value, **kwargs)
    except adjudication.AdjudicationError as exc:
        return str(exc)
    raise AssertionError('receipt was admitted')


class ReceiptValidationTests(unittest.TestCase):
    def test_complete_approved_receipt_is_admitted_with_exact_text_hashes(self):
        summary = validate(receipt())
        self.assertEqual(summary['coveredUnits'], sorted(UNITS))
        self.assertEqual({q['candidateId'] for q in summary['quotes']}, {'q1', 'q2'})
        self.assertEqual(summary['quotes'][0]['canonicalRef'], 'REV 4:2-3')
        self.assertEqual(len(summary['receiptSha256']), 64)

    def test_machine_pending_and_rejected_decisions_are_refused(self):
        self.assertEqual(reason(receipt(decision='pending')), 'decision_not_approved')
        self.assertEqual(reason(receipt(decision='rejected')), 'decision_not_approved')

    def test_unknown_role_or_missing_signature_is_refused(self):
        self.assertEqual(reason(receipt(decidedByRole='machine')), 'decided_by_role_invalid')
        self.assertEqual(reason(receipt(decidedByRole='model')), 'decided_by_role_invalid')
        self.assertEqual(reason(receipt(decidedBy='  ')), 'decided_by_missing')

    def test_machine_adjudicator_receipt_is_admitted_only_when_the_generator_reproduces_it(self):
        from scripts import scripture_machine_adjudication as machine
        rows = [{'sourceUnitId': 'r1', 'english': f'John 3:16 says, {READ_3_16}', 'start': 0.0, 'end': 1.0},
                {'sourceUnitId': 'r2', 'english': 'Amen.', 'start': 1.0, 'end': 2.0}]
        inputs = {'source.json': {'source': {'sourceId': 'synthetic'}}, 'anchor.json': {'sourceUnits': rows},
                  'group-plan.json': [{'translationGroupId': 'g1', 'sourceUnitIds': ['r1', 'r2']}]}
        generated, _ = machine.adjudicate(inputs['source.json'], inputs['anchor.json'], inputs['group-plan.json'],
                                          target_locale='zh-Hans', flagged_units=['r1'], library=LIBRARY)
        summary = validate(generated, bindings=generated['bindings'], flagged_units=['r1'], machine_inputs=inputs)
        self.assertEqual((summary['decidedByRole'], summary['adjudicationKind'], summary['humanApproval']),
                         ('machine_adjudicator', 'machine', False))
        self.assertTrue(summary['generator']['reproduced'])
        # A hand-written receipt labelled machine, with a classification the generator never emits, is refused.
        self.assertEqual(reason(receipt(decidedByRole='machine_adjudicator',
                                        decidedBy='scripture_machine_adjudication v x')), 'machine_inputs_required')
        handwritten = receipt(decidedByRole='machine_adjudicator', decidedBy='scripture_machine_adjudication v x',
                              bindings=generated['bindings'])
        self.assertEqual(reason(handwritten, bindings=generated['bindings'], flagged_units=UNITS, machine_inputs=inputs),
                         'machine_receipt_not_reproduced')
        human = validate(receipt())
        self.assertEqual((human['adjudicationKind'], human['humanApproval'], human['generator']), ('human', True, None))

    def test_a_frozen_machine_receipt_survives_a_later_generator(self):
        from unittest import mock
        from scripts import scripture_machine_adjudication as machine
        rows = [{'sourceUnitId': 'r1', 'english': f'John 3:16 says, {READ_3_16}', 'start': 0.0, 'end': 1.0},
                {'sourceUnitId': 'r2', 'english': 'Amen.', 'start': 1.0, 'end': 2.0}]
        inputs = {'source.json': {'source': {'sourceId': 'synthetic'}}, 'anchor.json': {'sourceUnits': rows},
                  'group-plan.json': [{'translationGroupId': 'g1', 'sourceUnitIds': ['r1', 'r2']}]}
        generated, basis = machine.adjudicate(inputs['source.json'], inputs['anchor.json'], inputs['group-plan.json'],
                                              target_locale='zh-Hans', flagged_units=['r1'], library=LIBRARY)
        check = dict(bindings=generated['bindings'], flagged_units=['r1'], machine_inputs=inputs)
        frozen = {'reproduced': True, 'version': basis['version'], 'implementationSha256': basis['implementationSha256'],
                  'signatureCurrent': True}
        later = {'VERSION': 'later', 'implementation_sha256': lambda: 'f' * 64,
                 'adjudicate': mock.Mock(side_effect=AssertionError('a frozen run is never re-run by a later generator'))}
        with mock.patch.multiple(machine, **later):
            summary = validate(generated, frozen_generator=frozen, **check)
            self.assertEqual((summary['generator']['frozenAdmission'], summary['generator']['reproduced'],
                              summary['generator']['version'], summary['generator']['current']['version']),
                             (True, False, basis['version'], 'later'))
            # Without the frozen record, or with a record for another generator, the later generator re-runs.
            with self.assertRaises(AssertionError):
                validate(generated, **check)
            self.assertEqual(reason(generated, frozen_generator=dict(frozen, version='other'), **check),
                             'frozen_generator_mismatch')
            # A record that never reproduced the receipt freezes nothing.
            with self.assertRaises(AssertionError):
                validate(generated, frozen_generator=dict(frozen, reproduced=False), **check)
        # The same generator still proves the receipt by reproducing it, frozen record or not.
        summary = validate(generated, frozen_generator=frozen, **check)
        self.assertTrue(summary['generator']['reproduced'])
        forged = dict(generated, candidates=[dict(generated['candidates'][0], classification='partial_direct_quote',
                                                  exactSentence=generated['candidates'][0]['exactSentence'][:4])])
        self.assertEqual(reason(forged, frozen_generator=frozen, **check), 'machine_receipt_not_reproduced')

    def test_bad_timestamp_and_schema_are_refused(self):
        self.assertEqual(reason(receipt(reviewedAt='yesterday')), 'reviewed_at_invalid')
        bad = receipt()
        bad['extra'] = True
        self.assertEqual(reason(bad), 'receipt_schema')

    def test_binding_to_a_different_source_anchor_or_plan_is_refused(self):
        changed = receipt(bindings={**BINDINGS, 'anchor.json': 'd' * 64})
        self.assertEqual(reason(changed), 'receipt_binding_changed')

    def test_locale_without_a_pinned_edition_is_refused(self):
        self.assertEqual(reason(receipt(targetLocale='fr'), target_locale='fr'), 'no_pinned_edition_for_locale')

    @unittest.skipUnless((scripture_editions.DOWNLOAD_DIR / 'NKRV-1998.json').is_file(), 'NKRV-1998 file not present')
    def test_ko_quote_is_admitted_and_keeps_its_pending_verification_status(self):
        text = scripture_editions.load('NKRV-1998').lookup('REV 3:16')['text']
        candidates = [
            {'candidateId': 'k1', 'sourceUnitIds': [UNITS[0]], 'classification': 'direct_quote',
             'reference': 'REV 3:16', 'editionId': 'NKRV-1998', 'exactSentence': text},
            {'candidateId': 'k2', 'sourceUnitIds': [UNITS[1]], 'classification': 'speaker_paraphrase',
             'reference': None, 'editionId': None, 'exactSentence': None}]
        summary = validate(receipt(targetLocale='ko', candidates=candidates), target_locale='ko')
        self.assertEqual([q['editionVerification'] for q in summary['quotes']],
                         [scripture_editions.PENDING])

    def test_altered_exact_sentence_is_refused(self):
        bad = receipt()
        bad['candidates'][0]['exactSentence'] = REV.replace('碧玉', '翡翠', 1)
        self.assertNotEqual(bad['candidates'][0]['exactSentence'], REV)
        self.assertEqual(reason(bad), 'exact_sentence_mismatch')

    def test_partial_quote_must_be_an_exact_substring_of_the_edition(self):
        bad = receipt()
        bad['candidates'][1]['exactSentence'] = '也不冷也不烫'
        self.assertEqual(reason(bad), 'exact_sentence_mismatch')

    def test_direct_quote_must_be_the_whole_verse_text(self):
        bad = receipt()
        bad['candidates'][0]['exactSentence'] = REV[:-1]
        self.assertEqual(reason(bad), 'exact_sentence_mismatch')

    def test_wrong_edition_or_unknown_reference_is_refused(self):
        self.assertEqual(reason(receipt(candidates=[
            {**receipt()['candidates'][0], 'editionId': 'NIV'}, receipt()['candidates'][1]])), 'edition_mismatch')
        self.assertEqual(reason(receipt(candidates=[
            {**receipt()['candidates'][0], 'reference': 'NoSuchBook 1:1'}, receipt()['candidates'][1]])),
            'exact_sentence_mismatch')

    def test_non_quote_cannot_carry_an_edition_claim(self):
        candidates = [{'candidateId': 'p1', 'sourceUnitIds': [UNITS[0]], 'classification': 'speaker_paraphrase',
                       'reference': None, 'editionId': 'CUV', 'exactSentence': None},
                      receipt()['candidates'][1]]
        self.assertEqual(reason(receipt(candidates=candidates)), 'non_quote_has_edition')

    def test_speaker_paraphrase_is_admitted_without_quotation_claims(self):
        candidates = [{'candidateId': 'p1', 'sourceUnitIds': [UNITS[0]], 'classification': 'speaker_paraphrase',
                       'reference': None, 'editionId': None, 'exactSentence': None},
                      receipt()['candidates'][1]]
        summary = validate(receipt(candidates=candidates))
        self.assertEqual([q['candidateId'] for q in summary['quotes']], ['q2'])

    def test_coverage_must_match_flagged_units_exactly(self):
        missing = receipt(candidates=receipt()['candidates'][:1])
        self.assertEqual(reason(missing), 'coverage_mismatch')
        extra = receipt()
        extra['candidates'].append({'candidateId': 'q3', 'sourceUnitIds': ['u-unflagged'],
            'classification': 'speaker_paraphrase', 'reference': None, 'editionId': None, 'exactSentence': None})
        self.assertEqual(reason(extra), 'coverage_mismatch')

    def test_unit_covered_twice_or_candidate_id_repeated_is_refused(self):
        twice = receipt()
        twice['candidates'][1]['sourceUnitIds'] = [UNITS[0]]
        self.assertEqual(reason(twice), 'unit_covered_twice')
        repeated = receipt()
        repeated['candidates'][1]['candidateId'] = 'q1'
        self.assertEqual(reason(repeated), 'candidate_id_repeated')

    def test_unknown_classification_is_refused(self):
        bad = receipt()
        bad['candidates'][0]['classification'] = 'probably_a_quote'
        self.assertEqual(reason(bad), 'classification_invalid')


class ReceiptAdmissionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)

    def write(self, value, name='scripture-adjudication.json'):
        data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        (self.directory / name).write_bytes(data)
        return {'path': name, 'sha256': hashlib.sha256(data).hexdigest()}

    def admit(self, manifest):
        return adjudication.require_admitted(manifest, self.directory, target_locale='zh-Hans',
            bindings=BINDINGS, flagged_units=UNITS)

    def test_missing_manifest_entry_refuses_before_any_dispatch(self):
        with self.assertRaisesRegex(ValueError, 'scripture_adjudication_required'):
            self.admit({'scriptureClassification': 'contains_direct_quotations'})

    def test_changed_receipt_file_is_refused(self):
        entry = self.write(receipt())
        (self.directory / entry['path']).write_text('{"tampered": true}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'receipt_file_changed'):
            self.admit({'scriptureAdjudication': entry})

    def test_receipt_path_must_stay_inside_the_fixture_directory(self):
        entry = self.write(receipt(), name='scripture-adjudication.json')
        escaping = {'path': '../scripture-adjudication.json', 'sha256': entry['sha256']}
        with self.assertRaisesRegex(ValueError, 'receipt_file_missing'):
            self.admit({'scriptureAdjudication': escaping})

    def test_admitted_receipt_round_trips_from_the_fixture_directory(self):
        entry = self.write(receipt())
        summary = self.admit({'scriptureAdjudication': entry})
        self.assertEqual(summary['coveredUnits'], sorted(UNITS))
        self.assertEqual(summary['receiptSha256'], adjudication.receipt_sha256(receipt()))


if __name__ == '__main__':
    unittest.main()
