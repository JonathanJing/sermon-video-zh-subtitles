"""Focused D4 developer checks; all production boundary checks are mocked."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from scripts import sermon_review_contracts as c
from scripts import sermon_review_gate as g
from scripts import target_language_policy as policy

FIXTURES = Path(__file__).resolve().parent / 'fixtures/rqc'
NOW = '2026-09-30T00:00:00Z'


def load(name):
    return json.loads((FIXTURES / (name + '.json')).read_text())


def artifact(name, value):
    return g.JsonArtifact(name, c.canonical_bytes(value))


def seal(review):
    review['receiptSha256'] = c.receipt_sha256(review)
    return review


def fixture():
    rubric = load('rubric')
    draft = load('legacy-policy-v2')
    draft.pop('componentSha256')
    draft.update(schemaVersion=policy.POLICY_V3, reviewMode='strict_verifier')
    draft['translator']['promptVersion'] = 'astra-strict-generator-v1'
    draft['reviewer']['promptVersion'] = 'sol-strict-verifier-v1'
    rubric['requiredLanguagePluginChecks'] = draft['languageReview']['requiredChecks']
    draft['reviewContract'] = dict(rubricCanonicalJsonSha256=c.canonical_sha256(rubric),
        reviewReceiptSchemaVersion='sermon-review-receipt-v1',
        candidateRevisionSchemaVersion='sermon-candidate-revision-v1',
        inputManifestSchemaVersion='sermon-review-input-manifest-v1', revisionGranularity='translation_group')
    strict = policy.freeze_strict_policy(draft, rubric)
    materials = tuple(artifact(name, {'synthetic': name}) for name in
                      ('englishSource', 'anchor', 'context', 'generation', 'review-evidence', 'public-candidate', 'human'))
    materials += (artifact('policy', strict),)
    mapping = {a.artifact_id: a for a in materials}
    candidate_artifact = g.JsonArtifact('candidate', (FIXTURES / 'candidate-artifact.json').read_bytes())
    rubric_artifact = artifact('rubric', rubric)
    candidate = load('candidate-revision')
    for name, prefix in [('englishSource', 'sourcePackage'), ('anchor', 'anchor'), ('policy', 'policy')]:
        ref = mapping[name].reference()
        candidate[prefix + 'Sha256'] = ref['canonicalJsonSha256']
        candidate[prefix + 'BytesSha256'] = ref['fileBytesSha256']
    candidate['generationReceiptRef'] = mapping['generation'].reference()
    manifest = load('input-manifest')
    review = load('review-pass')
    for row in (manifest, review):
        for key in ('sourcePackageSha256', 'anchorSha256', 'policySha256'):
            row[key] = candidate[key]
        row['rubricSha256'] = c.canonical_sha256(rubric)
    for name in manifest['materialRefs']:
        manifest['materialRefs'][name] = (candidate_artifact if name == 'candidate' else
            rubric_artifact if name == 'rubric' else mapping[name]).reference()
    review['reviewerInputManifestSha256'] = c.canonical_sha256(manifest)
    review['evidenceRefs'] = [mapping['review-evidence'].reference()]
    for check in review['checks']:
        check['evidenceRefs'] = review['evidenceRefs']
    seal(review)
    current = g.CurrentState('8' * 64, candidate['targetLocale'], c.canonical_sha256(candidate),
        candidate['sourceIdentitySha256'], candidate['sourcePackageSha256'], candidate['anchorSha256'],
        candidate['policySha256'], c.canonical_sha256(rubric), (c.canonical_sha256(review),), False, False)
    return g.GateSnapshot(current, artifact('revision', candidate), candidate_artifact, rubric_artifact,
        (g.ReviewEvidence(artifact('review', review), artifact('input', manifest)),), materials)


def checks(snapshot, **changes):
    return replace(g.BoundaryChecks(g.snapshot_sha256(snapshot), True, True, True, True, 'valid', ('human',)), **changes)


def evaluate(snapshot, boundary=None):
    return g.evaluate_gate(snapshot, gate_decision_id='gate-1', created_at=NOW,
                           boundary_checks=boundary if boundary is not None else checks(snapshot))


def change_review(snapshot, mutate, *, inventory=True):
    row = c.decode_json(snapshot.reviews[0].receipt.data)
    mutate(row)
    seal(row)
    evidence = replace(snapshot.reviews[0], receipt=artifact('review', row))
    current = replace(snapshot.current, review_receipt_sha256s=(c.canonical_sha256(row),)) if inventory else snapshot.current
    return replace(snapshot, current=current, reviews=(evidence,))


class GateEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = fixture()

    def assert_blocked(self, snapshot, reason=None, boundary=None):
        result = evaluate(snapshot, boundary)
        self.assertEqual(result.decision['admissionStatus'], 'blocked')
        self.assertNotIn('prepare_layer3', result.decision['allowedNextActions'])
        self.assertNotIn('prepare_layer4', result.decision['allowedNextActions'])
        if reason: self.assertIn(reason, result.decision['reasonCodes'])
        c.validate_contract(result.decision)
        return result

    def test_pass_is_deterministic_and_only_admits_layer3(self):
        before = g.snapshot_sha256(self.snapshot)
        a = evaluate(self.snapshot)
        self.assertEqual(a, evaluate(self.snapshot))
        self.assertEqual(a.decision['admissionStatus'], 'admitted')
        self.assertEqual(a.decision['allowedNextActions'], ['prepare_layer3'])
        self.assertEqual(a.review_states[0].execution_status, 'succeeded')
        self.assertEqual(a.review_states[0].review_verdict, 'pass')
        self.assertEqual(g.snapshot_sha256(self.snapshot), before)
        c.validate_contract(a.decision)
        ref = a.decision['reviewReceiptRefs'][0]
        self.assertEqual(ref, self.snapshot.reviews[0].receipt.reference())
        self.assertNotEqual(ref['canonicalJsonSha256'], c.decode_json(self.snapshot.reviews[0].receipt.data)['receiptSha256'])

    def test_machine_pass_waits_for_human_and_missing_adapter_blocks(self):
        boundary = checks(self.snapshot, approval_status='missing', approval_artifact_ids=())
        result = evaluate(self.snapshot, boundary)
        self.assertEqual(result.decision['admissionStatus'], 'waiting_human')
        self.assertEqual(result.decision['reasonCodes'], ['human_approval_missing'])
        self.assertEqual(result.review_states[0].review_verdict, 'pass')
        result = g.evaluate_gate(self.snapshot, gate_decision_id='gate-1', created_at=NOW)
        self.assertEqual(result.decision['admissionStatus'], 'blocked')

    def test_known_content_failure_can_repair_before_public_assembly_and_human_review(self):
        def fail(row):
            row['reviewVerdict']='needs_rework';row['checks'][0]['result']='fail'
            issue=copy.deepcopy(load('review-fail')['issues'][0]);issue['evidenceRefs']=row['evidenceRefs']
            row['issues']=[issue]
        snap=change_review(self.snapshot,fail)
        boundary=checks(snap,public_candidate_ready=False,language_plugin_passed=False,
                        approval_status='missing',approval_artifact_ids=())
        result=evaluate(snap,boundary)
        self.assertEqual(result.decision['admissionStatus'],'blocked')
        self.assertIn('repair_translation',result.decision['allowedNextActions'])
        self.assertNotIn('stale_identity',result.decision['reasonCodes'])
        self.assertNotIn('prepare_layer3',result.decision['allowedNextActions'])
        stale=evaluate(snap,replace(boundary,policy_ready=False))
        self.assertEqual(stale.decision['allowedNextActions'],['reconcile'])

    def test_current_locale_source_candidate_policy_and_rubric_must_match(self):
        for key in ('candidate_revision_sha256', 'source_identity_sha256', 'source_package_sha256',
                    'anchor_sha256', 'policy_sha256', 'rubric_sha256', 'target_locale'):
            with self.subTest(key=key):
                state = replace(self.snapshot.current, **{key: 'ko' if key == 'target_locale' else 'f' * 64})
                self.assert_blocked(replace(self.snapshot, current=state))

    def test_actual_candidate_bytes_cannot_be_reserialized_or_changed(self):
        for data in (self.snapshot.candidate_artifact.data + b' ', b'{}'):
            snap = replace(self.snapshot, candidate_artifact=g.JsonArtifact('candidate', data))
            self.assert_blocked(snap, 'stale_identity')

    def test_all_material_refs_require_exact_bytes_including_rubric_and_generation(self):
        for name in ('englishSource', 'anchor', 'policy', 'context', 'generation', 'review-evidence'):
            with self.subTest(name=name):
                mats = tuple(replace(a, data=a.data + b' ') if a.artifact_id == name else a for a in self.snapshot.materials)
                self.assert_blocked(replace(self.snapshot, materials=mats), 'stale_identity')
        self.assert_blocked(replace(self.snapshot, rubric=replace(self.snapshot.rubric,
                            data=self.snapshot.rubric.data + b' ')), 'stale_identity')

    def test_review_wrong_binding_or_missing_hard_check_never_passes(self):
        mutations = [lambda r: r.update(targetLocale='ko'), lambda r: r.update(revisionId='r2'),
            lambda r: r.update(policySha256='a' * 64), lambda r: r.update(reviewedArtifactSha256='a' * 64),
            lambda r: r.update(reviewerInputManifestSha256='a' * 64), lambda r: r['checks'].pop(),
            lambda r: r['checks'].append(copy.deepcopy(r['checks'][0])),
            lambda r: r['checks'][0].update(result='fail'), lambda r: r['checks'][0].update(evidenceRefs=[]),
            lambda r: r['coverage'].update(assessedUnitIds=[], unassessedUnitIds=['source.001']),
            lambda r: r.update(targetUtterances=['must not be consumed'])]
        for i, mutation in enumerate(mutations):
            with self.subTest(i=i): self.assert_blocked(change_review(self.snapshot, mutation))

    def test_unresolved_minor_or_uncertain_issue_cannot_pass(self):
        for severity in ('minor', 'uncertain'):
            def mutate(row):
                issue = copy.deepcopy(load('review-fail')['issues'][0])
                issue['severity'] = severity
                issue['evidenceRefs'] = row['evidenceRefs']
                row['issues'] = [issue]
            self.assert_blocked(change_review(self.snapshot, mutate), 'review_not_assessed')

    def test_bad_json_hash_and_legacy_editor_result_are_not_content_failure(self):
        for data in (b'{bad', b'{"a":1,"a":2}', c.canonical_bytes(load('legacy-editor-result'))):
            snap = replace(self.snapshot, reviews=(replace(self.snapshot.reviews[0], receipt=g.JsonArtifact('review', data)),))
            result = self.assert_blocked(snap, 'review_not_assessed')
            self.assertIsNone(result.review_states[0].execution_status)
            self.assertEqual(result.review_states[0].review_verdict, 'not_assessed')
        snap = change_review(self.snapshot, lambda r: r.update(receiptSha256='a' * 64))
        data = c.decode_json(snap.reviews[0].receipt.data); data['receiptSha256'] = 'a' * 64
        snap = replace(snap, reviews=(replace(snap.reviews[0], receipt=artifact('review', data)),))
        self.assert_blocked(snap, 'review_not_assessed')

    def test_failed_cancelled_and_unknown_keep_execution_separate(self):
        for status in ('failed', 'cancelled', 'outcome_unknown'):
            def mutate(row):
                row.update(executionStatus=status, reviewVerdict='not_assessed', checks=[])
                row['coverage'].update(assessedUnitIds=[], unassessedUnitIds=['source.001'])
            snap = change_review(self.snapshot, mutate)
            result = self.assert_blocked(snap, 'review_not_assessed')
            self.assertEqual(result.review_states[0].execution_status, status)
            self.assertEqual(result.review_states[0].review_verdict, 'not_assessed')
            self.assertEqual(result.decision['allowedNextActions'], ['reconcile'] if status == 'outcome_unknown' else ['retry_review'])

    def test_content_failure_routes_repair_inconclusive_routes_human(self):
        def fail(row):
            row.update(reviewVerdict='needs_rework', issues=load('review-fail')['issues'])
            row['checks'][0]['result'] = 'fail'
            row['issues'][0]['evidenceRefs'] = row['evidenceRefs']
        result = self.assert_blocked(change_review(self.snapshot, fail), 'review_failed')
        self.assertIn('repair_translation', result.decision['allowedNextActions'])
        self.assertNotIn('retry_review', result.decision['allowedNextActions'])
        def inconclusive(row):
            row['reviewVerdict'] = 'inconclusive'; row['checks'][0]['result'] = 'not_assessed'
        result = self.assert_blocked(change_review(self.snapshot, inconclusive), 'review_inconclusive')
        self.assertEqual(result.decision['allowedNextActions'], ['request_human_review'])

    def test_new_source_ambiguity_overrides_prior_ready_source_and_content_repair(self):
        for severity in ('major', 'uncertain'):
            def ambiguity(row):
                content = copy.deepcopy(load('review-fail')['issues'][0])
                content['evidenceRefs'] = row['evidenceRefs']
                source = dict(content, issueId='new-source-ambiguity', reasonCode='source_ambiguity', severity=severity)
                row.update(reviewVerdict='needs_rework', issues=[content, source])
                row['checks'][0]['result'] = 'fail'
            snap = change_review(self.snapshot, ambiguity)
            result = self.assert_blocked(snap, 'source_not_ready')
            self.assertEqual(result.decision['allowedNextActions'], ['request_source_review'])
            self.assertEqual(result.review_states[0].execution_status, 'succeeded')
            self.assertEqual(result.review_states[0].review_verdict, 'needs_rework')

    def test_evidence_or_conflict_issue_never_authorizes_translation_repair(self):
        for reason, gate_reason in [('evidence_insufficient', 'review_inconclusive'),
                                   ('contradictory_reviews', 'review_conflict')]:
            def unresolved(row):
                issue = copy.deepcopy(load('review-fail')['issues'][0])
                issue.update(reasonCode=reason, severity='major', evidenceRefs=row['evidenceRefs'])
                row.update(reviewVerdict='needs_rework', issues=[issue])
                row['checks'][0]['result'] = 'fail'
            result = self.assert_blocked(change_review(self.snapshot, unresolved), gate_reason)
            self.assertEqual(result.decision['allowedNextActions'], ['request_human_review'])

    def test_conflicting_reviews_preserve_both_and_cannot_cherry_pick(self):
        def mutate(row):
            row['reviewId'] = 'other-review'; row['reviewAttemptId'] = 'other-attempt'
            row['reviewVerdict'] = 'inconclusive'; row['checks'][0]['result'] = 'not_assessed'
        second = change_review(self.snapshot, mutate).reviews[0]
        second = replace(second, receipt=replace(second.receipt, artifact_id='review-2'),
                         input_manifest=replace(second.input_manifest, artifact_id='input-2'))
        snap = replace(self.snapshot, reviews=self.snapshot.reviews + (second,),
            current=replace(self.snapshot.current, review_receipt_sha256s=self.snapshot.current.review_receipt_sha256s +
                            (second.receipt.reference()['canonicalJsonSha256'],)))
        result = self.assert_blocked(snap, 'review_conflict')
        self.assertEqual(len(result.review_states), 2)
        self.assertEqual(result.decision['allowedNextActions'], ['request_human_review'])
        self.assert_blocked(replace(snap, reviews=(self.snapshot.reviews[0],)), 'stale_identity')

    def test_review_inventory_pending_unknown_and_duplicates_block(self):
        for key in ('has_pending_review', 'has_unknown_outcome'):
            snap = replace(self.snapshot, current=replace(self.snapshot.current, **{key: True}))
            result = self.assert_blocked(snap, 'review_not_assessed')
            self.assertEqual(result.decision['allowedNextActions'], ['reconcile'])
        self.assert_blocked(replace(self.snapshot, reviews=()), 'review_not_assessed')
        self.assert_blocked(replace(self.snapshot, materials=self.snapshot.materials + (self.snapshot.materials[0],)), 'review_conflict')
        second = replace(self.snapshot.reviews[0], receipt=replace(self.snapshot.reviews[0].receipt, artifact_id='review-2'),
                         input_manifest=replace(self.snapshot.reviews[0].input_manifest, artifact_id='input-2'))
        self.assert_blocked(replace(self.snapshot, reviews=self.snapshot.reviews + (second,)), 'review_conflict')

    def test_policy_model_prompt_must_match_actual_review_not_just_each_other(self):
        snap = change_review(self.snapshot, lambda r: r.update(reviewerModelRequested='gpt-6-astra', reviewerModelActual='gpt-6-astra'))
        self.assert_blocked(snap, 'review_not_assessed')

    def test_execution_recovery_pass_does_not_erase_history(self):
        def failed(row):
            row.update(reviewId='failed-review', reviewAttemptId='failed-attempt',
                       executionStatus='failed', reviewVerdict='not_assessed', checks=[])
            row['coverage'].update(assessedUnitIds=[], unassessedUnitIds=['source.001'])
        failed = change_review(self.snapshot, failed).reviews[0]
        failed = replace(failed, receipt=replace(failed.receipt, artifact_id='failed-review'),
                         input_manifest=replace(failed.input_manifest, artifact_id='failed-input'))
        snap = replace(self.snapshot, reviews=(failed,) + self.snapshot.reviews,
            current=replace(self.snapshot.current, review_receipt_sha256s=
                (failed.receipt.reference()['canonicalJsonSha256'],) + self.snapshot.current.review_receipt_sha256s))
        result = evaluate(snap)
        self.assertEqual(result.decision['admissionStatus'], 'admitted')
        self.assertEqual([r.execution_status for r in result.review_states], ['failed', 'succeeded'])
        self.assertEqual(len(result.decision['reviewReceiptRefs']), 2)

    def test_repeated_review_artifact_is_blocked_with_valid_decision(self):
        self.assert_blocked(replace(self.snapshot, reviews=self.snapshot.reviews * 2), 'review_conflict')

    def test_public_candidate_plugin_source_and_approval_cannot_be_skipped(self):
        for key in ('source_ready', 'policy_ready', 'public_candidate_ready', 'language_plugin_passed'):
            with self.subTest(key=key):
                self.assert_blocked(self.snapshot, boundary=checks(self.snapshot, **{key: False}))
                self.assert_blocked(self.snapshot, boundary=checks(self.snapshot, **{key: 1}))
        self.assert_blocked(self.snapshot, 'approval_invalid', checks(self.snapshot, approval_status='invalid', approval_artifact_ids=()))
        self.assert_blocked(self.snapshot, 'approval_invalid', checks(self.snapshot, approval_artifact_ids=()))
        self.assert_blocked(self.snapshot, 'approval_invalid', checks(self.snapshot, approval_artifact_ids=('review',)))
        self.assert_blocked(self.snapshot, 'stale_identity', checks(self.snapshot, approval_status='machine_pass'))

    def test_stale_boundary_evidence_bound_to_all_materials_and_state(self):
        boundary = checks(self.snapshot)
        for name in ('public-candidate', 'human'):
            mats = tuple(replace(a, data=a.data + b' ') if a.artifact_id == name else a for a in self.snapshot.materials)
            self.assert_blocked(replace(self.snapshot, materials=mats), 'stale_identity', boundary)
        self.assert_blocked(replace(self.snapshot, current=replace(self.snapshot.current, state_revision='9' * 64)), 'stale_identity', boundary)

    def test_invalid_envelope_and_unknown_rubric_fail_closed(self):
        for snap in (replace(self.snapshot, current=replace(self.snapshot.current, has_unknown_outcome=0)),
                     replace(self.snapshot, candidate_revision=artifact('revision', {}))):
            with self.assertRaises(c.ContractError): evaluate(snap)
        rubric = c.decode_json(self.snapshot.rubric.data); rubric['requiredChecks'][0] = 'future'
        self.assert_blocked(replace(self.snapshot, rubric=artifact('rubric', rubric)), 'unknown_rubric')


class GateAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = fixture()
        self.held = False
        owner = self
        class Lock:
            def __enter__(self): owner.held = True
            def __exit__(self, *args): owner.held = False
        self.lock = Lock()
        self.calls = []

    def load(self):
        self.assertTrue(self.held); self.calls.append('load'); return self.snapshot

    def validate(self, snapshot):
        self.assertTrue(self.held); self.calls.append('validate'); return checks(snapshot)

    def commit(self, **kwargs):
        self.assertTrue(self.held); self.calls.append('commit')
        self.assertEqual(kwargs['expected_snapshot_sha256'], g.snapshot_sha256(self.snapshot))
        self.assertEqual(kwargs['decision']['allowedNextActions'], ['prepare_layer3'])
        return True

    def admit(self, **overrides):
        args = dict(lock=self.lock, load_snapshot=self.load, chain_validator=self.validate,
                    compare_and_swap=self.commit, expected_state_revision=self.snapshot.current.state_revision,
                    gate_decision_id='gate-1', created_at=NOW)
        return g.admit_gate(**dict(args, **overrides))

    def test_reload_validate_and_cas_all_inside_existing_lock(self):
        result = self.admit()
        self.assertEqual(self.calls, ['load', 'validate', 'load', 'commit'])
        self.assertEqual(result.commit_status, 'committed')
        self.assertEqual(result.evaluation.decision['admissionStatus'], 'admitted')
        self.assertFalse(self.held)

    def test_stale_state_and_missing_human_never_call_cas(self):
        result = self.admit(expected_state_revision='0' * 64)
        self.assertEqual(result.commit_status, 'stale'); self.assertNotIn('commit', self.calls)
        result = self.admit(chain_validator=lambda s: checks(s, approval_status='missing', approval_artifact_ids=()))
        self.assertEqual(result.commit_status, 'not_attempted')
        self.assertEqual(result.evaluation.decision['admissionStatus'], 'waiting_human')
        self.assertNotIn('commit', self.calls)

    def test_byte_change_between_validation_and_commit_blocks_even_same_revision(self):
        original = self.snapshot
        changed = replace(original, materials=original.materials + (artifact('new-review-evidence', {}),))
        loader = Mock(side_effect=[original, changed])
        commit = Mock(return_value=True)
        result = self.admit(load_snapshot=loader, compare_and_swap=commit)
        self.assertEqual(result.commit_status, 'stale'); commit.assert_not_called()

    def test_cas_rejects_racing_revision_and_never_retries(self):
        commit = Mock(return_value=False)
        result = self.admit(compare_and_swap=commit)
        self.assertEqual(result.commit_status, 'stale')
        self.assertEqual(result.evaluation.decision['allowedNextActions'], ['reconcile'])
        commit.assert_called_once()

    def test_cas_unknown_after_possible_persistence_requires_reconciliation(self):
        for commit in (Mock(side_effect=OSError('private path must not leak')), Mock(return_value=None), Mock(return_value=1)):
            result = self.admit(compare_and_swap=commit)
            self.assertEqual(result.commit_status, 'outcome_unknown')
            self.assertEqual(result.evaluation.decision['admissionStatus'], 'blocked')
            self.assertEqual(result.evaluation.decision['allowedNextActions'], ['reconcile'])
            self.assertNotIn('private path', repr(result))
            commit.assert_called_once()

    def test_loader_or_chain_failure_never_reaches_commit(self):
        for name in ('load_snapshot', 'chain_validator'):
            commit = Mock()
            with self.assertRaises(OSError):
                self.admit(**{name: Mock(side_effect=OSError('unavailable')), 'compare_and_swap': commit})
            commit.assert_not_called()
            self.assertFalse(self.held)


if __name__ == '__main__':
    unittest.main()
