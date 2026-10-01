"""Explicit simulated human gates; real strict producers, synthetic transport."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from scripts import sermon_diagnostic_context as diagnostic
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_strict_locale as locale
from scripts import sermon_strict_candidate_bridge as bridge
from scripts import prepare_target_language_speech_job as speech
from scripts import build_english_source_package as english
from scripts import produce_target_language_candidate as producer
from scripts import target_language_policy as policies
from scripts import sermon_accounting as accounting
from tests import test_sermon_strict_locale as locale_fixtures


def reidentify(source):
    identity = english.source_identity(source['source'], source['transcript']['artifact'],
        source['anchors']['artifact'], source['review'], source['evidence']['machineJudge'], source['implementation'])
    source.update(downstreamInvalidationKey=identity, packageId='english-source-'+identity[:24])


class DiagnosticContextTests(unittest.TestCase):
    def setUp(self):
        self.f=locale_fixtures.LocaleTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        source,anchor,policy,rubric=map(c.decode_json,self.f.f.args)
        source.update(status='blocked',translationEligible=False,candidateTranslationEligible=False)
        source['review'].update(humanApproval=False, reviewedBy=None, reviewedAt=None,
            reviewedSourceUnitIds=[],evidence=None,checks={k:'pending' for k in diagnostic.PENDING_CHECKS})
        source['source']['approvedWindow'].update(status='pending',humanApproval=False,evidence=None)
        source['transcript']['completenessReview']='pending'
        source['issues']=[{'stage':'source','type':'approved_sermon_window_missing'}]+[
            {'stage':'review','type':name+'_review_pending'} for name in diagnostic.PENDING_CHECKS]
        reidentify(source)
        policy['sourceScope']['englishSourcePackageJsonSha256']=c.canonical_sha256(source)
        policy['componentSha256']['sourceScope']=c.canonical_sha256(policy['sourceScope'])
        self.source,self.anchor,self.policy,self.rubric=source,anchor,policy,rubric
        self.f.f.args=[strict.material_bytes(x) for x in (source,anchor,policy,rubric)]
        self.context=dict(schemaVersion=diagnostic.SCHEMA,runId=self.f.kw['production_run_id'],
            runConfigSha256='1'*64,storeSha256=self.f.store.store_sha256,
            sourceCanonicalSha256=c.canonical_sha256(source),anchorCanonicalSha256=c.canonical_sha256(anchor),
            simulationAuthorizationRef='2'*64,continuationCodeCommit='3'*40,
            humanAcceptance='pending',productionEligible=False)

    def run_locale(self,context=None):
        return locale.run_locale(*self.f.f.args,**self.f.kw,diagnostic_context=context)

    def test_no_context_keeps_production_gate_and_makes_no_calls(self):
        with self.f.f.session(),self.assertRaisesRegex(ValueError,'Approved English Source'):
            self.run_locale()
        self.assertEqual(self.f.f.calls,[])
        with self.assertRaises(ValueError):producer.validate_source_for_translation(self.source,self.anchor)
        self.assertFalse(self.source['translationEligible']);self.assertFalse(self.source['review']['humanApproval'])

    def test_real_generator_reviewer_plugin_bridge_and_replay_preserve_pending(self):
        before=[bytes(raw) for raw in self.f.f.args]
        with self.f.f.session():
            result=self.run_locale(self.context)
            replay=self.run_locale(self.context)
        self.assertEqual(result['status'],'waiting_human')
        self.assertEqual(result['candidateSha256'],replay['candidateSha256'])
        self.assertEqual(len(self.f.f.calls),4)
        events,errors=accounting.read_events(self.f.f.root/'logs')
        self.assertFalse(errors)
        observed=[row['metrics'] for row in events if row.get('stage')=='rqc.locale_input' and row.get('event')=='workload']
        self.assertTrue(observed)
        self.assertTrue(all(row.get('simulatedHumanGate') is True and row.get('productionEligible') is False
            and row.get('diagnosticContextSha256')==c.canonical_sha256(self.context) for row in observed))
        self.assertEqual(before,self.f.f.args)
        candidates=list((self.f.f.root/'locale'/'machine-candidates').glob('*/candidate.json'))
        self.assertEqual(len(candidates),1)
        candidate=json.loads(candidates[0].read_text())
        self.assertEqual(candidate['humanReview']['translation'],'pending')
        self.assertFalse(candidate['releaseEligible'])
        self.assertEqual(len(list((self.f.f.root/'locale').rglob('diagnostic-context.json'))),2)
        with self.assertRaises(ValueError):speech.validate_target_candidate(self.source,self.anchor,candidate)
        with self.assertRaisesRegex(ValueError,'cannot grant production'):
            speech.validate_target_candidate(self.source,self.anchor,candidate,diagnostic_context=self.context)
        with self.assertRaises(ValueError):
            bridge.compile_candidate(*self.f.f.args,[],plugin_path=self.f.f.f.plugin_path,
                expected_plugin_sha256=self.f.f.f.plugin_sha)

    def test_context_hash_runtime_and_approval_tampering_rejected(self):
        for key,value in [('sourceCanonicalSha256','f'*64),('anchorCanonicalSha256','f'*64),
                          ('productionEligible',True),('humanAcceptance','approved')]:
            with self.subTest(key=key):
                context={**self.context,key:value}
                with self.assertRaises(ValueError):diagnostic.validate_source(self.source,self.anchor,context)
        for key in ('runId','storeSha256'):
            with self.f.f.session(),self.assertRaisesRegex(ValueError,'runtime_binding'):
                self.run_locale({**self.context,key:'f'*64})
        self.assertEqual(self.f.f.calls,[])

    def test_rebound_context_does_not_override_media_alignment_or_derived_identity(self):
        for change in ('media','window','alignment','identity','issue'):
            source=deepcopy(self.source)
            if change=='media':source['source']['media']=None
            elif change=='window':source['source']['approvedWindow']['endSeconds']=0
            elif change=='alignment':source['alignment']['issueCount']=1
            elif change=='identity':source['downstreamInvalidationKey']='f'*64
            else:source['issues'].append({'stage':'anchors','type':'alignment_failed'})
            context={**self.context,'sourceCanonicalSha256':c.canonical_sha256(source)}
            with self.subTest(change=change),self.assertRaises(ValueError):
                diagnostic.validate_source(source,self.anchor,context)

    def test_only_bounded_named_clause_warning_is_allowed(self):
        anchor=deepcopy(self.anchor)
        warning=dict(type=diagnostic.CLAUSE_WARNING,durationSeconds=9.,maximumSeconds=8.)
        anchor['issues']=[warning]
        source=deepcopy(self.source)
        source['anchors']['artifact']['jsonSha256']=c.canonical_sha256(anchor)
        source['issues'].append(dict(stage='anchors',type=diagnostic.CLAUSE_WARNING,detail=warning))
        reidentify(source)
        context={**self.context,'sourceCanonicalSha256':c.canonical_sha256(source),
                 'anchorCanonicalSha256':c.canonical_sha256(anchor)}
        self.assertEqual(diagnostic.validate_source(source,anchor,context),c.canonical_sha256(anchor))
        warning['durationSeconds']=15.
        source['anchors']['artifact']['jsonSha256']=c.canonical_sha256(anchor);reidentify(source)
        context.update(sourceCanonicalSha256=c.canonical_sha256(source),anchorCanonicalSha256=c.canonical_sha256(anchor))
        with self.assertRaisesRegex(ValueError,'anchor_issue_not_permitted'):
            diagnostic.validate_source(source,anchor,context)

    def test_sidecar_cannot_be_replaced_or_context_removed_on_replay(self):
        with self.f.f.session():self.run_locale(self.context)
        contexts=list((self.f.f.root/'locale').rglob('diagnostic-context.json'))
        changed={**self.context,'simulationAuthorizationRef':'9'*64}
        contexts[0].write_text(json.dumps(changed))
        with self.f.f.session():
            result=self.run_locale(self.context)
        self.assertEqual(result['status'],'blocked')
        self.assertIsNone(result['output'])
        self.assertEqual(len(self.f.f.calls),4)


    def test_simulated_human_context_does_not_simulate_model_pass(self):
        prepared=strict.prepare(*self.f.f.args,self.f.f.group,diagnostic_context=self.context)
        self.f.f.mode='fail'
        with self.f.f.session():
            strict.generate(prepared,self.f.f.root/'single','candidate','r1','synthetic',self.f.f.transport)
            receipt=strict.review(prepared,self.f.f.root/'single','candidate','r1','synthetic',self.f.f.transport)
        self.assertEqual(receipt['reviewVerdict'],'needs_rework')
        self.assertTrue(receipt['issues'])
        self.assertEqual(len(self.f.f.calls),2)

    def test_only_pending_human_term_policy_codes_are_simulated_without_mutation(self):
        policy=deepcopy(self.policy)
        term=dict(source='Synthetic Name',target='示例名',reviewStatus='pending')
        policy['terminology']['properNames']=[term]
        policy['sourceScope']['usedProperNames']=[term['source']]
        policy['sourceScope']['termApprovalEvidence']=[]
        for key in ('terminology','sourceScope'):
            policy['componentSha256'][key]=c.canonical_sha256(policy[key])
        before=deepcopy(policy)
        identity=policies.validate_strict_policy(policy,self.rubric)
        self.assertFalse(identity['productionPolicyReady'])
        self.assertEqual(set(identity['unresolved']),{'terminology_review_pending','proper_name_approval_evidence_pending'})
        diagnostic.require_policy_ready(identity,self.context)
        self.assertFalse(identity['productionPolicyReady']);self.assertEqual(before,policy)
        with self.assertRaises(ValueError):diagnostic.require_policy_ready(identity)
        for code in ('scripture_policy_pending','language_review_plugin_pending','unknown_blocker'):
            with self.subTest(code=code),self.assertRaisesRegex(ValueError,'policy_blocker_not_permitted'):
                diagnostic.require_policy_ready({**identity,'unresolved':identity['unresolved']+[code]},self.context)


if __name__=='__main__':unittest.main()
