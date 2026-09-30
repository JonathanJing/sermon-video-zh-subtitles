"""Private D4 Layer 2 gate; no producer, model, approval writer or scheduler.

Integration boundary (not wired into production by this module):
* Load GateSnapshot from current state and immutable files inside the EXISTING
  controller lock. Use sermon_review_contracts.read_snapshot for each file.
* CurrentState comes from authoritative state, including the COMPLETE review
  inventory and pending/unknown attempts, never from a model's receipt.
* The trusted chain_validator must validate current source readiness, strict
  policy readiness, the COMPLETE public Candidate, a fresh pinned language
  plugin run, and the existing human receipt against that public Candidate.
  It must prove this private group's exact membership/text/coverage and revision
  binding, not treat one passing group as a whole-locale approval. Every input
  to those checks must be included in materials (and hence snapshot_sha256).
  BoundaryChecks is an in-process adapter result, NOT a new approval format.
  No default adapter exists: absent checks cannot admit anything.
* compare_and_swap must atomically recheck the state revision AND snapshot
  fingerprint, persist the decision and reserve the unique prepare_layer3
  intent. All writers must honor that lock/CAS. It returns literal True only
  after durable success. An exception is an unknown commit, requiring existing
  intent reconciliation, never an automatic retry or model call.

Pure evaluate_gate is advisory. Only admit_gate reloads, validates and commits;
its returned decision does not execute Layer 3. L3's own gates still apply, and
text-only delivery still needs its same-locale audio_unavailable package. This
module grants no Layer 4, publication, listening, device or venue authority.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import re
from typing import Callable, ContextManager

from scripts import sermon_review_contracts as c

GATE_VERSION = 'rqc-layer2-gate-v1'
_LABEL = re.compile(r'[A-Za-z0-9_.:-]{1,100}')
_HASH = re.compile(r'[a-f0-9]{64}')


@dataclass(frozen=True)
class JsonArtifact:
    artifact_id: str
    data: bytes

    def reference(self):
        c.require(type(self.artifact_id) is str and _LABEL.fullmatch(self.artifact_id), 'invalid_gate_artifact_id')
        value = c.decode_json(self.data)
        return dict(artifactId=self.artifact_id, canonicalJsonSha256=c.canonical_sha256(value),
                    fileBytesSha256=c.bytes_sha256(self.data), mediaType='application/json')


@dataclass(frozen=True)
class ReviewEvidence:
    receipt: JsonArtifact
    input_manifest: JsonArtifact


@dataclass(frozen=True)
class CurrentState:
    state_revision: str
    target_locale: str
    candidate_revision_sha256: str
    source_identity_sha256: str
    source_package_sha256: str
    anchor_sha256: str
    policy_sha256: str
    rubric_sha256: str
    # Full canonical receipt hashes (INCLUDING receiptSha256), not content hashes.
    review_receipt_sha256s: tuple[str, ...]
    has_pending_review: bool
    has_unknown_outcome: bool


@dataclass(frozen=True)
class GateSnapshot:
    current: CurrentState
    candidate_revision: JsonArtifact
    candidate_artifact: JsonArtifact
    rubric: JsonArtifact
    reviews: tuple[ReviewEvidence, ...]
    # Exact JSON source/anchor/policy/context/generation/evidence/public/human
    # artifacts, selected by the controller. IDs never become paths or URLs.
    materials: tuple[JsonArtifact, ...]
    parent_revision: JsonArtifact | None = None
    repair_plan: JsonArtifact | None = None


@dataclass(frozen=True)
class BoundaryChecks:
    snapshot_sha256: str
    source_ready: bool
    policy_ready: bool
    public_candidate_ready: bool
    language_plugin_passed: bool
    # Only the existing human-chain validator can establish valid.
    approval_status: str  # missing / invalid / valid
    approval_artifact_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewState:
    artifact_id: str
    execution_status: str | None
    review_verdict: str


@dataclass(frozen=True)
class GateEvaluation:
    decision: dict
    review_states: tuple[ReviewState, ...]


@dataclass(frozen=True)
class AdmissionResult:
    evaluation: GateEvaluation
    commit_status: str  # not_attempted / committed / stale / outcome_unknown


def _artifacts(snapshot):
    return (snapshot.candidate_revision, snapshot.candidate_artifact, snapshot.rubric,
            *(a for r in snapshot.reviews for a in (r.receipt, r.input_manifest)),
            *snapshot.materials,
            *((snapshot.parent_revision,) if snapshot.parent_revision is not None else ()),
            *((snapshot.repair_plan,) if snapshot.repair_plan is not None else ()))


def _shape(snapshot):
    c.require(type(snapshot) is GateSnapshot and type(snapshot.current) is CurrentState, 'invalid_gate_snapshot')
    state = snapshot.current
    for field in fields(state):
        value = getattr(state, field.name)
        if field.name.endswith('sha256') or field.name == 'state_revision':
            c.require(type(value) is str and _HASH.fullmatch(value), 'invalid_gate_current_identity')
    c.require(state.target_locale in ('zh-Hans', 'ko', 'es') and type(state.target_locale) is str,
              'invalid_gate_locale')
    c.require(type(state.has_pending_review) is bool and type(state.has_unknown_outcome) is bool,
              'invalid_gate_execution_state')
    hashes = state.review_receipt_sha256s
    c.require(type(hashes) is tuple and len(hashes) <= 64 and
              all(type(h) is str and _HASH.fullmatch(h) for h in hashes) and len(set(hashes)) == len(hashes),
              'invalid_gate_review_inventory')
    c.require(type(snapshot.reviews) is tuple and len(snapshot.reviews) <= 64 and
              all(type(r) is ReviewEvidence for r in snapshot.reviews), 'invalid_gate_reviews')
    c.require(type(snapshot.materials) is tuple and len(snapshot.materials) <= 512,
              'invalid_gate_materials')
    c.require(all(type(a) is JsonArtifact and type(a.data) is bytes and len(a.data) <= c.MAX_BYTES
                  and type(a.artifact_id) is str and _LABEL.fullmatch(a.artifact_id)
                  for a in _artifacts(snapshot)), 'invalid_gate_artifacts')


def snapshot_sha256(snapshot: GateSnapshot) -> str:
    """Fingerprint all bytes and current state, even a malformed review response."""
    _shape(snapshot)
    return c.canonical_sha256({
        'current': {f.name: getattr(snapshot.current, f.name) for f in fields(snapshot.current)},
        'artifacts': [(a.artifact_id, c.bytes_sha256(a.data)) for a in _artifacts(snapshot)],
        'reviewCount': len(snapshot.reviews), 'materialCount': len(snapshot.materials),
        'hasParent': snapshot.parent_revision is not None, 'hasRepair': snapshot.repair_plan is not None,
    })


def _blocked(evaluation, reason, action):
    decision = dict(evaluation.decision, admissionStatus='blocked', reasonCodes=[reason],
                    allowedNextActions=[action])
    c.validate_contract(decision)
    return GateEvaluation(decision, evaluation.review_states)


def evaluate_gate(snapshot: GateSnapshot, *, gate_decision_id: str, created_at: str,
                  boundary_checks: BoundaryChecks | None = None) -> GateEvaluation:
    """Deterministic, side-effect-free evaluation of a frozen private snapshot.

    Invalid envelope/candidate identity raises ContractError: no truthful Gate
    Decision can be named. Bad review/material/boundary evidence blocks instead.
    Status fields are never inferred from success of the evaluation itself.
    """
    fingerprint = snapshot_sha256(snapshot)
    candidate = c.decode_json(snapshot.candidate_revision.data)
    c.validate_contract(candidate)
    c.require(candidate['schemaVersion'] == 'sermon-candidate-revision-v1', 'expected_candidate_revision')
    state = snapshot.current
    decision = dict(schemaVersion='sermon-review-gate-decision-v1',
                    **{key: candidate[key] for key in ('candidateId', 'revisionId', 'targetLocale', 'workUnitIds')},
                    gateDecisionId=gate_decision_id, gateVersion=GATE_VERSION,
                    stateRevision=state.state_revision, artifactSha256=candidate['artifactSha256'],
                    reviewReceiptRefs=[], policySha256=candidate['policySha256'],
                    rubricSha256=state.rubric_sha256, approvalReceiptRefs=[],
                    admissionStatus='blocked', reasonCodes=['review_not_assessed'],
                    allowedNextActions=['reconcile'], createdAt=created_at)
    c.validate_contract(decision)
    reasons, actions, observations = set(), set(), []

    def block(reason, action='reconcile'):
        reasons.add(reason); actions.add(action)

    identity = {
        'targetLocale': state.target_locale, 'sourceIdentitySha256': state.source_identity_sha256,
        'sourcePackageSha256': state.source_package_sha256, 'anchorSha256': state.anchor_sha256,
        'policySha256': state.policy_sha256,
    }
    if (any(candidate[k] != v for k, v in identity.items()) or
            c.canonical_sha256(candidate) != state.candidate_revision_sha256):
        block('stale_identity')
    try:
        c.validate_candidate_artifact(candidate, snapshot.candidate_artifact.data)
        c.validate_revision_lineage(candidate,
            c.decode_json(snapshot.parent_revision.data) if snapshot.parent_revision else None,
            c.decode_json(snapshot.repair_plan.data) if snapshot.repair_plan else None)
    except c.ContractError:
        block('stale_identity')
    rubric = None
    try:
        rubric = c.decode_json(snapshot.rubric.data)
        c.validate_contract(rubric)
        c.require(rubric['schemaVersion'] == 'sermon-review-rubric-v1' and
                  c.canonical_sha256(rubric) == state.rubric_sha256 and
                  rubric['targetLocale'] == state.target_locale, 'unknown_gate_rubric')
    except c.ContractError:
        rubric = None
        block('unknown_rubric', 'escalate_engineering')

    # Duplicate IDs are rejected even if their bytes match: an explicit complete
    # inventory is easier to audit than silently deduplicating evidence.
    artifacts = _artifacts(snapshot)
    ids = [a.artifact_id for a in artifacts]
    if len(set(ids)) != len(ids):
        block('review_conflict')
    material_map = {a.artifact_id: a for a in artifacts}

    def verify_ref(ref):
        a = material_map.get(ref['artifactId'])
        c.require(a is not None and a.reference() == ref, 'gate_material_mismatch')

    def verify_refs(value):
        if type(value) is dict:
            if set(value) == {'artifactId', 'canonicalJsonSha256', 'fileBytesSha256', 'mediaType'}:
                verify_ref(value)
            else:
                for child in value.values(): verify_refs(child)
        elif type(value) is list:
            for child in value: verify_refs(child)

    try:
        verify_ref(candidate['generationReceiptRef'])
    except c.ContractError:
        block('stale_identity')

    review_hashes, review_ids, attempt_ids, verdicts = [], [], [], set()
    known_execution_failures = 0
    for evidence in snapshot.reviews:
        review = None
        try:
            ref = evidence.receipt.reference()
            review_hashes.append(ref['canonicalJsonSha256'])
            previous = next((r for r in decision['reviewReceiptRefs'] if r['artifactId'] == ref['artifactId']), None)
            if previous is None:
                decision['reviewReceiptRefs'].append(ref)
            else:
                block('review_conflict')
            review = c.decode_json(evidence.receipt.data)
            c.validate_contract(review)
            c.require(review['schemaVersion'] == 'sermon-review-receipt-v1', 'expected_review_receipt')
        except c.ContractError:
            observations.append(ReviewState(evidence.receipt.artifact_id, None, 'not_assessed'))
            block('review_not_assessed')
            continue
        observations.append(ReviewState(evidence.receipt.artifact_id,
                                        review['executionStatus'], review['reviewVerdict']))
        review_ids.append(review['reviewId']); attempt_ids.append(review['reviewAttemptId'])
        try:
            manifest = c.decode_json(evidence.input_manifest.data)
            c.require(rubric is not None, 'unknown_gate_rubric')
            c.validate_review_binding(review, candidate, rubric, manifest)
            verify_refs(manifest)
            verify_refs(review)
            # The current strict policy, not arbitrary self-declared model/prompt.
            policy = c.decode_json(material_map[manifest['materialRefs']['policy']['artifactId']].data)
            c.require(next(c.validator('sermon-target-language-policy-v3').iter_errors(policy), None) is None,
                      'invalid_gate_strict_policy')
            c.require(policy['targetLocale'] == state.target_locale and
                      policy['reviewContract']['rubricCanonicalJsonSha256'] == state.rubric_sha256 and
                      set(policy['languageReview']['requiredChecks']) == set(rubric['requiredLanguagePluginChecks']) and
                      review['reviewerModelRequested'] == policy['reviewer']['model'] and
                      review['reviewerPromptVersion'] == policy['reviewer']['promptVersion'], 'gate_policy_mismatch')
        except c.ContractError:
            block('stale_identity')
            continue
        if review['executionStatus'] == 'outcome_unknown':
            block('review_not_assessed')
        elif review['executionStatus'] in ('failed', 'cancelled'):
            known_execution_failures += 1
        else:
            verdicts.add(review['reviewVerdict'])
            issue_codes = {issue['reasonCode'] for issue in review['issues']}
            # A fresh finding overrides earlier readiness. These are evidence
            # or source problems, even when the valid receipt says needs_rework.
            # Keep the fixed action priorities aligned with the D5 planner.
            if 'source_ambiguity' in issue_codes:
                block('source_not_ready', 'request_source_review')
            if 'contradictory_reviews' in issue_codes:
                block('review_conflict', 'request_human_review')
            if 'evidence_insufficient' in issue_codes:
                block('review_inconclusive', 'request_human_review')
            if review['reviewVerdict'] == 'needs_rework':
                if not issue_codes & {'source_ambiguity', 'contradictory_reviews', 'evidence_insufficient'}:
                    block('review_failed', 'repair_translation')
            elif review['reviewVerdict'] == 'inconclusive':
                block('review_inconclusive', 'request_human_review')
            elif review['reviewVerdict'] != 'pass':
                block('review_not_assessed', 'request_human_review')
            if review['coverage']['unassessedUnitIds']:
                block('coverage_incomplete', 'request_human_review')
            if any(check['result'] != 'pass' for check in review['checks']):
                block('hard_check_failed', 'request_human_review')
    # A complete bound pass can recover a known execution failure. It cannot
    # erase an earlier content verdict, malformed evidence or unknown outcome.
    if known_execution_failures and verdicts != {'pass'}:
        block('review_not_assessed', 'retry_review')
    if len(set(review_ids)) != len(review_ids) or len(set(attempt_ids)) != len(attempt_ids) or len(verdicts) > 1:
        block('review_conflict', 'request_human_review')
    if not snapshot.reviews:
        block('review_not_assessed')
    if sorted(review_hashes) != sorted(state.review_receipt_sha256s):
        block('stale_identity')
    if state.has_pending_review or state.has_unknown_outcome:
        block('review_not_assessed')

    approval = 'missing'
    if boundary_checks is None:
        block('source_not_ready', 'request_source_review')
        block('language_plugin_failed', 'escalate_engineering')
    else:
        checks = boundary_checks
        valid_checks = (type(checks) is BoundaryChecks and checks.snapshot_sha256 == fingerprint and
                        all(type(getattr(checks, key)) is bool for key in
                            ('source_ready', 'policy_ready', 'public_candidate_ready', 'language_plugin_passed')) and
                        checks.approval_status in ('missing', 'invalid', 'valid') and
                        type(checks.approval_artifact_ids) is tuple and
                        len(checks.approval_artifact_ids) <= 16 and
                        all(type(i) is str and _LABEL.fullmatch(i) for i in checks.approval_artifact_ids) and
                        len(set(checks.approval_artifact_ids)) == len(checks.approval_artifact_ids))
        if not valid_checks:
            block('stale_identity')
        else:
            if not checks.source_ready: block('source_not_ready', 'request_source_review')
            if not checks.policy_ready: block('stale_identity')
            # A failed private review precedes public candidate assembly. Those
            # downstream checks are mandatory for admission, but their absence
            # cannot turn a validated content failure into stale identity and
            # make the prescribed repair unreachable. Source/policy stay required.
            downstream_required = verdicts == {'pass'} and not reasons
            if downstream_required and not checks.public_candidate_ready: block('stale_identity')
            if downstream_required and not checks.language_plugin_passed: block('language_plugin_failed', 'escalate_engineering')
            approval = checks.approval_status if downstream_required else 'missing'
            approval_ids = checks.approval_artifact_ids if downstream_required else ()
            try:
                c.require((approval == 'valid') == bool(approval_ids), 'invalid_gate_approval_refs')
                for key in approval_ids:
                    # Must be actual materials verified by the trusted adapter,
                    # not a reference to the machine review itself.
                    artifact = next((a for a in snapshot.materials if a.artifact_id == key), None)
                    c.require(artifact is not None, 'missing_gate_approval_material')
                    decision['approvalReceiptRefs'].append(artifact.reference())
            except c.ContractError:
                approval = 'invalid'
            if approval == 'invalid': block('approval_invalid', 'request_human_review')

    if reasons:
        # Unknown results/stale identities/conflicts never auto-retry or repair.
        if state.has_pending_review or state.has_unknown_outcome or any(
                row.execution_status == 'outcome_unknown' for row in observations):
            actions = {'reconcile'}
        elif reasons & {'stale_identity', 'unknown_rubric', 'review_conflict'}:
            actions = {'request_human_review'} if 'review_conflict' in reasons else {'reconcile'}
        elif 'source_not_ready' in reasons:
            actions = {'request_source_review'}
        elif 'review_inconclusive' in reasons:
            actions = {'request_human_review'}
        elif 'review_failed' in reasons:
            actions.discard('retry_review')
        decision.update(reasonCodes=sorted(reasons), allowedNextActions=sorted(actions))
    elif approval == 'missing':
        decision.update(admissionStatus='waiting_human', reasonCodes=['human_approval_missing'],
                        allowedNextActions=['request_human_review'])
    else:
        decision.update(admissionStatus='admitted', reasonCodes=['all_required_evidence_passed'],
                        allowedNextActions=['prepare_layer3'])
    c.validate_contract(decision)
    return GateEvaluation(decision, tuple(observations))


def admit_gate(*, lock: ContextManager, load_snapshot: Callable[[], GateSnapshot],
               chain_validator: Callable[[GateSnapshot], BoundaryChecks],
               compare_and_swap: Callable[..., bool], expected_state_revision: str,
               gate_decision_id: str, created_at: str) -> AdmissionResult:
    """Reload inside an existing lock; never accept a precomputed Gate Decision.

    Loader/validator failures propagate without a CAS or side effect. CAS failure
    is conservatively unknown, since persistence may have preceded the failure.
    Caller must reconcile its durable intent before trying admission again.
    """
    c.require(type(expected_state_revision) is str and _HASH.fullmatch(expected_state_revision),
              'invalid_expected_state_revision')
    with lock:
        snapshot = load_snapshot()
        fingerprint = snapshot_sha256(snapshot)
        checks = chain_validator(snapshot)
        result = evaluate_gate(snapshot, gate_decision_id=gate_decision_id,
                               created_at=created_at, boundary_checks=checks)
        if snapshot.current.state_revision != expected_state_revision:
            return AdmissionResult(_blocked(result, 'stale_identity', 'reconcile'), 'stale')
        if result.decision['admissionStatus'] != 'admitted':
            return AdmissionResult(result, 'not_attempted')
        # Catch byte changes even if a broken writer forgot to bump stateRevision.
        if snapshot_sha256(load_snapshot()) != fingerprint:
            return AdmissionResult(_blocked(result, 'stale_identity', 'reconcile'), 'stale')
        try:
            committed = compare_and_swap(expected_state_revision=expected_state_revision,
                                        expected_snapshot_sha256=fingerprint,
                                        decision=c.decode_json(c.canonical_bytes(result.decision)))
        except Exception:
            return AdmissionResult(_blocked(result, 'review_not_assessed', 'reconcile'), 'outcome_unknown')
        if committed is True:
            return AdmissionResult(result, 'committed')
        if committed is False:
            return AdmissionResult(_blocked(result, 'stale_identity', 'reconcile'), 'stale')
        return AdmissionResult(_blocked(result, 'review_not_assessed', 'reconcile'), 'outcome_unknown')
