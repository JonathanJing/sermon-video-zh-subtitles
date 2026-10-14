"""A budget root may reuse a response another approved root of the run already paid for."""
from pathlib import Path
import tempfile
import unittest

from scripts import sermon_source_budget as subject
from scripts import sermon_workflow_jobs as jobs
from tests.test_source_budget_settlement import AUTHORITY, BOUNDS, IDENTITY, OPERATION, USAGE, call, ledger


def store(root, *, reuse=(), transport=None, authority=AUTHORITY):
    return subject.SourceBudget(root, authority, verify=lambda: None, reuse_roots=reuse,
                                transport=transport or (lambda *args: {"model": "gpt-6.1-sol", "usage": USAGE}))


class ReuseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.text, self.audio = Path(directory.name) / "text", Path(directory.name) / "audio"
        # The text QC root pays for the call once.
        self.paid = call(store(self.text))

    def test_a_paid_response_is_reused_at_no_cost_and_records_where_it_came_from(self):
        dispatched = []
        audio = store(self.audio, reuse=[self.text], transport=lambda *args: dispatched.append(1))
        self.assertEqual(call(audio), self.paid)
        self.assertEqual(dispatched, [])
        row = ledger(self.audio)["requests"][OPERATION]
        self.assertEqual(row["status"], "returned")
        self.assertEqual((row["settlement"]["costStatus"], row["settlement"]["costMicrousd"]), ("reused", 0))
        saved = jobs._read(next((self.audio / "responses").iterdir()))
        self.assertEqual(saved["reusedFrom"]["budgetRoot"], str(self.text.resolve()))
        self.assertEqual(saved["reusedFrom"]["responseSha256"], ledger(self.text)["requests"][OPERATION]["responseSha256"])
        self.assertEqual(saved["reusedFrom"]["originalSettlement"]["costStatus"], "estimated_upper_bound")
        # A replay in the reusing root reads its own copy; the source root is untouched.
        self.assertEqual(call(store(self.audio, reuse=[self.text], transport=lambda *a: self.fail("dispatched"))), self.paid)
        self.assertEqual(len(ledger(self.text)["requests"]), 1)

    def test_a_reused_response_does_not_count_against_the_cap(self):
        tight = dict(AUTHORITY, globalBounds={"requests": 1, "wallTimeMs": 10 ** 9, "costMicrousd": 10 ** 9})
        other = dict(IDENTITY, index=2)
        store(self.text).call(operation="judge." + "d" * 64, identity=other, bounds=BOUNDS, request=b"fixture",
                             api_key="", content_type="fixture", endpoint="fixture")
        audio = store(self.audio, reuse=[self.text], authority=tight)
        call(audio)  # reused, free
        audio.call(operation="judge." + "d" * 64, identity=other, bounds=BOUNDS, request=b"fixture", api_key="",
                   content_type="fixture", endpoint="fixture")  # a second free reuse still fits
        rows = ledger(self.audio)["requests"]
        self.assertEqual(sorted(row["settlement"]["costStatus"] for row in rows.values()), ["reused", "reused"])

    def test_only_an_identical_request_with_an_intact_response_is_reused(self):
        dispatched = []
        audio = store(self.audio, reuse=[self.text], transport=lambda *args: dispatched.append(1) or {"model": "gpt-6.1-sol", "usage": USAGE})
        changed = dict(IDENTITY, index=9)
        with self.assertRaisesRegex(ValueError, "source_reuse_operation_missing"):
            audio.call(operation=OPERATION.replace("c", "e"), identity=changed, bounds=BOUNDS, request=b"fixture",
                       api_key="", content_type="fixture", endpoint="fixture")
        self.assertEqual(dispatched, [])
        # A matching paid receipt that was damaged blocks reconciliation; it is never re-bought.
        response = next((self.text / "responses").iterdir())
        saved = jobs._read(response); saved["response"] = {"model": "forged"}
        response.write_text(__import__("json").dumps(saved))
        fresh = Path(self.audio.parent) / "fresh"
        dispatched.clear()
        with self.assertRaisesRegex(ValueError, "source_reuse_response_reconciliation_required"):
            call(store(fresh, reuse=[self.text], transport=lambda *args: dispatched.append(1)))
        self.assertEqual(dispatched, [])

    def test_without_reuse_roots_the_call_is_paid_as_before(self):
        dispatched = []
        call(store(self.audio, transport=lambda *args: dispatched.append(1) or {"model": "gpt-6.1-sol", "usage": USAGE}))
        self.assertEqual(dispatched, [1])

    def test_a_root_cannot_reuse_itself(self):
        with self.assertRaisesRegex(ValueError, "invalid_source_reuse_roots"):
            store(self.text, reuse=[self.text])


if __name__ == "__main__":
    unittest.main()


class JudgeAuthorizationTests(unittest.TestCase):
    def write(self, directory, *, approved_reuse, requested_reuse):
        import hashlib, json
        bounds = {"globalBounds": {"requests": 10, "wallTimeMs": 10 ** 6, "costMicrousd": 10 ** 6},
                  "requestLimits": dict(subject.text_limits.DEFAULT_REQUEST_LIMITS)}
        root = str(directory / ".api-budget-audio")
        approval = {"schemaVersion": ("sermon-machine-qc-api-budget-approval-v2" if requested_reuse else "sermon-machine-qc-api-budget-approval-v1"), "humanApproval": True, "decision": "approved",
                    "binding": {"budgetRoot": root, **bounds, **({"reuseBudgetRoots": approved_reuse} if approved_reuse else {})}}
        (directory / "approval.json").write_text(json.dumps(approval))
        value = {"schemaVersion": ("sermon-machine-qc-api-budget-authorization-v2" if requested_reuse else "sermon-machine-qc-api-budget-authorization-v1"), "budgetRoot": root,
                 "authority": {"approvalSha256": hashlib.sha256((directory / "approval.json").read_bytes()).hexdigest(),
                               "bounds": bounds, "requestLimits": bounds["requestLimits"]},
                 "approvalReceipt": "approval.json", **({"reuseBudgetRoots": requested_reuse} if requested_reuse else {})}
        (directory / "authorization.json").write_text(json.dumps(value))
        return directory / "authorization.json"

    def test_reuse_roots_must_be_named_by_the_approval(self):
        from unittest.mock import patch
        from scripts import run_machine_qc_clip_test as driver
        with tempfile.TemporaryDirectory() as name, patch("scripts.sermon_openai_runtime.selected_route", return_value=None):
            directory = Path(name)
            unapproved = self.write(directory, approved_reuse=None, requested_reuse=[str(directory / "text")])
            with self.assertRaisesRegex(ValueError, "not bound to its approval"):
                driver.ApiJudge(unapproved)
            approved = self.write(directory, approved_reuse=[str(directory / "text")], requested_reuse=[str(directory / "text")])
            # Bound correctly, it proceeds to the launcher check.
            with self.assertRaisesRegex(ValueError, "dev or prod OpenAI launcher"):
                driver.ApiJudge(approved)

    def test_legacy_v1_rejects_reuse_even_empty_and_scoped_v2_is_not_reuse_v2(self):
        import json
        from unittest.mock import patch
        from scripts import run_machine_qc_clip_test as driver
        with tempfile.TemporaryDirectory() as name,patch('scripts.sermon_openai_runtime.selected_route',return_value=None):
            root=Path(name)
            path=self.write(root,approved_reuse=None,requested_reuse=None)
            with self.assertRaisesRegex(ValueError,'dev or prod OpenAI launcher'):driver.ApiJudge(path)
            value=json.loads(path.read_text());value['reuseBudgetRoots']=[];path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'not bound to its approval'):driver.ApiJudge(path)
            path=self.write(root,approved_reuse=[str(root/'source')],requested_reuse=[str(root/'source')])
            value=json.loads(path.read_text());value['qcContext']={'targetLocale':'ko'};path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'not bound to its approval'):driver.ApiJudge(path)

    def test_judge_source_key_and_project_binding_prevents_cross_root_reuse(self):
        import hashlib,json
        from unittest.mock import patch
        from scripts import run_machine_qc_clip_test as driver
        route={'environment':'dev','credentialAlias':'tongxing-dev-runtime','projectId':'proj_one'}
        schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
        for changed in ('same','key','project'):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as name:
                root=Path(name);source=root/'source';dest=root/'dest';source.mkdir();dest.mkdir()
                source_auth=self.write(source,approved_reuse=None,requested_reuse=None)
                with patch('scripts.sermon_openai_runtime.selected_route',return_value=route),patch.dict('os.environ',{'OPENAI_API_KEY':'synthetic-key-one'}):
                    old=driver.ApiJudge(source_auth)
                    old.ledger.transport=lambda *args:{'model':'gpt-6.1-sol','usage':USAGE,'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}
                    self.assertEqual(old('review','system','user',schema),{'ok':True})
                    response_file=next((old.ledger.root/'responses').iterdir())
                    saved=json.loads(response_file.read_text())
                    self.assertEqual(saved['requestIdentity']['sourceExecutionIdentity']['settings']['credentialSha256'],hashlib.sha256(b'synthetic-key-one').hexdigest())
                    self.assertNotIn('synthetic-key-one',json.dumps(saved))
                reuse=[str(old.ledger.root)]
                dest_auth=self.write(dest,approved_reuse=reuse,requested_reuse=reuse)
                newroute={**route,'projectId':'proj_two'} if changed=='project' else route
                key='synthetic-key-two' if changed=='key' else 'synthetic-key-one'
                with patch('scripts.sermon_openai_runtime.selected_route',return_value=newroute),patch.dict('os.environ',{'OPENAI_API_KEY':key}):
                    new=driver.ApiJudge(dest_auth);calls=[]
                    new.ledger.transport=lambda *args:calls.append(1)
                    if changed=='same':self.assertEqual(new('review','system','user',schema),{'ok':True})
                    else:
                        with self.assertRaisesRegex(ValueError,'source_reuse_operation_missing'):
                            new('review','system','user',schema)
                    self.assertEqual(calls,[])

    def test_environment_key_and_project_mutation_refused_after_judge_admission(self):
        from unittest.mock import patch
        from scripts import run_machine_qc_clip_test as driver
        route={'environment':'dev','credentialAlias':'tongxing-dev-runtime','projectId':'proj_one'}
        with tempfile.TemporaryDirectory() as name,patch('scripts.sermon_openai_runtime.selected_route',return_value=route) as selected,patch.dict('os.environ',{'OPENAI_API_KEY':'synthetic-key'}):
            root=Path(name);path=self.write(root,approved_reuse=None,requested_reuse=None);judge=driver.ApiJudge(path)
            calls=[];judge.ledger.transport=lambda *args:calls.append(1)
            import os
            os.environ['OPENAI_API_KEY']='changed-key'
            with self.assertRaisesRegex(ValueError,'changed after admission'):judge('review','system','user',{})
            os.environ['OPENAI_API_KEY']='synthetic-key';selected.return_value={**route,'projectId':'proj_two'}
            with self.assertRaisesRegex(ValueError,'changed after admission'):judge('review','system','user',{})
            self.assertEqual(calls,[])

    def test_legacy_unversioned_approval_keeps_original_admission(self):
        import hashlib,json
        from unittest.mock import patch
        from scripts import run_machine_qc_clip_test as driver
        with tempfile.TemporaryDirectory() as name,patch('scripts.sermon_openai_runtime.selected_route',return_value=None):
            root=Path(name);path=self.write(root,approved_reuse=None,requested_reuse=None)
            approval=root/'approval.json';value=json.loads(approval.read_text());value.pop('schemaVersion')
            approval.write_text(json.dumps(value));auth=json.loads(path.read_text())
            auth['authority']['approvalSha256']=hashlib.sha256(approval.read_bytes()).hexdigest();path.write_text(json.dumps(auth))
            with self.assertRaisesRegex(ValueError,'dev or prod OpenAI launcher'):driver.ApiJudge(path)
            auth['schemaVersion']='sermon-machine-qc-api-budget-authorization-v2';auth['reuseBudgetRoots']=[str(root/'source')]
            value['binding']['reuseBudgetRoots']=auth['reuseBudgetRoots'];approval.write_text(json.dumps(value))
            auth['authority']['approvalSha256']=hashlib.sha256(approval.read_bytes()).hexdigest();path.write_text(json.dumps(auth))
            with self.assertRaisesRegex(ValueError,'not bound to its approval'):driver.ApiJudge(path)
