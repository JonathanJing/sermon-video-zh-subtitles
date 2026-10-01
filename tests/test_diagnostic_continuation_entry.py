"""Existing-ledger/code/deadline bindings; no real credentials or transport."""
import copy
import json
import unittest
from unittest.mock import patch
from scripts import run_bounded_diagnostic_continuation as entry
from scripts import sermon_accounting as accounting
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_review_budget as budget
from tests import test_run_bounded_diagnostic as fixtures

class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.BoundedRunTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.root=self.f.f.root
        self.identity={'gitCommit':'b'*40,'trackedWorkingTreeDirty':False}
        original={'gitCommit':'a'*40,'trackedWorkingTreeDirty':False}
        config={**self.f.subject.config,'codeSha256':c.canonical_sha256(original)}
        self.subject=provider.DiagnosticProvider(self.f.subject.store,config,executor=self.f.capture, domain=lambda:"7"*64)
        self.plan={'schemaVersion':'sermon-bounded-diagnostic-plan-v1','runDirectory':str(self.root),
                   'providerConfig':config,'authority':self.subject.store.authority,
                   'executionIdentity':original,'sourceClipPath':str(self.f.clip)}
        strict.save_once(self.root/'run-plan.json',self.plan)
        self.context=dict(schemaVersion='sermon-diagnostic-context-v1',runId=config['runId'],
            runConfigSha256=c.canonical_sha256(config),storeSha256=self.subject.store.store_sha256,
            sourceCanonicalSha256='4'*64,anchorCanonicalSha256='5'*64,
            simulationAuthorizationRef='6'*64,continuationCodeCommit=self.identity['gitCommit'],
            humanAcceptance='pending',productionEligible=False)
        self.cont=dict(schemaVersion='sermon-diagnostic-continuation-v1',
            originalPlanSha256=c.canonical_sha256(self.plan),executionIdentity=self.identity,
            diagnosticContext=self.context)
        with self.f.f.session():self.subject.transcribe('synthetic',self.f.raw)
        self.statepath=self.root/'budget'/budget.STORE_ID/'provider-run/state.json'
        self.original_state=self.statepath.read_bytes()

    def prepare(self):
        constructor=provider.DiagnosticProvider
        with patch.object(accounting,'execution_identity',return_value=self.identity), patch.object(
                entry.provider,'DiagnosticProvider', side_effect=lambda store,config: constructor(store,config,domain=lambda:'7'*64)):
            return entry.prepare_continuation(self.plan,self.cont)

    def test_reuses_prior_receipt_budget_deadline_without_call_or_mutation(self):
        root,subject,context,deadline=self.prepare()
        state=json.loads(self.original_state)
        self.assertEqual(root,self.root.resolve())
        self.assertEqual(deadline,state['startedMonotonic']+5400)
        self.assertEqual(subject.config,self.subject.config)
        self.assertEqual(context,self.context)
        self.assertEqual(subject.snapshot()['requestCount'],1)
        self.assertEqual(self.statepath.read_bytes(),self.original_state)
        self.assertEqual(len(self.f.calls),1)

    def test_foreign_config_code_source_and_missing_store_fail_before_dispatch(self):
        for key,value in [('runConfigSha256','e'*64),('storeSha256','e'*64),
                          ('continuationCodeCommit','e'*40),('productionEligible',True)]:
            with self.subTest(key=key):
                old=self.context[key];self.context[key]=value
                with self.assertRaises(ValueError):self.prepare()
                self.context[key]=old
        self.f.clip.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'source_clip_changed'):self.prepare()
        self.f.clip.write_bytes(b'synthetic approved clip')
        self.statepath.unlink()
        with self.assertRaisesRegex(ValueError,'existing_provider_required'):self.prepare()
        self.assertFalse(self.statepath.exists())
        self.assertEqual(len(self.f.calls),1)

    def test_unknown_prior_result_and_expired_clock_do_not_reset_or_retry(self):
        state=json.loads(self.original_state)
        next(iter(state['requests'].values()))['state']='outcome_unknown'
        self.statepath.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError,'requires_reconciliation'):self.prepare()
        state=json.loads(self.original_state);state['startedMonotonic']-=5401
        self.statepath.write_text(json.dumps(state));before=self.statepath.read_bytes()
        with self.assertRaisesRegex(ValueError,'deadline'):self.prepare()
        self.assertEqual(self.statepath.read_bytes(),before)
        self.assertEqual(len(self.f.calls),1)

if __name__=='__main__':unittest.main()
