"""Reuse preflight mirrors runtime response/settlement gates without dispatch or writes."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import check_run_start as check
from tongxing_production.source import budget as source
from tongxing_production.orchestration import jobs
from tests.test_source_budget_settlement import AUTHORITY, IDENTITY, OPERATION, USAGE, call


class ReuseReceiptIntegrityTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.base=Path(temp.name);self.paid=self.base/'paid';self.destination=self.base/'new'
        store=source.SourceBudget(self.paid,AUTHORITY,verify=lambda:None,transport=lambda *args:{'model':'gpt-6.1-sol','usage':USAGE})
        call(store)
        self.ledger_path=self.paid/'source-budget.json';self.response_path=next((self.paid/'responses').glob('*.json'))
        self.original_ledger=json.loads(self.ledger_path.read_text());self.original_saved=json.loads(self.response_path.read_text())

    def save(self,ledger=None,saved=None):
        ledger=json.loads(json.dumps(self.original_ledger)) if ledger is None else ledger
        saved=json.loads(json.dumps(self.original_saved)) if saved is None else saved
        ledger['requests'][OPERATION]['responseSha256']=jobs._digest(saved)
        self.ledger_path.write_text(json.dumps(ledger));self.response_path.write_text(json.dumps(saved))

    def assert_rejected_without_writes(self):
        before={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in self.base.rglob('*') if p.is_file()}
        with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            with self.assertRaises(ValueError):check.inspect_source_root(self.paid,required=True,as_reuse_source=True)
            reusable=source.SourceBudget(self.destination,AUTHORITY,verify=lambda:None,reuse_roots=[self.paid],transport=lambda *args:self.fail('provider call'))
            with self.assertRaises(ValueError):reusable._reusable(OPERATION,jobs._digest(IDENTITY))
        self.assertEqual(before,{str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in self.base.rglob('*') if p.is_file()})
        self.assertFalse(self.destination.exists())

    def test_hash_matching_nonobject_response_never_counts_as_reusable(self):
        for response in [None,[], 'syntactically valid JSON',1,True]:
            with self.subTest(response=response):
                saved=json.loads(json.dumps(self.original_saved));saved['response']=response;self.save(saved=saved)
                self.assert_rejected_without_writes()

    def test_hash_matching_nonobject_receipt_fails_cleanly(self):
        self.save(saved=[]);self.assert_rejected_without_writes()

    def test_malformed_recorded_legacy_settlement_cannot_be_recomputed_away(self):
        for version in ['sermon-source-budget-ledger-v1',source.LEDGER_V2]:
            for settlement in [None,{'costStatus':'unsupported','costMicrousd':None},{'costStatus':'unknown','costMicrousd':-1}]:
                with self.subTest(version=version,settlement=settlement):
                    ledger=json.loads(json.dumps(self.original_ledger));ledger['schemaVersion']=version
                    ledger.pop('reuseBudgetRoots');ledger['requests'][OPERATION].pop('settlement')
                    if version.endswith('-v1'):
                        ledger.pop('maxConcurrent');ledger.pop('resourcePolicySha256')
                    saved=json.loads(json.dumps(self.original_saved));saved['settlement']=settlement
                    self.save(ledger,saved);self.assert_rejected_without_writes()

    def test_valid_but_different_saved_settlement_fails_for_both_settled_versions(self):
        for version in [source.LEDGER_V3,source.LEDGER_V4]:
            with self.subTest(version=version):
                ledger=json.loads(json.dumps(self.original_ledger));ledger['schemaVersion']=version
                if version==source.LEDGER_V3:ledger.pop('reuseBudgetRoots')
                saved=json.loads(json.dumps(self.original_saved));saved['settlement']['costMicrousd']+=1
                self.save(ledger,saved);self.assert_rejected_without_writes()

    def test_valid_paid_receipt_and_legacy_computed_settlement_still_pass_read_only(self):
        for version in ['sermon-source-budget-ledger-v1',source.LEDGER_V2,source.LEDGER_V3,source.LEDGER_V4]:
            with self.subTest(version=version):
                ledger=json.loads(json.dumps(self.original_ledger));ledger['schemaVersion']=version
                saved=json.loads(json.dumps(self.original_saved))
                if version!=source.LEDGER_V4:ledger.pop('reuseBudgetRoots')
                if version not in source.SETTLED_LEDGERS:
                    ledger['requests'][OPERATION].pop('settlement');saved.pop('settlement')
                if version.endswith('-v1'):
                    ledger.pop('maxConcurrent');ledger.pop('resourcePolicySha256')
                self.save(ledger,saved)
                before={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in self.base.rglob('*') if p.is_file()}
                check.inspect_source_root(self.paid,required=True,as_reuse_source=True)
                self.assertEqual(before,{str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in self.base.rglob('*') if p.is_file()})
