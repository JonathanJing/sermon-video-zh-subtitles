"""D1 developer checks only. Synthetic receipts never establish human approval."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_review_contracts as c
from scripts import target_language_policy as policy

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT/'tests/fixtures/rqc'


def load(name): return json.loads((FIXTURES/(name+'.json')).read_text())
def seal(row): row['receiptSha256'] = c.receipt_sha256(row); return row


class ReviewContractTests(unittest.TestCase):
    def test_all_positive_fixtures_schema_and_semantic_validation(self):
        for name in ('candidate-revision','rubric','input-manifest','review-pass','review-fail','gate-waiting','repair-plan'):
            with self.subTest(name=name):
                row=load(name);self.assertTrue(c.validator(row['schemaVersion']).is_valid(row));c.validate_contract(row)
        result=c.validate_review_binding(load('review-pass'),load('candidate-revision'),load('rubric'),load('input-manifest'))
        self.assertEqual(result['executionAuthority'],'none');self.assertIsNone(result['admissionStatus'])
        c.validate_repair_binding(load('repair-plan'),load('review-fail'),load('candidate-revision'))

    def test_every_schema_is_closed_and_required_fields_not_optional(self):
        for name in ('candidate-revision','rubric','input-manifest','review-pass','gate-waiting','repair-plan'):
            row=load(name)
            for key in row:
                if key=='missingReasons':continue
                changed=copy.deepcopy(row);del changed[key]
                with self.subTest(name=name,removed=key),self.assertRaises(c.ContractError):c.validate_contract(changed)
            row['prompt']='secret fixture injection'
            with self.assertRaises(c.ContractError):c.validate_contract(row)

    def test_no_coercion_nonfinite_unbounded_or_private_paths(self):
        for key,value in [('revisionNumber',True),('revisionNumber',1.0),('revisionNumber',float('nan')),
                          ('candidateId','/private/path'),('candidateId','x'*101),('candidateId','line\n'),
                          ('createdAt','2026-02-30T00:00:00Z'),('schemaVersion',{}),('schemaVersion','future')]:
            row=load('candidate-revision');row[key]=value
            with self.subTest(key=key),self.assertRaises(c.ContractError):c.validate_contract(row)
        row=load('review-pass');row['targetUtterances']=['Reviewer cannot replace candidate']
        with self.assertRaises(c.ContractError):c.validate_contract(row)
        row=load('review-pass');row['issues']=['x']*65
        with self.assertRaises(c.ContractError):c.validate_contract(row)

    def test_receipt_hash_non_circular_and_exact_bytes_distinct(self):
        row=load('review-pass');digest=row['receiptSha256'];row['receiptSha256']='0'*64
        self.assertEqual(c.receipt_sha256(row),digest)
        with self.assertRaisesRegex(c.ContractError,'hash_mismatch'):c.validate_contract(row)
        manifest=load('candidate-revision');data=(FIXTURES/'candidate-artifact.json').read_bytes()
        c.validate_candidate_artifact(manifest,data)
        reserialized=c.canonical_bytes(json.loads(data))
        self.assertEqual(c.canonical_sha256(json.loads(data)),c.canonical_sha256(json.loads(reserialized)))
        self.assertNotEqual(c.bytes_sha256(data),c.bytes_sha256(reserialized))
        with self.assertRaisesRegex(c.ContractError,'hash_mismatch'):c.validate_candidate_artifact(manifest,reserialized)

    def test_duplicate_keys_and_changed_file_snapshot_are_rejected(self):
        with self.assertRaises(c.ContractError):c.decode_json(b'{"candidateId":"a","candidateId":"b"}')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'candidate.json';path.write_bytes((FIXTURES/'candidate-artifact.json').read_bytes())
            value,data=c.read_snapshot(path);self.assertEqual(value,json.loads(data))
            link=Path(tmp)/'link.json';link.symlink_to(path)
            with self.assertRaises(OSError):c.read_snapshot(link)
            original=c.os.stat
            def replaced(*args,**kwargs):
                path.write_text('{}')
                return original(*args,**kwargs)
            with patch.object(c.os,'stat',side_effect=replaced),self.assertRaisesRegex(c.ContractError,'snapshot_changed'):
                c.read_snapshot(path)

    def test_pass_requires_all_checks_full_coverage_no_unresolved_issues(self):
        mutations=[lambda r:r['checks'].pop(),lambda r:r['checks'].append(copy.deepcopy(r['checks'][0])),
            lambda r:r['checks'][0].update(result='fail'),lambda r:r['checks'][0].update(evidenceRefs=[]),
            lambda r:r['coverage'].update(assessedUnitIds=[],unassessedUnitIds=['source.001']),
            lambda r:r['coverage'].update(expectedUnitIds=['source.002']),
            lambda r:r.update(issues=load('review-fail')['issues']),
            lambda r:r.update(reviewerModelActual='other-model')]
        for mutate in mutations:
            row=load('review-pass');mutate(row);seal(row)
            with self.subTest(mutate=mutate),self.assertRaises(c.ContractError):c.validate_contract(row)

    def test_execution_failure_unknown_and_inconclusive_are_not_content_failure(self):
        for status in ('failed','cancelled','outcome_unknown'):
            row=load('review-pass');row.update(executionStatus=status,reviewVerdict='not_assessed',checks=[],
                reviewerModelActual=None,providerResponseId=None,missingReasons=dict(reviewerModelActual='not_observed',providerResponseId='not_observed'))
            row['coverage'].update(assessedUnitIds=[],unassessedUnitIds=['source.001']);seal(row);c.validate_contract(row)
            row['reviewVerdict']='needs_rework';seal(row)
            with self.assertRaises(c.ContractError):c.validate_contract(row)
        row=load('review-pass');row['reviewVerdict']='inconclusive';row['checks'][0]['result']='not_assessed';seal(row);c.validate_contract(row)

    def test_stale_locale_policy_rubric_input_and_unit_bindings_are_rejected(self):
        for key,value in [('targetLocale','ko'),('revisionId','r2'),('sourceIdentitySha256','0'*64),('policySha256','0'*64),
                          ('reviewedArtifactSha256','0'*64),('rubricSha256','0'*64),('reviewerInputManifestSha256','0'*64)]:
            row=load('review-pass');row[key]=value;seal(row)
            with self.subTest(key=key),self.assertRaises(c.ContractError):
                c.validate_review_binding(row,load('candidate-revision'),load('rubric'),load('input-manifest'))
        rubric=load('rubric');rubric['requiredChecks'][0]='unknown_check'
        with self.assertRaises(c.ContractError):c.validate_contract(rubric)
        row=load('review-pass');row['evidenceRefs'].append(dict(row['evidenceRefs'][0],fileBytesSha256='0'*64));seal(row)
        with self.assertRaisesRegex(c.ContractError,'conflicting_artifact'):c.validate_contract(row)

    def test_gate_cannot_grant_l3_from_machine_pass_without_human_refs(self):
        gate=load('gate-waiting');gate.update(admissionStatus='admitted',allowedNextActions=['prepare_layer3'],reasonCodes=['all_required_evidence_passed'])
        with self.assertRaisesRegex(c.ContractError,'admitted_gate_evidence_missing'):c.validate_contract(gate)
        gate=load('gate-waiting');gate['allowedNextActions']=['prepare_layer3']
        with self.assertRaises(c.ContractError):c.validate_contract(gate)
        gate=load('gate-waiting');gate['allowedNextActions']=['prepare_layer4']
        with self.assertRaises(c.ContractError):c.validate_contract(gate)

    def test_repair_requires_bound_failure_and_new_content_revision(self):
        plan=load('repair-plan')
        with self.assertRaises(c.ContractError):c.validate_repair_binding(plan,load('review-pass'),load('candidate-revision'))
        plan['toRevisionId']='r1'
        with self.assertRaises(c.ContractError):c.validate_contract(plan)
        parent=load('candidate-revision');child=copy.deepcopy(parent)
        child.update(revisionId='r2',parentRevisionId='r1',revisionNumber=2,repairPlanId='synthetic-repair')
        c.validate_revision_lineage(child,parent,load('repair-plan'))
        child['policySha256']='0'*64
        with self.assertRaises(c.ContractError):c.validate_revision_lineage(child,parent,load('repair-plan'))


class StrictPolicyTests(unittest.TestCase):
    def strict(self):
        draft=load('legacy-policy-v2');draft.pop('componentSha256');draft['schemaVersion']=policy.POLICY_V3
        draft['reviewMode']='strict_verifier';draft['translator']['promptVersion']='astra-strict-generator-v1';draft['reviewer']['promptVersion']='sol-strict-verifier-v1'
        rubric=load('rubric');rubric['requiredLanguagePluginChecks']=draft['languageReview']['requiredChecks']
        draft['reviewContract']=dict(rubricCanonicalJsonSha256=c.canonical_sha256(rubric),reviewReceiptSchemaVersion='sermon-review-receipt-v1',candidateRevisionSchemaVersion='sermon-candidate-revision-v1',inputManifestSchemaVersion='sermon-review-input-manifest-v1',revisionGranularity='translation_group')
        return policy.freeze_strict_policy(draft,rubric),rubric

    def test_v3_is_explicit_never_accepted_by_legacy_default(self):
        strict,rubric=self.strict();result=policy.validate_strict_policy(strict,rubric)
        self.assertEqual(result['reviewMode'],'strict_verifier');self.assertEqual(result['executionAuthority'],'none')
        with self.assertRaisesRegex(ValueError,'Unsupported'):policy.validate_policy(strict)
        strict['batching']['workers']=True
        with self.assertRaises(c.ContractError):policy.validate_strict_policy(strict,rubric)

    def test_legacy_editor_result_remains_raw_and_is_not_relabelled_strict(self):
        from scripts import run_target_language_models as legacy
        data=(FIXTURES/'legacy-editor-result.json').read_bytes()
        self.assertEqual(c.bytes_sha256(data),load('legacy-golden-sha256')['fixtureLegacyEditorBytesSha256'])
        row=json.loads(data);before=c.canonical_bytes(row)
        normalized=legacy.normalize_semantic_review(row['semanticReview'])
        self.assertEqual(set(normalized['checks'].values()),{'pass'})
        self.assertEqual(c.canonical_bytes(row),before)
        self.assertEqual(row['targetUtterances'],['合成审校后的文字。'])
        self.assertNotIn('reviewMode',row)
        with self.assertRaises(c.ContractError):c.validate_contract(row)

    def test_unknown_rubric_or_stale_components_fail_closed(self):
        strict,rubric=self.strict();rubric['rubricVersion']='changed'
        with self.assertRaises(c.ContractError):policy.validate_strict_policy(strict,rubric)
        strict,rubric=self.strict();strict['reviewContract']['rubricCanonicalJsonSha256']='0'*64
        with self.assertRaises(c.ContractError):policy.validate_strict_policy(strict,rubric)

    def test_legacy_policy_bytes_and_hashes_remain_frozen(self):
        golden=load('legacy-golden-sha256')
        for name,digest in golden.items():
            if name.endswith('.json'):
                data=(ROOT/'config/target-language-policies'/name).read_bytes();self.assertEqual(c.bytes_sha256(data),digest)
                parsed=json.loads(data);before=c.canonical_bytes(parsed);policy.validate_policy(parsed);self.assertEqual(before,c.canonical_bytes(parsed))
        row=load('legacy-policy-v2');self.assertEqual(policy.validate_policy(row)['translationPolicySha256'],golden['fixtureV2CanonicalJsonSha256'])


if __name__=='__main__':unittest.main()
