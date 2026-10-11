"""Synthetic compatibility proofs; no human or production acceptance claimed."""
import copy
import json
import unittest
from unittest.mock import patch

from scripts import sermon_strict_candidate_bridge as bridge
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_review_contracts as c
from scripts import produce_target_language_candidate as producer
from scripts import review_target_language_candidate as human
from scripts import prepare_target_language_speech_job as handoff
from tests import test_sermon_strict_layer2 as fixtures


class StrictBridgeTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.StrictAdapterTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.groups = copy.deepcopy(self.f.f.evidence['groups'])
        self.revisions = []
        with self.f.session():
            for group in self.groups:
                self.f.f.evidence['groups'][0] = group
                prepared = strict.prepare(*self.f.args, {k: group[k] for k in ('translationGroupId', 'sourceUnitIds')},
                                          rule_preflight=self.f.rule_preflight, rule_context=self.f.rule_context)
                root = self.f.root / group['translationGroupId']
                strict.generate(prepared, root, 'candidate', 'r1', 'fixture', self.f.transport)
                strict.review(prepared, root, 'candidate', 'r1', 'fixture', self.f.transport)
                self.revisions.append((root, 1))
        self.kw = dict(plugin_path=self.f.f.plugin_path, expected_plugin_sha256=self.f.f.plugin_sha)

    def compile(self):
        return bridge.compile_candidate(*self.f.args, self.revisions, **self.kw)

    def test_compiles_exact_text_into_public_schema_without_human_approval(self):
        result = self.compile()
        candidate = result['candidate']
        self.assertEqual(candidate['status'], 'machine_review_pass_human_review_pending')
        self.assertFalse(candidate['releaseEligible'])
        self.assertEqual(candidate['humanReview']['translation'], 'pending')
        self.assertEqual([g['targetUtterances'] for g in candidate['groups']],
                         [g['targetUtterances'] for g in self.groups])
        self.assertEqual(len(result['revisionBindings']), 2)
        self.assertEqual(len(self.f.calls), 4)
        source, anchor, policy, rubric = [c.decode_json(b) for b in self.f.args]
        with self.assertRaises(ValueError): producer.prepare_request(source, anchor, policy)
        with self.assertRaises(ValueError): handoff.validate_policy_binding(candidate, policy)
        with self.assertRaises(ValueError): human.build_worksheet(source, anchor, candidate, policy)
        with self.assertRaises(ValueError): handoff.validate_target_candidate(source, anchor, candidate)
        handoff.validate_policy_binding(candidate, policy, strict_rubric=rubric)

    def test_explicit_human_worksheet_preserves_full_chain_and_rejects_changed_text(self):
        pending = self.compile()['candidate']
        source, anchor, policy, rubric = [c.decode_json(b) for b in self.f.args]
        worksheet = human.build_worksheet(source, anchor, pending, policy, strict_rubric=rubric)
        with self.assertRaises(ValueError):
            human.approve_worksheet(source, anchor, pending, policy, worksheet, strict_rubric=rubric)
        reviewed = human.apply_batch_approval(worksheet, reviewer='Synthetic fixture reviewer',
            reviewed_at='2026-09-30T00:00:00Z', evidence='Synthetic development fixture; not human acceptance')
        approved, receipt = human.approve_worksheet(source, anchor, pending, policy, reviewed, strict_rubric=rubric)
        result = bridge.validate_approved_chain(*self.f.args, self.revisions,
            candidate=approved, human_receipt=receipt, **self.kw)
        self.assertEqual(result['admissionStatus'], 'validated_only')
        self.assertEqual(result['executionAuthority'], 'none')
        # A machine waiver cannot stand in for the human receipt the strict gate records.
        with patch.object(handoff, 'validate_released_candidate',
                          return_value={'textPolicy': handoff.MACHINE_TEXT_POLICY}):
            with self.assertRaisesRegex(ValueError, 'strict_bridge_requires_human_receipt'):
                bridge.validate_approved_chain(*self.f.args, self.revisions,
                    candidate=approved, human_receipt=receipt, **self.kw)
        approved['groups'][0]['targetUtterances'][0] += ' changed'
        with self.assertRaisesRegex(ValueError, 'strict_bridge_public_candidate_changed'):
            bridge.validate_approved_chain(*self.f.args, self.revisions,
                candidate=approved, human_receipt=receipt, **self.kw)
        self.assertEqual(len(self.f.calls), 4)

    def test_missing_duplicate_or_reordered_groups_fail_existing_coverage_gate(self):
        original = list(self.revisions)
        for revisions in (original[:1], original[::-1], [original[0], original[0]]):
            with self.subTest(revisions=str(revisions)), self.assertRaises(ValueError):
                bridge.compile_candidate(*self.f.args, revisions, **self.kw)

    def test_changed_receipt_or_raw_provider_proof_is_rejected(self):
        root = self.revisions[0][0]
        path = root / 'reviewer.raw.json'
        original = path.read_bytes()
        changed = json.loads(original)
        changed['accounting']['modelCallId'] = 'other-call'
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'strict_raw_receipt_binding_changed'): self.compile()
        path.write_bytes(original)
        path = root / 'review-receipt.json'
        receipt = json.loads(path.read_bytes())
        receipt['modelCallId'] = 'other-call'
        receipt['receiptSha256'] = c.receipt_sha256(receipt)
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'strict_bridge_review_proof_changed'): self.compile()

    def test_source_bytes_and_plugin_identity_changes_fail_without_calls(self):
        with self.assertRaisesRegex(ValueError, 'strict_bridge_input_bytes_changed'):
            bridge.compile_candidate(self.f.args[0] + b' ', *self.f.args[1:], self.revisions, **self.kw)
        with self.assertRaises(ValueError):
            bridge.compile_candidate(*self.f.args, self.revisions,
                plugin_path=self.f.f.plugin_path, expected_plugin_sha256='0' * 64)
        self.assertEqual(len(self.f.calls), 4)

    def test_cached_terminal_envelope_must_match_fresh_response_requirements(self):
        root = self.revisions[0][0]
        for role in ('generator', 'reviewer'):
            path = root / (role + '.raw.json')
            original = path.read_bytes()
            for kind in ('length', 'content_filter', 'multiple_choices', 'missing_choice', 'invalid_choice'):
                with self.subTest(role=role, corruption=kind):
                    row = json.loads(original)
                    if kind == 'multiple_choices': row['response']['choices'] *= 2
                    elif kind == 'missing_choice': row['response']['choices'] = []
                    elif kind == 'invalid_choice': row['response']['choices'] = [None]
                    else: row['response']['choices'][0]['finish_reason'] = kind
                    path.write_text(json.dumps(row))
                    with self.assertRaises(c.ContractError): self.compile()
                    path.write_bytes(original)
        self.assertEqual(len(self.f.calls), 4)

    def test_plugin_cannot_change_an_earlier_group_after_it_was_validated(self):
        original=producer.run_language_plugin
        def mutate(*args,**kwargs):
            result=original(*args,**kwargs)
            path=self.revisions[0][0]/'candidate.json'
            path.write_bytes(path.read_bytes()+b' ')
            return result
        with patch.object(producer,'run_language_plugin',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'strict_bridge_snapshot_changed'):self.compile()

    def test_symlinked_private_proof_is_rejected(self):
        root = self.revisions[0][0]
        path = root / 'review-receipt.json'
        target = root / 'other.json'
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaises((ValueError, OSError)): self.compile()


if __name__ == '__main__': unittest.main()
