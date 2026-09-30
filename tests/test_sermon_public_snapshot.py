"""Aggregate file limits and safe publication; no model/provider calls."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import inspect_canonical_packages as packages
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from scripts import sermon_review_budget as budget
from scripts import sermon_strict_gate_admission as admission
from tests import test_sermon_strict_gate_admission as gates


class PublicSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)

    def test_large_aggregate_roundtrip_immutable_replay_and_private_limit_unchanged(self):
        self.assertEqual(public.MAX_BYTES,packages.MAX_JSON_BYTES)
        self.assertEqual(c.MAX_BYTES,256*1024)
        value={'text':'a'*(c.MAX_BYTES+100)};path=self.root/'candidate.json'
        first=public.save_once(path,value)
        self.assertEqual(public.read_snapshot(path),(value,first))
        self.assertEqual(public.save_once(path,value),first)
        with self.assertRaises(ValueError):c.read_snapshot(path)
        with self.assertRaisesRegex(ValueError,'immutable_public_artifact_changed'):
            public.save_once(path,{'text':'changed'})
        self.assertEqual(path.read_bytes(),first)

    def test_over_limit_never_publishes_and_boundary_includes_newline(self):
        path=self.root/'large.json';value={'text':'123'}
        size=len(c.canonical_bytes(value))+1
        with patch.object(public,'MAX_BYTES',size-1):
            with self.assertRaisesRegex(ValueError,'size_limit'):public.save_once(path,value)
        self.assertFalse(path.exists());self.assertEqual(list(self.root.iterdir()),[])
        with patch.object(public,'MAX_BYTES',size):public.save_once(path,value)
        with patch.object(public,'MAX_BYTES',size-1):
            with self.assertRaisesRegex(ValueError,'invalid_public_snapshot_file'):public.read_snapshot(path)

    def test_duplicates_nonfinite_and_symlink_paths_are_rejected(self):
        for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e999}'):
            with self.assertRaises(ValueError):public.decode_json(raw)
        target=self.root/'target.json';target.write_bytes(b'{}')
        link=self.root/'link.json';link.symlink_to(target)
        with self.assertRaises(ValueError):public.read_snapshot(link)
        with self.assertRaises(ValueError):public.save_once(link,{})
        parent=self.root/'redirect';parent.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):public.read_snapshot(parent/'target.json')

    def test_atomic_publication_failure_recovers_and_competing_value_is_never_overwritten(self):
        path=self.root/'aggregate.json';original=public.os.link
        def lost(*args,**kwargs):original(*args,**kwargs);raise OSError('lost acknowledgement')
        with patch.object(public.os,'link',side_effect=lost):
            with self.assertRaises(OSError):public.save_once(path,{'value':1})
        self.assertEqual(public.read_snapshot(path)[0],{'value':1})
        self.assertEqual(public.save_once(path,{'value':1}),path.read_bytes())
        competing=self.root/'competing.json'
        def replace(*args,**kwargs):
            competing.write_bytes(b'{"value":2}')
            return original(*args,**kwargs)
        with patch.object(public.os,'link',side_effect=replace):
            with self.assertRaisesRegex(ValueError,'immutable_public_artifact_changed'):
                public.save_once(competing,{'value':1})
        self.assertEqual(public.read_snapshot(competing)[0],{'value':2})
        self.assertFalse(any(p.name.startswith('.') for p in self.root.iterdir()))

    def test_concurrent_replacement_during_read_is_not_a_coherent_snapshot(self):
        path=self.root/'snapshot.json';path.write_bytes(b'{"value":1}')
        original=public.os.fstat;calls=[]
        def changed(fd):
            calls.append(fd)
            if len(calls)==2:
                replacement=self.root/'replacement.json';replacement.write_bytes(b'{"value":2}')
                replacement.replace(path)
            return original(fd)
        with patch.object(public.os,'fstat',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'changed_during_read'):public.read_snapshot(path)


class LargePublicGateTests(unittest.TestCase):
    def setUp(self):
        self.f=gates.AdmissionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        for group in self.f.f.groups:
            original=''.join(group['targetUtterances'])
            group['targetUtterances']=[original+'爱'*15500,'爱'*15500]
        self.f.store=budget.BudgetStore(self.f.root/'large-budget',self.f.store.authority)
        self.f.generate_groups();self.f.approve()
        self.f.boundary=admission.AdmissionBoundary(self.f.config,self.f.store)

    def test_actual_large_public_candidate_admits_and_retains_exact_human_receipt(self):
        raw=(self.f.root/'public.json').read_bytes();self.assertGreater(len(raw),c.MAX_BYTES)
        with self.assertRaises(ValueError):c.decode_json(raw)
        snapshot=self.f.boundary.snapshot()
        self.assertEqual(snapshot.files['public_candidate'],raw)
        for group in snapshot.groups:
            descriptor=next(a for a in group.materials if a.artifact_id=='public-candidate-binding')
            self.assertEqual(c.decode_json(descriptor.data)['fileBytesSha256'],c.bytes_sha256(raw))
            self.assertTrue(all(len(a.data)<=c.MAX_BYTES for a in group.materials))
        value=self.f.admit(snapshot.state_revision)
        self.assertEqual(value['status'],'committed',value)
        human_raw=(self.f.root/'human.json').read_bytes()
        for decision in value['intent']['decisions']:
            self.assertEqual(decision['approvalReceiptRefs'][0]['fileBytesSha256'],c.bytes_sha256(human_raw))
        self.assertEqual(self.f.admit()['status'],'existing')
        self.assertEqual(len(self.f.f.f.calls),4)

    def test_second_current_snapshot_rechecks_entire_large_public_bytes(self):
        revision=self.f.boundary.snapshot().state_revision
        original=self.f.boundary._validate
        def mutate(snapshot,created_at):
            result=original(snapshot,created_at)
            path=self.f.root/'public.json';path.write_bytes(path.read_bytes()+b' ')
            return result
        with patch.object(self.f.boundary,'_validate',side_effect=mutate):
            result=self.f.admit(revision)
        self.assertEqual(result['status'],'stale',result)
        self.assertEqual(self.f.boundary.reconcile()['intents'],[])

    def test_large_human_receipt_is_not_silently_promoted_to_public_limit(self):
        path=self.f.root/'human.json';value=public.read_snapshot(path)[0]
        value['testPadding']='a'*(c.MAX_BYTES+1);path.write_bytes(c.canonical_bytes(value))
        with self.assertRaises(ValueError):self.f.boundary.snapshot()


if __name__=='__main__':unittest.main()
