"""Synthetic D5 developer checks; neither durable-budget nor acceptance evidence."""
import copy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import sermon_repair_planning as p
from scripts import sermon_review_contracts as c

FIXTURES = Path(__file__).parent / 'fixtures' / 'rqc'
UNIT = 'l2.zh-Hans.group.001'
NEXT = 'l2.zh-Hans.group.002'
INDEPENDENT = 'l2.zh-Hans.group.003'
AUDIO = 'l3.zh-Hans.audio'
PAGE = 'l4.zh-Hans.page'
KO = 'l2.ko.group.001'
STATE = '8' * 64


def load(name):
    return json.loads((FIXTURES / (name + '.json')).read_text())


def seal(review):
    review['receiptSha256'] = c.receipt_sha256(review)
    return review


def node(unit, layer, locale, *dependencies):
    return {'workUnitId': unit, 'layer': layer, 'targetLocale': locale, 'dependsOn': list(dependencies)}


def graph():
    return [node('source', 1, None), node(UNIT, 2, 'zh-Hans', 'source'),
            node(NEXT, 2, 'zh-Hans', UNIT), node(INDEPENDENT, 2, 'zh-Hans', 'source'),
            node(AUDIO, 3, 'zh-Hans', UNIT, NEXT, INDEPENDENT), node(PAGE, 4, 'zh-Hans', AUDIO),
            node(KO, 2, 'ko', 'source'), node('l3.ko.audio', 3, 'ko', KO)]


def budget(**changes):
    return replace(p.BudgetSnapshot(production_run_id='9' * 64, state_revision=STATE,
        candidate_id='synthetic-candidate', work_unit_id=UNIT, chain_root_revision_id='r1',
        current_revision_id='r1', authorization_sha256='a' * 64, global_budget_sha256='b' * 64,
        content_revisions_reserved=0, review_attempts_reserved=1, decision_proposals_reserved=0), **changes)


def inputs(review=None, **changes):
    review = review or load('review-fail')
    review_bytes = c.canonical_bytes(review)
    gate = load('gate-waiting')
    gate.update(admissionStatus='blocked', reasonCodes=['review_failed'],
                allowedNextActions=['repair_translation', 'retry_review', 'request_human_review',
                                    'request_source_review', 'reconcile', 'escalate_engineering'],
                reviewReceiptRefs=[{'artifactId': 'review-receipt',
                    'canonicalJsonSha256': c.canonical_sha256(review),
                    'fileBytesSha256': c.bytes_sha256(review_bytes), 'mediaType': 'application/json'}])
    return dict(candidate=load('candidate-revision'),
        candidate_bytes=(FIXTURES / 'candidate-artifact.json').read_bytes(), review=review,
        review_bytes=review_bytes, rubric=load('rubric'), input_manifest=load('input-manifest'),
        gate=gate, state_revision=STATE, graph=graph(), budget=budget(), **changes)


def failed_review(status='failed'):
    review = load('review-pass')
    review.update(executionStatus=status, reviewVerdict='not_assessed', issues=[])
    review['coverage'].update(assessedUnitIds=[], unassessedUnitIds=['source.001'])
    for check in review['checks']:
        check['result'] = 'not_assessed'
    return seal(review)


class RoutingTests(unittest.TestCase):
    def test_all_content_codes_have_fixed_allowlisted_action(self):
        actions = set(c.validator('sermon-review-gate-decision-v1').schema['properties']['allowedNextActions']['items']['enum'])
        for code, action in p.FAILURE_ACTIONS.items():
            with self.subTest(code=code):
                self.assertEqual(p.route_failure(code), action)
                self.assertIn(action, actions)
                if code in p.CONTENT_FAILURES:
                    receipt = load('review-fail')
                    receipt['issues'][0]['reasonCode'] = code
                    result = p.plan_repair(**inputs(seal(receipt)))
                    self.assertEqual(result['action'], 'repair_translation')
                    self.assertEqual(result['repairPlan']['reasonCodes'], [code])
        self.assertEqual(p.route_failure('unrecognized_failure'), 'escalate_engineering')
        with self.assertRaises(c.ContractError):
            p.route_failure('meaning_omission', version='v-next')
        with self.assertRaises(TypeError):
            p.FAILURE_ACTIONS['meaning_omission'] = 'retry_review'

    def test_content_failure_creates_bound_new_revision_and_canonical_sidecars(self):
        args = inputs()
        original = copy.deepcopy(args)
        result = p.plan_repair(**args)
        self.assertEqual(args, original)
        self.assertEqual(result, p.plan_repair(**args))
        self.assertEqual(result['status'], 'proposal')
        self.assertNotEqual(result['toRevisionId'], 'r1')
        self.assertEqual(result['repairPlan']['affectedWorkUnitIds'], [UNIT])
        self.assertEqual(result['dependencyGroupsRequiringOwnPlans'], [NEXT])
        self.assertEqual(result['dependencyClosure']['invalidateWorkUnitIds'], [AUDIO, PAGE])
        self.assertEqual(result['executionAuthority'], 'none')
        self.assertEqual(result['durableIntegration'], 'pending')
        c.validate_repair_binding(result['repairPlan'], args['review'], args['candidate'])
        for key, name in [('dependencyClosureRef', 'dependencyClosure'), ('constraintsRef', 'constraints'), ('budgetRef', 'budgetSnapshot')]:
            ref = result['repairPlan'][key]
            self.assertEqual(ref['canonicalJsonSha256'], c.canonical_sha256(result[name]))
            self.assertEqual(ref['fileBytesSha256'], c.bytes_sha256(c.canonical_bytes(result[name])))
        result['repairPlan']['affectedWorkUnitIds'].append('injected')
        self.assertEqual(p.plan_repair(**args)['repairPlan']['affectedWorkUnitIds'], [UNIT])

    def test_failed_and_cancelled_review_recover_same_candidate_without_content_closure(self):
        for status in ('failed', 'cancelled'):
            with self.subTest(status=status):
                args = inputs(failed_review(status))
                result = p.plan_repair(**args)
                self.assertEqual(result['action'], 'retry_review')
                self.assertEqual(result['toRevisionId'], result['fromRevisionId'])
                self.assertEqual(result['dependencyClosure']['regenerateWorkUnitIds'], [])
                self.assertEqual(result['dependencyClosure']['invalidateWorkUnitIds'], [])
                c.validate_repair_binding(result['repairPlan'], args['review'], args['candidate'])

    def test_unknown_outcome_never_blind_retries_even_with_gate_retry_or_saved_response(self):
        for saved in (False, True):
            args = inputs(failed_review('outcome_unknown'), saved_review_response=saved)
            args['gate']['allowedNextActions'] = ['retry_review']
            result = p.plan_repair(**args)
            self.assertEqual(result['status'], 'reconciliation_required')
            self.assertEqual(result['action'], 'reconcile')
            self.assertEqual(result['toRevisionId'], 'r1')
            self.assertIsNone(result['repairPlan'])
            self.assertFalse(result['requiresFreshProviderRequest'])

    def test_saved_response_and_log_failure_do_not_request_new_inference(self):
        for options in ({'saved_review_response': True}, {'persistence_failed': True}):
            with self.subTest(options=options):
                result = p.plan_repair(**inputs(failed_review(), **options))
                self.assertEqual(result['action'], 'reconcile')
                self.assertFalse(result['requiresFreshProviderRequest'])
                self.assertIsNone(result['repairPlan'])

    def test_d4_stale_and_unknown_rubric_routes_reconcile_without_paid_plan(self):
        for code in ('stale_identity', 'unknown_rubric'):
            args = inputs()
            args['gate'].update(reasonCodes=[code], allowedNextActions=['reconcile'])
            result = p.plan_repair(**args)
            self.assertEqual(result['action'], 'reconcile')
            self.assertEqual(result['status'], 'reconciliation_required')
            self.assertFalse(result['requiresFreshProviderRequest'])
        result = p.plan_repair(**inputs(failed_review('outcome_unknown'), scope_ambiguous=True))
        self.assertEqual(result['action'], 'reconcile')

    def test_source_uncertainty_and_conflicts_override_content_repair(self):
        for issue, action in [('source_ambiguity', 'request_source_review'), ('contradictory_reviews', 'request_human_review'),
                              ('evidence_insufficient', 'request_human_review')]:
            review = load('review-fail')
            second = copy.deepcopy(review['issues'][0])
            second.update(issueId='issue-2', reasonCode=issue, severity='uncertain')
            review['issues'].append(second)
            result = p.plan_repair(**inputs(seal(review)))
            self.assertEqual(result['action'], action)
            self.assertEqual(result['toRevisionId'], 'r1')
            self.assertIsNone(result['repairPlan'])

    def test_inconclusive_is_human_review_not_content_regeneration(self):
        review = load('review-fail')
        review['issues'][0]['severity'] = 'uncertain'
        review['reviewVerdict'] = 'inconclusive'
        result = p.plan_repair(**inputs(seal(review)))
        self.assertEqual(result['action'], 'request_human_review')
        self.assertIsNone(result['repairPlan'])

    def test_pass_waits_for_human_without_manufacturing_approval(self):
        args = inputs(load('review-pass'))
        args['gate'].update(admissionStatus='waiting_human', reasonCodes=['human_approval_missing'],
                            allowedNextActions=['request_human_review'])
        result = p.plan_repair(**args)
        self.assertEqual(result['action'], 'request_human_review')
        self.assertEqual(result['executionAuthority'], 'none')
        self.assertIsNone(result['repairPlan'])

    def test_admitted_machine_pass_has_no_repair_and_no_new_admission_authority(self):
        args = inputs(load('review-pass'))
        args['gate'].update(admissionStatus='admitted', reasonCodes=['all_required_evidence_passed'],
                            allowedNextActions=['prepare_layer3'],
                            approvalReceiptRefs=[load('candidate-revision')['generationReceiptRef']])
        result = p.plan_repair(**args)
        self.assertEqual(result['status'], 'no_repair')
        self.assertIsNone(result['action'])
        self.assertEqual(result['executionAuthority'], 'none')

    def test_gate_scope_state_hash_and_action_bindings_fail_closed(self):
        for key, value in [('stateRevision', '0' * 64), ('candidateId', 'other'), ('revisionId', 'r2'),
                           ('artifactSha256', '0' * 64), ('policySha256', '0' * 64), ('rubricSha256', '0' * 64),
                           ('reviewReceiptRefs', []), ('workUnitIds', [NEXT])]:
            args = inputs()
            args['gate'][key] = value
            with self.subTest(key=key), self.assertRaises(c.ContractError):
                p.plan_repair(**args)
        args = inputs()
        args['gate']['allowedNextActions'] = ['request_human_review']
        result = p.plan_repair(**args)
        self.assertEqual(result['status'], 'blocked')
        self.assertIsNone(result['repairPlan'])

    def test_byte_identity_not_just_canonical_identity_is_required(self):
        for key in ('candidate_bytes', 'review_bytes'):
            args = inputs()
            if key == 'candidate_bytes':
                args[key] += b'\n'
            else:
                args['gate']['reviewReceiptRefs'][0]['fileBytesSha256'] = '0' * 64
            with self.subTest(key=key), self.assertRaises(c.ContractError):
                p.plan_repair(**args)


class ClosureTests(unittest.TestCase):
    def test_transitive_closure_reuses_prerequisites_independent_groups_and_other_locales(self):
        result = p.dependency_closure(graph(), [UNIT])
        self.assertEqual(result['affectedWorkUnitIds'], [UNIT, NEXT, AUDIO, PAGE])
        self.assertEqual(result['regenerateWorkUnitIds'], [UNIT, NEXT])
        self.assertIn(INDEPENDENT, result['reuseEligibleWorkUnitIds'])
        self.assertIn('source', result['reuseEligibleWorkUnitIds'])
        self.assertIn(KO, result['reuseEligibleWorkUnitIds'])
        self.assertIn('l3.ko.audio', result['reuseEligibleWorkUnitIds'])

    def test_graph_and_edge_order_do_not_change_plan(self):
        shuffled = list(reversed(graph()))
        for row in shuffled:
            row['dependsOn'].reverse()
        self.assertEqual(p.dependency_closure(graph(), [UNIT]), p.dependency_closure(shuffled, [UNIT]))

    def test_confirmed_source_change_closure_covers_all_locales(self):
        result = p.dependency_closure(graph(), ['source'])
        self.assertEqual(set(result['affectedWorkUnitIds']), {row['workUnitId'] for row in graph()})
        self.assertEqual(result['reuseEligibleWorkUnitIds'], [])

    def test_missing_cycles_cross_locale_reverse_layers_and_duplicate_units_rejected(self):
        invalid = []
        value = graph(); value[1]['dependsOn'] = ['missing']; invalid.append(value)
        value = graph(); value[1]['dependsOn'] = [NEXT]; invalid.append(value)
        value = graph(); value[1]['dependsOn'] = [KO]; invalid.append(value)
        value = graph(); value[1]['dependsOn'] = [AUDIO]; invalid.append(value)
        value = graph(); value.append(copy.deepcopy(value[1])); invalid.append(value)
        value = graph(); value[1]['targetLocale'] = 'ko'; invalid.append(value)
        value = graph(); value[1]['dependsOn'] = ['source', 'source']; invalid.append(value)
        value = graph(); value[1]['layer'] = True; invalid.append(value)
        value = graph(); value[1]['targetLocale'] = ['ko']; invalid.append(value)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(c.ContractError):
                p.dependency_closure(value, [UNIT])


class BudgetAndLineageTests(unittest.TestCase):
    def test_no_snapshot_means_no_proposed_paid_work(self):
        for review in (load('review-fail'), failed_review()):
            args = inputs(review); args['budget'] = None
            result = p.plan_repair(**args)
            self.assertEqual(result['reasonCode'], 'durable_budget_snapshot_required')
            self.assertEqual(result['status'], 'blocked')
            self.assertIsNone(result['repairPlan'])

    def test_experiment_limits_include_reservations_and_allow_stricter_authorization(self):
        cases = [(load('review-fail'), {'content_revisions_reserved': 2}, 'content_revision_limit_reached'),
                 (failed_review(), {'review_attempts_reserved': 2}, 'review_execution_limit_reached'),
                 (load('review-fail'), {'limits': p.Limits(content_revisions=0)}, 'content_revision_limit_reached'),
                 (failed_review(), {'limits': p.Limits(review_attempts_per_revision=1)}, 'review_execution_limit_reached')]
        for review, changes, reason in cases:
            args = inputs(review); args['budget'] = budget(**changes)
            result = p.plan_repair(**args)
            self.assertEqual(result['reasonCode'], reason)
            self.assertIsNone(result['repairPlan'])

    def test_bad_or_reset_counters_and_foreign_budget_identity_rejected(self):
        for changes in ({'content_revisions_reserved': True}, {'review_attempts_reserved': 0},
                        {'decision_proposals_reserved': -1}, {'state_revision': '0' * 64},
                        {'candidate_id': 'foreign'}, {'work_unit_id': NEXT}, {'chain_root_revision_id': 'new-root'},
                        {'current_revision_id': 'r2'}, {'authorization_sha256': ''},
                        {'limits': p.Limits(content_revisions=3)}, {'limits': p.Limits(decision_proposals_per_chain=2)},
                        {'unresolved_operation_ids': ['/tmp/unsafe']}):
            args = inputs(); args['budget'] = budget(**changes)
            with self.subTest(changes=changes), self.assertRaises(c.ContractError):
                p.plan_repair(**args)
        with self.assertRaises(FrozenInstanceError):
            budget().content_revisions_reserved = 0

    def test_unknown_reserved_request_blocks_even_known_content_failure(self):
        args = inputs(); args['budget'] = budget(unresolved_operation_ids=('intent-previous',))
        result = p.plan_repair(**args)
        self.assertEqual(result['action'], 'reconcile')
        self.assertFalse(result['requiresFreshProviderRequest'])
        self.assertIsNone(result['repairPlan'])

    def test_same_artifact_and_failure_cannot_reset_with_new_issue_or_review_id(self):
        args = inputs()
        first = p.plan_repair(**args)
        args['review']['issues'][0]['issueId'] = 'different-issue'
        args['review']['reviewId'] = 'different-review'
        args = inputs(seal(args['review']))
        args['budget'] = budget(prior_failure_fingerprints=(first['failureFingerprint'],))
        result = p.plan_repair(**args)
        self.assertEqual(result['reasonCode'], 'repeated_failure_without_new_evidence')
        self.assertIsNone(result['repairPlan'])

    def test_complete_immutable_lineage_and_no_counter_reset_after_revision(self):
        args = inputs()
        first = p.plan_repair(**args)
        parent = copy.deepcopy(args['candidate'])
        child = copy.deepcopy(parent)
        child.update(revisionId=first['toRevisionId'], parentRevisionId='r1', revisionNumber=2,
                     repairPlanId=first['repairPlan']['repairPlanId'])
        c.validate_revision_lineage(child, parent, first['repairPlan'])
        args['candidate'] = child
        args['review']['revisionId'] = child['revisionId']
        args['input_manifest']['revisionId'] = child['revisionId']
        args['review']['reviewerInputManifestSha256'] = c.canonical_sha256(args['input_manifest'])
        args['review'] = seal(args['review']); args['review_bytes'] = c.canonical_bytes(args['review'])
        args['gate']['revisionId'] = child['revisionId']
        args['gate']['reviewReceiptRefs'][0].update(canonicalJsonSha256=c.canonical_sha256(args['review']),
                                                  fileBytesSha256=c.bytes_sha256(args['review_bytes']))
        args['budget'] = budget(current_revision_id=child['revisionId'], content_revisions_reserved=1)
        with self.assertRaisesRegex(c.ContractError, 'incomplete_revision_chain'):
            p.plan_repair(**args)
        args.update(prior_revisions=[parent], prior_repairs=[first['repairPlan']])
        second = p.plan_repair(**args)
        self.assertNotEqual(second['toRevisionId'], first['toRevisionId'])
        self.assertEqual(second['constraints']['rootRevisionId'], 'r1')
        args['budget'] = replace(args['budget'], prior_failure_fingerprints=(first['failureFingerprint'],))
        self.assertEqual(p.plan_repair(**args)['reasonCode'], 'repeated_failure_without_new_evidence')
        args['budget'] = replace(args['budget'], content_revisions_reserved=0)
        with self.assertRaisesRegex(c.ContractError, 'budget_counter_reset'):
            p.plan_repair(**args)
        changed = copy.deepcopy(child); changed['sourceIdentitySha256'] = '0' * 64
        with self.assertRaises(c.ContractError):
            c.validate_revision_lineage(changed, parent, first['repairPlan'])

    def test_new_bound_context_evidence_can_distinguish_repeated_failure(self):
        args = inputs()
        first = p.plan_repair(**args)
        args['budget'] = budget(prior_failure_fingerprints=(first['failureFingerprint'],))
        args['input_manifest']['materialRefs']['context'].update(canonicalJsonSha256='c' * 64,
                                                               fileBytesSha256='d' * 64)
        args['review']['reviewerInputManifestSha256'] = c.canonical_sha256(args['input_manifest'])
        args['review'] = seal(args['review'])
        args['review_bytes'] = c.canonical_bytes(args['review'])
        args['gate']['reviewReceiptRefs'][0].update(canonicalJsonSha256=c.canonical_sha256(args['review']),
                                                  fileBytesSha256=c.bytes_sha256(args['review_bytes']))
        result = p.plan_repair(**args)
        self.assertEqual(result['status'], 'proposal')
        self.assertNotEqual(result['failureFingerprint'], first['failureFingerprint'])


class DecisionTests(unittest.TestCase):
    def setup_packet(self):
        args = inputs(scope_ambiguous=True)
        planning = p.plan_repair(**args)
        packet = p.build_ambiguous_packet(planning, budget=args['budget'])
        proposal = {'schemaVersion': p.decision.DECISION_SCHEMA, 'decisionId': packet['decisionId'],
            'stateRevision': STATE, 'packetSha256': c.canonical_sha256(packet),
            'selectedAction': 'open_text_revision', 'affectedWorkUnits': ['text.zh-Hans'],
            'reasonCode': 'text_repair_needed', 'evidenceRefs': packet['evidenceRefs'][:]}
        return args, planning, packet, proposal

    def test_proposal_interface_reuses_existing_schema_without_invoking_responder(self):
        with patch.object(p.decision, 'propose', side_effect=AssertionError('must not invoke model')):
            args, planning, packet, proposal = self.setup_packet()
            self.assertEqual(packet['retryBudget'], {'remainingDecisionAttempts': 1, 'maxTurns': 1})
            self.assertEqual(packet['evidenceIdentitySha256'], c.canonical_sha256(planning))
            self.assertIsNone(planning['repairPlan'])
            result = p.validate_ambiguous_proposal(packet, proposal, copy.deepcopy(packet))
            self.assertEqual(result['action'], 'repair_translation')
            self.assertEqual(result['executionAuthority'], 'none')
            self.assertEqual(args['budget'].decision_proposals_reserved, 0)

    def test_chain_decision_limit_does_not_reset_with_issue_or_revision(self):
        args = inputs(scope_ambiguous=True); args['budget'] = budget(decision_proposals_reserved=1)
        planning = p.plan_repair(**args)
        self.assertEqual(planning['reasonCode'], 'decision_proposal_limit_reached')
        with self.assertRaises(c.ContractError):
            p.build_ambiguous_packet(planning, budget=args['budget'])

    def test_unambiguous_and_single_action_cases_cannot_request_model(self):
        args = inputs()
        with self.assertRaises(c.ContractError):
            p.build_ambiguous_packet(p.plan_repair(**args), budget=args['budget'])
        args['scope_ambiguous'] = True
        args['gate']['allowedNextActions'] = ['repair_translation']
        with self.assertRaisesRegex(c.ContractError, 'multiple_allowed_actions'):
            p.build_ambiguous_packet(p.plan_repair(**args), budget=args['budget'])

    def test_proposal_cannot_add_text_paths_actions_scope_or_alter_budget(self):
        args, planning, packet, proposal = self.setup_packet()
        for key, value in [('targetUtterances', ['injected']), ('path', '/private/secret'),
                           ('selectedAction', 'open_audio_revision'), ('affectedWorkUnits', ['text.ko']),
                           ('reasonCode', 'audio_repair_needed'), ('evidenceRefs', [])]:
            changed = copy.deepcopy(proposal); changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                p.validate_ambiguous_proposal(packet, changed, packet)
        fresh = copy.deepcopy(packet)
        fresh['stateRevision'] = '1' * 64
        with self.assertRaises(ValueError):
            p.validate_ambiguous_proposal(packet, proposal, fresh)
        with self.assertRaises(c.ContractError):
            p.build_ambiguous_packet(planning, budget=replace(args['budget'], global_budget_sha256='0' * 64))

    def test_non_rqc_ambiguous_packets_are_rejected(self):
        _, _, packet, proposal = self.setup_packet()
        packet['triggeringFailureCode'] = 'timing_repair_scope_ambiguous'
        packet = p.decision.build_packet(**{k: v for k, v in packet.items() if k != 'decisionId'})
        proposal.update(decisionId=packet['decisionId'], packetSha256=c.canonical_sha256(packet))
        with self.assertRaisesRegex(c.ContractError, 'unsupported_rqc_decision_scope'):
            p.validate_ambiguous_proposal(packet, proposal, packet)


if __name__ == '__main__':
    unittest.main()
