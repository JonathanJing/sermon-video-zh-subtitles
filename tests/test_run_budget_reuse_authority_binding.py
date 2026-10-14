"""Prior plan, approved root and paid ledger must be the same QC authority."""
import copy
import json
from pathlib import Path
import unittest
from scripts import plan_run_budgets as p, check_run_start as check
from tests import test_run_budget_qc_resume as fixtures
from tests import test_run_start_tools as tools


class ReuseAuthorityBindingTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.QcResumePlanTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.base=self.f.f.base;self.plan_path=self.base/'run/plan.json'
        self.original=json.loads(self.plan_path.read_text())
        self.root=Path(self.f.stage['budgetRoot'])

    def run_reuse(self,name='replay'):
        return tools.run_plan(*self.f.f.args(name,extra=['--reuse-from',str(self.base/'run')]))

    def files(self):
        return {str(path):(path.read_bytes(),path.stat().st_mtime_ns) for path in self.root.rglob('*') if path.is_file()}

    def test_valid_original_authority_replay_plan_preserves_source_business_files(self):
        before=self.files();self.assertEqual(self.run_reuse()[0],0)
        self.assertEqual(self.files(),before)
        self.assertEqual(self.f.f.load('replay')['stages'][0]['executionMode'],'replay_only')

    def test_other_valid_authority_cannot_replace_selected_prior_ledger(self):
        path=self.root/'source-budget.json';value=json.loads(path.read_text())
        # This is a structurally valid authority with the same bounds and all
        # original response/row hashes. It is a different approval, not corruption.
        value['authority']['approvalSha256']='b'*64;path.write_text(json.dumps(value))
        before=self.files()
        with self.assertRaisesRegex(ValueError,'another approval'):
            self.run_reuse()
        self.assertFalse((self.base/'replay').exists());self.assertEqual(self.files(),before)

    def test_prior_plan_or_aggregate_approval_hash_change_refuses_before_writes(self):
        for mutation in ('plan','approval'):
            with self.subTest(mutation=mutation):
                original=self.plan_path.read_bytes()
                receipt=self.plan_path.parent/self.original['approvalReceipt'];receipt_bytes=receipt.read_bytes()
                if mutation=='plan':
                    value=copy.deepcopy(self.original);value['settledUsd']+=1;self.plan_path.write_text(json.dumps(value))
                else:
                    value=json.loads(receipt_bytes);value['operatorEvidence']='edited';receipt.write_text(json.dumps(value))
                before=self.files()
                with self.assertRaisesRegex(ValueError,'prior plan'):
                    self.run_reuse('changed-'+mutation)
                self.assertFalse((self.base/('changed-'+mutation)).exists());self.assertEqual(self.files(),before)
                self.plan_path.write_bytes(original);receipt.write_bytes(receipt_bytes)

    def test_approved_prior_stage_cannot_redirect_root_or_pin_wrong_auth_hash(self):
        for field in ('budgetRoot','authorizationSha256','approvalSha256'):
            with self.subTest(field=field):
                value=copy.deepcopy(self.original)
                value['stages'][0][field]=str(self.base/'other-root') if field=='budgetRoot' else 'e'*64
                receipt=self.plan_path.parent/value['approvalReceipt'];approved=json.loads(receipt.read_text())
                approved['binding']={k:v for k,v in value.items() if k not in {'approvalReceipt','approvalSha256'}}
                receipt.write_text(json.dumps(approved));value['approvalSha256']=p.file_sha256(receipt)
                self.plan_path.write_text(json.dumps(value));before=self.files()
                with self.assertRaisesRegex(ValueError,'prior stage'):
                    self.run_reuse('stage-'+field)
                self.assertFalse((self.base/('stage-'+field)).exists());self.assertEqual(self.files(),before)

    def test_preflight_rechecks_frozen_prior_authority_and_plan_references(self):
        self.assertEqual(self.run_reuse()[0],0)
        target=self.base/'replay'
        self.assertEqual(check.check_budget(target)['status'],'pass')
        stage=self.f.f.load('replay')['stages'][0]
        self.assertEqual(stage['reuseSources'][0]['authority'],json.loads((self.root/'source-budget.json').read_text())['authority'])
        sources=[self.root/'source-budget.json',Path(self.f.stage['authorization']),self.plan_path]
        for source in sources:
            with self.subTest(source=source.name):
                original=source.read_bytes();value=json.loads(original)
                if source.name=='source-budget.json':value['authority']['approvalSha256']='d'*64
                elif source==self.plan_path:value['settledUsd']+=1
                else:value['authority']['bounds']['globalBounds']['requests']+=1
                source.write_text(json.dumps(value));before=self.files()
                self.assertEqual(check.check_budget(target)['status'],'fail')
                self.assertEqual(self.files(),before);source.write_bytes(original)
